from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import DoctorProfile
from allauth.account.signals import user_signed_up
from tracker.emails.utils import send_notification_email


@receiver(pre_save, sender=DoctorProfile)
def detect_verification_change(sender, instance, **kwargs):
    if not instance.pk:
        instance._was_verified = False
    else:
        old = DoctorProfile.objects.get(pk=instance.pk)
        instance._was_verified = old.is_verified


@receiver(post_save, sender=DoctorProfile)
def send_verification_email(sender, instance, **kwargs):
    was_verified = getattr(instance, '_was_verified', False)

    if not was_verified and instance.is_verified:
        send_notification_email(
            instance.user,
            'Congratulations. Your professional account has been verified and you can now access doctor features.',
            {
                'notification_title': 'Professional Account Verified',
                'subject': 'Your FemiCare Professional Account is Verified',
                'action_url': '/login/',
                'action_label': 'Sign In',
            },
        )

@receiver(post_save, sender=DoctorProfile)
def update_profile_completion(sender, instance, **kwargs):
    instance.is_profile_complete = instance.check_profile_complete()
    DoctorProfile.objects.filter(pk=instance.pk).update(
        is_profile_complete=instance.is_profile_complete
    )


@receiver(user_signed_up)
def prompt_2fa_after_allauth_signup(request, user, **kwargs):
    if request is None:
        return

    if not user.role:
        user.role = 'user'
        user.save(update_fields=['role'])

    request.session['prompt_2fa_after_signup'] = True
    request.session['post_signup_next'] = 'doctor_details' if user.role == 'doctor' else 'user_profile'