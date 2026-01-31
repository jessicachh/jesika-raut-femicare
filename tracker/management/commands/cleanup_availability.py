from django.core.management.base import BaseCommand
from django.utils import timezone
from tracker.models import DoctorAvailability

class Command(BaseCommand):
    help = "Remove expired doctor availability"

    def handle(self, *args, **kwargs):
        now = timezone.now()
        expired = DoctorAvailability.objects.filter(
            date__lt=now.date()
        ) | DoctorAvailability.objects.filter(
            date=now.date(),
            end_time__lt=now.time()
        )

        count = expired.count()
        expired.delete()

        self.stdout.write(f"Deleted {count} expired availability slots")