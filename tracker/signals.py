# from django.db.models.signals import post_save
# from django.dispatch import receiver
# from django.core.mail import send_mail
# from django.conf import settings
# from django.urls import reverse
# from django.contrib.sites.models import Site
# from .models import DoctorProfile

# @receiver(post_save, sender=DoctorProfile)
# def doctor_verification_email(sender, instance, created, **kwargs):
#     # Only send email when verified AND not rejected
#     if instance.is_verified and not instance.is_rejected:

#         # Prevent duplicate emails
#         if hasattr(instance, '_email_sent'):
#             return

#         current_site = Site.objects.get_current()
#         login_url = f"http://{current_site.domain}{reverse('login')}"

#         send_mail(
#             subject="Your Doctor Account Has Been Approved – FemiCare",
#             message=(
#                 f"Hello Dr. {instance.user.username},\n\n"
#                 "We are pleased to inform you that your doctor account on FemiCare "
#                 "has been successfully verified by our administration team.\n\n"
#                 f"You can now log in using the link below:\n{login_url}\n\n"
#                 "If you experience any issues, please contact our support team.\n\n"
#                 "Warm regards,\n"
#                 "FemiCare Team"
#             ),
#             from_email=settings.DEFAULT_FROM_EMAIL,
#             recipient_list=[instance.user.email],
#             fail_silently=False,
#         )

#         # Mark email as sent (runtime only)
#         instance._email_sent = True


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
