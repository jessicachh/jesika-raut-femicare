from django.core.management.base import BaseCommand

from tracker.models import User
from tracker.views import check_period_delay, trigger_emergency_alert


class Command(BaseCommand):
    help = 'Run emergency risk and delayed-period checks for all app users.'

    def handle(self, *args, **options):
        users = User.objects.filter(role='user')
        high_alerts = 0
        medium_alerts = 0
        delayed_alerts = 0

        for user in users:
            assessment = trigger_emergency_alert(user)
            if assessment.get('level') == 'high' and assessment.get('triggered'):
                high_alerts += 1
            elif assessment.get('level') == 'medium' and assessment.get('triggered'):
                medium_alerts += 1

            if check_period_delay(user):
                delayed_alerts += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Emergency checks complete. High alerts: {high_alerts}, '
                f'Medium alerts: {medium_alerts}, Delayed period alerts: {delayed_alerts}.'
            )
        )
