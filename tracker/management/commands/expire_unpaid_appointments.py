from django.core.management.base import BaseCommand
from django.utils import timezone

from tracker.models import Appointment


class Command(BaseCommand):
    help = 'Expire awaiting-payment appointments that passed payment_due_at and release their slots.'

    def handle(self, *args, **options):
        now = timezone.localtime(timezone.now())
        overdue = Appointment.objects.filter(
            status='awaiting_payment',
            payment_due_at__isnull=False,
            payment_due_at__lt=now,
        ).select_related('availability')

        expired_count = 0
        for appt in overdue:
            slot = appt.availability
            slot.is_active = True
            slot.save(update_fields=['is_active'])
            appt.delete()
            expired_count += 1

        self.stdout.write(self.style.SUCCESS(f'Expired unpaid appointments: {expired_count}'))
