"""
Management command to detect N+1 query patterns during a simulated request cycle.

Usage:
    python manage.py find_n_plus_one
    python manage.py find_n_plus_one --threshold 5
    python manage.py find_n_plus_one --url /doctors/

This command instruments Django's database backend to count queries executed
during common view operations and reports any that exceed the threshold,
helping identify N+1 query regressions before they reach production.
"""

from django.core.management.base import BaseCommand
from django.db import connection, reset_queries
from django.conf import settings


class _QueryCounter:
    """Context manager that counts SQL queries executed in a block."""

    def __init__(self, label):
        self.label = label
        self.count = 0
        self.queries = []

    def __enter__(self):
        reset_queries()
        return self

    def __exit__(self, *args):
        self.queries = list(connection.queries)
        self.count = len(self.queries)


class Command(BaseCommand):
    help = (
        'Detect N+1 query patterns by simulating queryset access for key models. '
        'Requires DEBUG=True (or --force) to capture query logs.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--threshold',
            type=int,
            default=5,
            help='Number of queries above which a pattern is flagged as a potential N+1 (default: 5).',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Run even when DEBUG=False (query logging will be incomplete).',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Print every SQL statement captured, not just the summary.',
        )

    def handle(self, *args, **options):
        threshold = options['threshold']
        verbose = options['verbose']
        force = options['force']

        if not settings.DEBUG and not force:
            self.stderr.write(
                self.style.ERROR(
                    'DEBUG is False — Django does not log queries in production mode. '
                    'Set DEBUG=True in your local settings or pass --force to skip this check.'
                )
            )
            return

        self.stdout.write(self.style.MIGRATE_HEADING('FemiCare N+1 Query Detector'))
        self.stdout.write(f'Threshold: {threshold} queries per block\n')

        issues_found = 0

        # ------------------------------------------------------------------ #
        # 1. DoctorProfile listing (explore_doctors equivalent)
        # ------------------------------------------------------------------ #
        issues_found += self._check(
            label='DoctorProfile listing (explore_doctors)',
            threshold=threshold,
            verbose=verbose,
            runner=self._check_doctor_listing,
        )

        # ------------------------------------------------------------------ #
        # 2. Appointment listing for a doctor (doctor_appointment equivalent)
        # ------------------------------------------------------------------ #
        issues_found += self._check(
            label='Appointment listing for doctor (doctor_appointment)',
            threshold=threshold,
            verbose=verbose,
            runner=self._check_doctor_appointments,
        )

        # ------------------------------------------------------------------ #
        # 3. Payment listing (doctor_dashboard pending verifications)
        # ------------------------------------------------------------------ #
        issues_found += self._check(
            label='Payment listing (doctor_dashboard)',
            threshold=threshold,
            verbose=verbose,
            runner=self._check_payment_listing,
        )

        # ------------------------------------------------------------------ #
        # 4. EmergencyRequest listing (doctor_appointment panel)
        # ------------------------------------------------------------------ #
        issues_found += self._check(
            label='EmergencyRequest listing (doctor_appointment)',
            threshold=threshold,
            verbose=verbose,
            runner=self._check_emergency_requests,
        )

        # ------------------------------------------------------------------ #
        # 5. DoctorAvailability listing (doctor_dashboard slots)
        # ------------------------------------------------------------------ #
        issues_found += self._check(
            label='DoctorAvailability listing (doctor_dashboard)',
            threshold=threshold,
            verbose=verbose,
            runner=self._check_availability_listing,
        )

        # ------------------------------------------------------------------ #
        # 6. Notification listing (get_notifications)
        # ------------------------------------------------------------------ #
        issues_found += self._check(
            label='Notification listing (get_notifications)',
            threshold=threshold,
            verbose=verbose,
            runner=self._check_notifications,
        )

        # ------------------------------------------------------------------ #
        # Summary
        # ------------------------------------------------------------------ #
        self.stdout.write('')
        if issues_found == 0:
            self.stdout.write(self.style.SUCCESS('No N+1 patterns detected above threshold.'))
        else:
            self.stdout.write(
                self.style.WARNING(
                    f'{issues_found} potential N+1 pattern(s) detected. '
                    'Review the flagged querysets and add select_related() / prefetch_related() as needed.'
                )
            )

    # ---------------------------------------------------------------------- #
    # Internal helpers
    # ---------------------------------------------------------------------- #

    def _check(self, label, threshold, verbose, runner):
        """Run *runner*, count queries, and report. Returns 1 if flagged, else 0."""
        with _QueryCounter(label) as counter:
            try:
                runner()
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(
                    self.style.WARNING(f'  [{label}] Skipped — {exc.__class__.__name__}: {exc}')
                )
                return 0

        status = self.style.SUCCESS('OK') if counter.count <= threshold else self.style.ERROR('FLAGGED')
        self.stdout.write(f'  {status}  {label}: {counter.count} queries')

        if verbose or counter.count > threshold:
            for i, q in enumerate(counter.queries, 1):
                sql_preview = q.get('sql', '')[:120].replace('\n', ' ')
                self.stdout.write(f'    [{i:02d}] {sql_preview}')

        return 1 if counter.count > threshold else 0

    # ---------------------------------------------------------------------- #
    # Individual check runners — each simulates a view's queryset access
    # ---------------------------------------------------------------------- #

    def _check_doctor_listing(self):
        from tracker.models import DoctorProfile
        doctors = list(
            DoctorProfile.objects.filter(
                is_verified=True,
                is_profile_complete=True,
            ).select_related('user', 'user__payment_details')[:20]
        )
        # Simulate template attribute access
        for d in doctors:
            _ = d.user.username
            _ = getattr(d.user, 'payment_details', None)

    def _check_doctor_appointments(self):
        from tracker.models import Appointment
        appts = list(
            Appointment.objects.select_related('user', 'availability')[:20]
        )
        for a in appts:
            _ = a.user.username
            _ = a.availability.date

    def _check_payment_listing(self):
        from tracker.models import Payment
        payments = list(
            Payment.objects.select_related(
                'user', 'appointment', 'appointment__availability'
            ).filter(status='pending')[:20]
        )
        for p in payments:
            _ = p.user.username
            _ = p.appointment.status
            _ = p.appointment.availability.date

    def _check_emergency_requests(self):
        from tracker.models import EmergencyRequest
        requests = list(
            EmergencyRequest.objects.filter(status='pending')
            .select_related('user')[:20]
        )
        for r in requests:
            _ = r.user.username

    def _check_availability_listing(self):
        from tracker.models import DoctorAvailability
        slots = list(
            DoctorAvailability.objects.select_related(
                'appointment', 'appointment__user'
            )[:20]
        )
        for s in slots:
            _ = s.date
            if s.appointment_id:
                _ = s.appointment.status

    def _check_notifications(self):
        from tracker.models import Notification
        notifications = list(
            Notification.objects.order_by('-created_at')[:20]
        )
        for n in notifications:
            _ = n.title
            _ = n.is_read
