from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Avg
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

class User(AbstractUser):
    ROLE_CHOICES = (
        ('user', 'User'),
        ('doctor', 'Doctor'),
    )
    
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='user')
    is_verified = models.BooleanField(default=False)  # for doctors only

    has_accepted_terms = models.BooleanField(default=False)
    is_two_factor_enabled = models.BooleanField(default=False)
    two_factor_enabled_at = models.DateTimeField(null=True, blank=True)
    is_password_strong = models.BooleanField(default=False)
    
    def __str__(self):
        return self.username

    def set_password(self, raw_password):
        super().set_password(raw_password)

        if not raw_password:
            self.is_password_strong = False
            return

        try:
            validate_password(raw_password, self)
            self.is_password_strong = True
        except ValidationError:
            self.is_password_strong = False

class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='user_profile'
    )

    date_of_birth = models.DateField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    profile_picture = models.ImageField(upload_to='profile_pictures/', null=True, blank=True)
    has_accepted_terms = models.BooleanField(default=False)
    height_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    address = models.CharField(max_length=255, blank=True)
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
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    expected_end_date = models.DateField(null=True, blank=True)
    
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
    actual_start_date = models.DateField(null=True, blank=True)
    predicted_start_date = models.DateField(null=True, blank=True)
    is_confirmed = models.BooleanField(default=False)
    predicted_next_period = models.DateField(null=True, blank=True)
    estimated_ovulation_day = models.DateField(null=True, blank=True)
    fertile_window_start = models.DateField(null=True, blank=True)
    fertile_window_end = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']



class DoctorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='doctor_profile')
    
    # Verification Fields
    full_name = models.CharField(max_length=255, blank=True)
    license_number = models.CharField(max_length=100, unique=True)
    specialization = models.CharField(max_length=100, default="Gynecologist")
    experience_years = models.PositiveIntegerField(null=True, blank=True)
    hospital_name = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=255, blank=True, null=True) 
    certificate = models.FileField(upload_to="doctor_certificates/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Dashboard/Profile Fields
    photo = models.ImageField(upload_to="doctor_photos/", blank=True, null=True)
    bio = models.TextField(blank=True)
    qualifications = models.TextField(blank=True)
    languages_spoken = models.CharField(max_length=255, blank=True)

    is_verified = models.BooleanField(default=False)
    is_profile_complete = models.BooleanField(default=False)

    def check_profile_complete(self):
        return all([
            bool(self.photo and self.photo.name),
            bool(self.bio and self.bio.strip()),
            bool(self.qualifications and self.qualifications.strip()),
            bool(self.languages_spoken and self.languages_spoken.strip())
        ])

    def save(self, *args, **kwargs):
        if self.license_number:
            self.license_number = self.license_number.strip().upper()
        self.is_profile_complete = self.check_profile_complete()
        super().save(*args, **kwargs)


class DoctorReview(models.Model):
    doctor = models.ForeignKey(
        DoctorProfile,
        on_delete=models.CASCADE,
        related_name="reviews"
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("doctor", "patient")  # one review per patient
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.doctor.full_name} - {self.rating}⭐"


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



class Appointment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    doctor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='appointments')
    availability = models.OneToOneField(DoctorAvailability, on_delete=models.CASCADE)
    patient_message = models.TextField(blank=True, help_text="Reason for appointment")
    reject_reason = models.TextField(blank=True, help_text="Why doctor rejected")

    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
        ('expired', 'Expired'),
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # optional fields
    cancel_reason = models.TextField(blank=True)

    def is_expired(self):
        from django.utils import timezone
        return self.status == "pending" and (timezone.now() - self.created_at).total_seconds() >= 21600
    



class EmergencyRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('assigned', 'Assigned'),
        ('completed', 'Completed'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='emergency_requests'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reason = models.TextField(blank=True)
    assigned_doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_emergency_requests',
        limit_choices_to={'role': 'doctor'},
    )
    assigned_slot = models.OneToOneField(
        'DoctorAvailability',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='emergency_assignment',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"EmergencyRequest #{self.id} ({self.status})"


class ChatMessage(models.Model):
    # Using the combination of doctor/patient to keep history persistent
    room_name = models.CharField(max_length=255) 
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField(blank=True)
    file = models.FileField(upload_to='chat_files/', null=True, blank=True)
    is_note = models.BooleanField(default=False) # True if it's a doctor's internal note
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False) # Track if message has been read

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.sender.username}: {self.message[:50]}"


