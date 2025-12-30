from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import UserProfile, DoctorProfile
from django.conf import settings

User = get_user_model()
 
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        if instance.role == 'doctor':
            DoctorProfile.objects.create(
                user=instance,
                experience_years=0
            )
        else:
            UserProfile.objects.create(user=instance)
