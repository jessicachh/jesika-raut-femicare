from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings
from .models import DoctorProfile
from django.core.mail import EmailMultiAlternatives # Use this for HTML
from django.utils.html import strip_tags
from django.template.loader import render_to_string


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
        subject = "Your FemiCare Professional Account is Verified! 🎉"
        
        # Context data to pass to the HTML template
        context = {
            'doctor_name': instance.user.username,
            'login_url': "http://127.0.0.1:8000/login/", # Change to your actual URL in production
        }
        
        # Render HTML and create plain text version
        html_content = render_to_string('doctor_verified.html', context)
        text_content = strip_tags(html_content) 

        # Create the email object
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[instance.user.email],
        )
        email.attach_alternative(html_content, "text/html")
        
        try:
            email.send(fail_silently=False)
        except Exception as e:
            print(f"Error sending email: {e}")

@receiver(post_save, sender=DoctorProfile)
def update_profile_completion(sender, instance, **kwargs):
    instance.is_profile_complete = instance.check_profile_complete()
    DoctorProfile.objects.filter(pk=instance.pk).update(
        is_profile_complete=instance.is_profile_complete
    )