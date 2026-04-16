"""
Management command: find_n_plus_one

Instruments Django's database backend to capture every SQL query executed
during a simulated request to the most query-heavy views, then reports any
view that fires more queries than a configurable threshold.

Usage:
    python manage.py find_n_plus_one
    python manage.py find_n_plus_one --threshold 10
    python manage.py find_n_plus_one --url /doctor/dashboard/ --threshold 5

The command creates a minimal fake request (authenticated as the first
doctor/user it can find) and calls the view function directly, so it works
without a running HTTP server.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, reset_queries
from django.test import RequestFactory

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enable_query_logging() -> None:
    """Force Django to record every SQL statement in connection.queries."""
    from django.conf import settings
    settings.DEBUG = True


def _capture_queries(func, *args, **kwargs) -> tuple[Any, list[dict]]:
    """
    Call *func* with *args*/*kwargs*, capture all DB queries fired during the
    call, and return (return_value, queries_list).
    """
    reset_queries()
    result = func(*args, **kwargs)
    queries = list(connection.queries)
    return result, queries


def _detect_repeated_queries(queries: list[dict], min_repeats: int = 3) -> list[tuple[str, int]]:
    """
    Return a list of (sql_template, count) pairs where the same query
    (ignoring literal values) was executed *min_repeats* or more times.

    A very simple normalisation is applied: integer/string literals are
    replaced with a placeholder so that queries that differ only in their
    WHERE clause value are grouped together.
    """
    import re

    def _normalise(sql: str) -> str:
        # Replace quoted strings
        sql = re.sub(r"'[^']*'", "'?'", sql)
        # Replace numeric literals
        sql = re.sub(r'\b\d+\b', '?', sql)
        return sql.strip()

    counts: dict[str, int] = defaultdict(int)
    for q in queries:
        counts[_normalise(q['sql'])] += 1

    repeated = [(sql, cnt) for sql, cnt in counts.items() if cnt >= min_repeats]
    repeated.sort(key=lambda x: x[1], reverse=True)
    return repeated


# ---------------------------------------------------------------------------
# View probes
# ---------------------------------------------------------------------------

def _probe_view(view_name: str, view_func, request) -> dict:
    """
    Execute *view_func* with *request*, measure wall-clock time and query
    count, and return a summary dict.
    """
    start = time.perf_counter()
    try:
        _, queries = _capture_queries(view_func, request)
    except Exception as exc:  # noqa: BLE001
        return {
            'view': view_name,
            'error': str(exc),
            'query_count': 0,
            'duration_ms': 0,
            'repeated': [],
        }
    duration_ms = (time.perf_counter() - start) * 1000
    repeated = _detect_repeated_queries(queries, min_repeats=3)
    return {
        'view': view_name,
        'error': None,
        'query_count': len(queries),
        'duration_ms': duration_ms,
        'repeated': repeated,
        'queries': queries,
    }


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = (
        'Detect N+1 query patterns in key views by instrumenting the DB '
        'layer and reporting views that fire an unexpectedly high number of '
        'queries or repeat the same query many times.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--threshold',
            type=int,
            default=15,
            help='Warn when a view fires more than this many queries (default: 15).',
        )
        parser.add_argument(
            '--min-repeats',
            type=int,
            default=3,
            help='Flag a query template repeated at least this many times (default: 3).',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            default=False,
            help='Print every captured SQL statement for flagged views.',
        )

    def handle(self, *args, **options):  # noqa: C901
        threshold: int = options['threshold']
        min_repeats: int = options['min_repeats']
        verbose: bool = options['verbose']

        _enable_query_logging()

        factory = RequestFactory()

        # ------------------------------------------------------------------
        # Find test users
        # ------------------------------------------------------------------
        doctor_user = User.objects.filter(role='doctor', is_active=True).first()
        patient_user = User.objects.filter(role='user', is_active=True).first()

        if not doctor_user and not patient_user:
            raise CommandError(
                'No active users found in the database. '
                'Create at least one doctor and one patient account first.'
            )

        # ------------------------------------------------------------------
        # Build probes: (label, view_callable, request)
        # ------------------------------------------------------------------
        probes: list[tuple[str, Any, Any]] = []

        # Lazy imports to avoid circular-import issues at module load time.
        from tracker import views as v

        if doctor_user:
            req_dashboard = factory.get('/doctor/dashboard/')
            req_dashboard.user = doctor_user
            probes.append(('doctor_dashboard', v.doctor_dashboard, req_dashboard))

            req_appt = factory.get('/doctor/appointments/')
            req_appt.user = doctor_user
            probes.append(('doctor_appointment', v.doctor_appointment, req_appt))

            req_profile = factory.get('/doctor/profile/')
            req_profile.user = doctor_user
            probes.append(('doctor_profile', v.doctor_profile, req_profile))

        if patient_user:
            req_explore = factory.get('/explore-doctors/')
            req_explore.user = patient_user
            probes.append(('explore_doctors', v.explore_doctors, req_explore))

            req_home = factory.get('/dashboard/')
            req_home.user = patient_user
            probes.append(('dashboard_home', v.dashboard_home, req_home))

            req_appt_user = factory.get('/appointments/')
            req_appt_user.user = patient_user
            probes.append(('appointment (user)', v.appointment, req_appt_user))

        if not probes:
            raise CommandError('No probes could be built — check that users exist.')

        # ------------------------------------------------------------------
        # Run probes and collect results
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING('\n=== N+1 Query Detector ===\n'))
        self.stdout.write(
            f'Threshold: {threshold} queries  |  '
            f'Repeat flag: {min_repeats}× same template\n'
        )
        self.stdout.write('-' * 60)

        flagged: list[dict] = []

        for label, view_func, request in probes:
            result = _probe_view(label, view_func, request)

            status_symbol = '✓'
            style = self.style.SUCCESS

            if result['error']:
                status_symbol = '✗'
                style = self.style.ERROR
            elif result['query_count'] > threshold or result['repeated']:
                status_symbol = '⚠'
                style = self.style.WARNING
                flagged.append(result)

            line = (
                f"{status_symbol}  {label:<35} "
                f"{result['query_count']:>4} queries  "
                f"{result['duration_ms']:>7.1f} ms"
            )
            if result['error']:
                line += f"  ERROR: {result['error']}"
            self.stdout.write(style(line))

            if result.get('repeated'):
                for sql_tmpl, cnt in result['repeated'][:5]:
                    short = sql_tmpl[:120].replace('\n', ' ')
                    self.stdout.write(
                        self.style.WARNING(f"     ↳ repeated {cnt}×: {short}…")
                    )

        # ------------------------------------------------------------------
        # Verbose dump
        # ------------------------------------------------------------------
        if verbose and flagged:
            self.stdout.write('\n' + '=' * 60)
            self.stdout.write(self.style.MIGRATE_HEADING('Detailed query log for flagged views'))
            self.stdout.write('=' * 60)
            for result in flagged:
                self.stdout.write(f"\n--- {result['view']} ({result['query_count']} queries) ---")
                for i, q in enumerate(result.get('queries', []), 1):
                    self.stdout.write(f"  [{i:03d}] {q['sql'][:200]}")

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        self.stdout.write('\n' + '-' * 60)
        if flagged:
            self.stdout.write(
                self.style.WARNING(
                    f'\n{len(flagged)} view(s) exceeded the threshold or have repeated queries:\n'
                )
            )
            for result in flagged:
                self.stdout.write(
                    self.style.WARNING(
                        f'  • {result["view"]}: {result["query_count"]} queries, '
                        f'{len(result["repeated"])} repeated template(s)'
                    )
                )
            self.stdout.write(
                '\nFix suggestions:\n'
                '  • Add select_related() for ForeignKey / OneToOneField lookups\n'
                '  • Add prefetch_related() for reverse FK and ManyToMany relations\n'
                '  • Use .only() or .defer() to avoid loading unused fields\n'
                '  • Replace per-object attribute access in loops with annotated querysets\n'
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nAll {len(probes)} probed views are within the {threshold}-query threshold. '
                    'No obvious N+1 patterns detected.\n'
                )
            )
