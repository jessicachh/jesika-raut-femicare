from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

class User(AbstractUser):
    ROLE_CHOICES = (
        ('user', 'User'),
        ('doctor', 'Doctor'),
    )

    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    is_verified = models.BooleanField(default=False)  # for doctors only

    def __str__(self):
        return self.username

class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='user_profile'
    )

    date_of_birth = models.DateField(null=True, blank=True)
    cycle_length = models.IntegerField(null=True, blank=True)  # ✅ FIX
    last_period_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username


class CycleLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    log_date = models.DateField(auto_now_add=True)
    last_period_start = models.DateField(
    null=True,
    blank=True,
    help_text="First day of last period"
    )
    
    # Cycle basics (USER INPUT)
    length_of_cycle = models.IntegerField(
        help_text="Average number of days between periods"
    )
    length_of_menses = models.IntegerField(
        help_text="How many days bleeding lasts"
    )

    mean_menses_length = models.IntegerField()

    mean_bleeding_intensity = models.IntegerField(
        choices=[
            (1, 'Light'),
            (2, 'Moderate'),
            (3, 'Heavy'),
        ]
    )

    unusual_bleeding = models.BooleanField(default=False)

    total_menses_score = models.IntegerField(
        choices=[
            (0, 'None'),
            (3, 'As Regular'),
            (6, 'Moderate'),
            (9, 'Severe'),
        ]
    )

    # Body metrics
    height_cm = models.FloatField()
    weight_kg = models.FloatField()
    bmi = models.FloatField(null=True, blank=True)

    # 🔮 PREDICTIONS (SYSTEM GENERATED)
    predicted_next_period = models.DateField(null=True, blank=True)
    estimated_ovulation_day = models.DateField(null=True, blank=True)
    fertile_window_start = models.DateField(null=True, blank=True)
    fertile_window_end = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']



class DoctorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # already existing verified fields
    full_name = models.CharField(max_length=255, blank=True)
    license_number = models.CharField(max_length=100)
    specialization = models.CharField(max_length=100)
    experience_years = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    hospital_name = models.CharField(max_length=255, blank=True)
    certificate = models.FileField(upload_to="doctor_certificates/",null=True,blank=True)
    # NEW
    photo = models.ImageField(
        upload_to="doctor_photos/",
        blank=True,
        null=True
    )

    bio = models.TextField(blank=True)

    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return self.user.get_full_name()



# Appointment Model
class DoctorAvailability(models.Model):
    DAYS_OF_WEEK = (
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    )
    doctor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'doctor'},
        related_name="availabilities"
    )
    date = models.DateField(default=timezone.now)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        """Check if availability is in the past"""
        end_datetime = timezone.make_aware(
            timezone.datetime.combine(self.date, self.end_time)
        )
        return end_datetime < timezone.now()

    def __str__(self):
        return f"{self.doctor.username} | {self.date} {self.start_time}-{self.end_time}"