import logging
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)

APPOINTMENT_EMAIL_CONFIG = {
    "request_confirmation": {
        "subject": "Appointment Request Received - FemiCare",
        "html": "emails/appointment_request_confirmation.html",
        "text": "emails/appointment_request_confirmation.txt",
    },
    "accepted": {
        "subject": "Appointment Confirmed - FemiCare",
        "html": "emails/appointment_accepted.html",
        "text": "emails/appointment_accepted.txt",
    },
    "rejected": {
        "subject": "Appointment Update - FemiCare",
        "html": "emails/appointment_rejected.html",
        "text": "emails/appointment_rejected.txt",
    },
}

EMERGENCY_EMAIL_CONFIG = {
    "emergency_alert": {
        "subject": "Emergency Health Alert - FemiCare",
        "html": "emails/emergency_alert.html",
        "text": "emails/emergency_alert.txt",
    },
    "doctor_assigned": {
        "subject": "Emergency Doctor Assigned - FemiCare",
        "html": "emails/emergency_doctor_assigned.html",
        "text": "emails/emergency_doctor_assigned.txt",
    },
    "symptom_risk": {
        "subject": "Symptom Risk Alert - FemiCare",
        "html": "emails/symptom_risk_alert.html",
        "text": "emails/symptom_risk_alert.txt",
    },
    "delayed_period": {
        "subject": "Delayed Period Alert - FemiCare",
        "html": "emails/delayed_period_alert.html",
        "text": "emails/delayed_period_alert.txt",
    },
}

VERIFICATION_EMAIL_CONFIG = {
    "email_verification": {
        "subject": "Email Verification Code - FemiCare",
        "html": "emails/email_verification.html",
        "text": "emails/email_verification.txt",
    },
    "two_factor": {
        "subject": "FemiCare Verification Code",
        "html": "emails/email_verification.html",
        "text": "emails/email_verification.txt",
    },
}


def _resolve_display_name(user: Any) -> str:
    if not user:
        return "there"

    first_name = getattr(user, "first_name", "")
    if first_name:
        return first_name

    username = getattr(user, "username", "")
    if username:
        return username

    return "there"


def _build_absolute_url(path_or_url: str) -> str:
    if not path_or_url:
        return ""

    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url

    base_url = getattr(settings, "SITE_BASE_URL", "").rstrip("/")
    if base_url and path_or_url.startswith("/"):
        return f"{base_url}{path_or_url}"
    if base_url:
        return f"{base_url}/{path_or_url}"

    return path_or_url


def _default_context(user: Any) -> Dict[str, Any]:
    return {
        "brand_name": "FemiCare",
        "greeting_name": _resolve_display_name(user),
        "dashboard_url": _build_absolute_url(reverse("dashboard_home")),
        "resources_url": _build_absolute_url(reverse("resources")),
        "support_email": getattr(settings, "DEFAULT_FROM_EMAIL", "support@femicare.local"),
    }


def _send_templated_email(
    *,
    subject: str,
    recipient_email: str,
    html_template: str,
    text_template: str,
    context: Dict[str, Any],
    fail_silently: bool = False,
) -> bool:
    if not recipient_email:
        return False

    html_content = render_to_string(html_template, context)
    text_content = render_to_string(text_template, context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[recipient_email],
    )
    message.attach_alternative(html_content, "text/html")

    try:
        message.send(fail_silently=fail_silently)
        return True
    except Exception:
        logger.exception("Failed sending email template=%s recipient=%s", html_template, recipient_email)
        if fail_silently:
            return False
        raise


def send_appointment_email(user: Any, email_type: str, data: Optional[Dict[str, Any]] = None) -> bool:
    config = APPOINTMENT_EMAIL_CONFIG.get(email_type)
    if not config or not user or not getattr(user, "email", ""):
        return False

    payload = _default_context(user)
    payload.update(data or {})

    return _send_templated_email(
        subject=payload.get("subject", config["subject"]),
        recipient_email=user.email,
        html_template=config["html"],
        text_template=config["text"],
        context=payload,
        fail_silently=True,
    )


def send_emergency_email(user: Any, data: Optional[Dict[str, Any]] = None) -> bool:
    payload = data or {}
    email_type = payload.get("type", "emergency_alert")
    config = EMERGENCY_EMAIL_CONFIG.get(email_type)
    if not config or not user:
        return False

    recipient_email = payload.get("recipient_email") or getattr(user, "email", "")
    if not recipient_email:
        return False

    context = _default_context(user)
    context.update(payload)

    return _send_templated_email(
        subject=context.get("subject", config["subject"]),
        recipient_email=recipient_email,
        html_template=config["html"],
        text_template=config["text"],
        context=context,
        fail_silently=True,
    )


def send_notification_email(user: Any, message: str, data: Optional[Dict[str, Any]] = None) -> bool:
    if not user or not getattr(user, "email", ""):
        return False

    payload = _default_context(user)
    payload.update(data or {})
    payload.setdefault("notification_title", "FemiCare Notification")
    payload["notification_message"] = message

    return _send_templated_email(
        subject=payload.get("subject", payload["notification_title"]),
        recipient_email=user.email,
        html_template="emails/general_notification_alert.html",
        text_template="emails/general_notification_alert.txt",
        context=payload,
        fail_silently=True,
    )


def send_verification_email(user: Any, verification_type: str, data: Optional[Dict[str, Any]] = None) -> bool:
    config = VERIFICATION_EMAIL_CONFIG.get(verification_type)
    if not config:
        return False

    payload = data or {}
    recipient_email = payload.get("recipient_email") or getattr(user, "email", "")
    if not recipient_email:
        return False

    context = _default_context(user)
    context.update(payload)

    return _send_templated_email(
        subject=context.get("subject", config["subject"]),
        recipient_email=recipient_email,
        html_template=config["html"],
        text_template=config["text"],
        context=context,
        fail_silently=False,
    )


def send_profile_settings_change_email(user: Any, data: Optional[Dict[str, Any]] = None) -> bool:
    if not user or not getattr(user, "email", ""):
        return False

    payload = _default_context(user)
    payload.update(data or {})

    return _send_templated_email(
        subject=payload.get("subject", "Profile and Settings Updated - FemiCare"),
        recipient_email=user.email,
        html_template="emails/profile_settings_change_confirmation.html",
        text_template="emails/profile_settings_change_confirmation.txt",
        context=payload,
        fail_silently=True,
    )
