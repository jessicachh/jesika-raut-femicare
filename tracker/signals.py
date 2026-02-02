from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings
from .models import DoctorProfile


@receiver(pre_save, sender=DoctorProfile)
def detect_verification_change(sender, instance, **kwargs):
    if not instance.pk:
        instance._was_verified = False
    else:
        old = DoctorProfile.objects.get(pk=instance.pk)
        instance._was_verified = old.is_verified


@receiver(post_save, sender=DoctorProfile)
def send_verification_email(sender, instance, **kwargs):
    if not instance._was_verified and instance.is_verified:
        send_mail(
            subject="Your Doctor Account is Verified 🎉",
            message="Congratulations! Your account has been verified. You can now log in.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[instance.user.email],
            fail_silently=False,
        )

@receiver(post_save, sender=DoctorProfile)
def update_profile_completion(sender, instance, **kwargs):
    instance.is_profile_complete = instance.check_profile_complete()
    DoctorProfile.objects.filter(pk=instance.pk).update(
        is_profile_complete=instance.is_profile_complete
    )