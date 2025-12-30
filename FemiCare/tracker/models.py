from django.contrib.auth.models import AbstractUser
from django.db import models

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


class DoctorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    specialization = models.CharField(max_length=100)
    experience_years = models.IntegerField(default=0)

    license_number = models.CharField(max_length=50)
    certificate = models.FileField(upload_to='certificates/', null=True, blank=True)

    is_verified = models.BooleanField(default=False)
    is_rejected = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Dr. {self.user.username}"