class Conversation(models.Model):
    """
    Represents a conversation between a doctor and patient.
    Automatically created when an appointment is made.
    """
    doctor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='doctor_conversations')
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='patient_conversations')
    room_name = models.CharField(max_length=255, unique=True)
    last_message = models.TextField(blank=True, null=True)
    last_message_time = models.DateTimeField(auto_now_add=True)
    unread_count_doctor = models.IntegerField(default=0)
    unread_count_patient = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_message_time']
        unique_together = ['doctor', 'patient']

    def __str__(self):
        return f"Conversation: Dr. {self.doctor.username} - {self.patient.username}"

    def get_other_user(self, current_user):
        """Get the other participant in the conversation"""
        if current_user == self.doctor:
            return self.patient
        return self.doctor

    def get_unread_count(self, user):
        """Get unread count for a specific user"""
        if user.role == 'doctor':
            return self.unread_count_doctor
        return self.unread_count_patient

    def mark_as_read(self, user):
        """Mark conversation as read for a specific user"""
        if user.role == 'doctor':
            self.unread_count_doctor = 0
        else:
            self.unread_count_patient = 0
        self.save()


class UserDocument(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='documents'
    )
    file = models.FileField(upload_to='user_documents/')
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def save(self, *args, **kwargs):
        if self.file and not self.original_name:
            self.original_name = self.file.name.split('/')[-1]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.original_name or self.file.name}"


class HealthLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='health_logs'
    )
    height_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} health log ({self.created_at:%Y-%m-%d %H:%M})"


class MoodEntry(models.Model):
    MOOD_CHOICES = (
        ('happy', 'Happy'),
        ('sad', 'Sad'),
        ('stressed', 'Stressed'),
        ('calm', 'Calm'),
        ('irritated', 'Irritated'),
        ('energetic', 'Energetic'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='mood_entries'
    )
    mood = models.CharField(max_length=20, choices=MOOD_CHOICES)
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']
        unique_together = ('user', 'date')

    def __str__(self):
        return f"{self.user.username} mood on {self.date:%Y-%m-%d}: {self.mood}"


class PredictionFeedback(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='prediction_feedbacks'
    )
    cycle_log = models.OneToOneField(
        'CycleLog',
        on_delete=models.CASCADE,
        related_name='feedback',
        null=True,
        blank=True,
    )
    predicted_date = models.DateField()
    actual_date = models.DateField(null=True, blank=True)
    is_correct = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} prediction feedback ({self.predicted_date})"


class SymptomLog(models.Model):
    SOURCE_CHOICES = (
        ('manual', 'Manual Add Symptom'),
        ('first_login', 'First Login Period Form'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='symptom_logs'
    )
    cycle_log = models.ForeignKey(
        'CycleLog',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='symptom_logs',
    )
    symptom = models.CharField(max_length=100)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']
        unique_together = ('user', 'symptom', 'date')

    def __str__(self):
        return f"{self.user.username} - {self.symptom} ({self.date:%Y-%m-%d})"


class PeriodCheckIn(models.Model):
    PAIN_LEVEL_CHOICES = (
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    )

    BLOOD_FLOW_CHOICES = (
        ('light', 'Light'),
        ('normal', 'Normal'),
        ('heavy', 'Heavy'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='period_checkins'
    )
    cycle_log = models.ForeignKey(
        'CycleLog',
        on_delete=models.CASCADE,
        related_name='period_checkins'
    )
    pain_level = models.CharField(max_length=20, choices=PAIN_LEVEL_CHOICES)
    blood_flow = models.CharField(max_length=20, choices=BLOOD_FLOW_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('user', 'cycle_log')

    def __str__(self):
        return f"{self.user.username} check-in ({self.cycle_log_id})"


class Notification(models.Model):
    TYPE_CHOICES = (
        ('appointment', 'Appointment'),
        ('appointment_accepted', 'Appointment Accepted'),
        ('appointment_rejected', 'Appointment Rejected'),
        ('message_received', 'Message Received'),
        ('emergency_alert', 'Emergency Alert'),
        ('profile', 'Profile'),
        ('settings_update', 'Settings Update'),
        ('system', 'System'),
        ('cycle', 'Cycle'),
        ('email', 'Email'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    title = models.CharField(max_length=150)
    message = models.TextField()
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='system')
    target_url = models.CharField(max_length=255, blank=True, default='')
    target_section_id = models.CharField(max_length=100, blank=True, default='')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.title}"


class TwoFactorCode(models.Model):
    PURPOSE_CHOICES = (
        ('login', 'Login Verification'),
        ('setup', '2FA Setup Verification'),
        ('settings_enable', 'Enable 2FA'),
        ('settings_disable', 'Disable 2FA'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='two_factor_codes'
    )
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=30, choices=PURPOSE_CHOICES)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.purpose}"