"""
Management command to test SMTP email delivery.

Usage:
    python manage.py test_email --to user@example.com
    python manage.py test_email --to user@example.com --subject "Custom subject"

This command sends a plain-text probe email and prints a full diagnostic
summary of the SMTP settings being used, making it easy to confirm whether
the EMAIL_HOST / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD environment variables
are configured correctly in production.
"""

import logging
import smtplib
import socket

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send a test email to verify SMTP configuration and connectivity."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            required=True,
            metavar="EMAIL",
            help="Recipient email address for the test message.",
        )
        parser.add_argument(
            "--subject",
            default="FemiCare SMTP Test",
            metavar="SUBJECT",
            help="Email subject line (default: 'FemiCare SMTP Test').",
        )

    def handle(self, *args, **options):
        recipient = options["to"].strip()
        subject = options["subject"].strip()

        # ── Diagnostic summary ────────────────────────────────────────────────
        email_backend = getattr(settings, "EMAIL_BACKEND", "<not set>")
        email_host = getattr(settings, "EMAIL_HOST", "<not set>")
        email_port = getattr(settings, "EMAIL_PORT", "<not set>")
        email_use_tls = getattr(settings, "EMAIL_USE_TLS", "<not set>")
        email_host_user = getattr(settings, "EMAIL_HOST_USER", "") or "<not set>"
        email_host_password = getattr(settings, "EMAIL_HOST_PASSWORD", "")
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "<not set>")

        self.stdout.write(self.style.MIGRATE_HEADING("\n── SMTP Configuration ──────────────────────────────"))
        self.stdout.write(f"  EMAIL_BACKEND    : {email_backend}")
        self.stdout.write(f"  EMAIL_HOST       : {email_host}")
        self.stdout.write(f"  EMAIL_PORT       : {email_port}")
        self.stdout.write(f"  EMAIL_USE_TLS    : {email_use_tls}")
        self.stdout.write(f"  EMAIL_HOST_USER  : {email_host_user}")
        self.stdout.write(
            f"  EMAIL_HOST_PASSWORD: {'<set>' if email_host_password else '<NOT SET — authentication will fail>'}"
        )
        self.stdout.write(f"  DEFAULT_FROM_EMAIL: {from_email}")
        self.stdout.write(f"  Recipient        : {recipient}")
        self.stdout.write(self.style.MIGRATE_HEADING("────────────────────────────────────────────────────\n"))

        # ── Warn about obviously wrong config ─────────────────────────────────
        if not email_host_password:
            self.stdout.write(
                self.style.WARNING(
                    "WARNING: EMAIL_HOST_PASSWORD is empty. "
                    "Gmail SMTP requires an App Password — plain account passwords are rejected."
                )
            )
        if email_host_user == "<not set>":
            self.stdout.write(
                self.style.WARNING(
                    "WARNING: EMAIL_HOST_USER is not set. "
                    "Most SMTP servers require a username for authentication."
                )
            )

        # ── TCP connectivity probe ────────────────────────────────────────────
        if isinstance(email_host, str) and isinstance(email_port, int):
            self.stdout.write(f"Checking TCP connectivity to {email_host}:{email_port} …")
            try:
                sock = socket.create_connection((email_host, email_port), timeout=10)
                sock.close()
                self.stdout.write(self.style.SUCCESS(f"  TCP connection to {email_host}:{email_port} succeeded."))
            except OSError as exc:
                self.stdout.write(
                    self.style.ERROR(
                        f"  TCP connection to {email_host}:{email_port} FAILED: {exc}\n"
                        "  Check that IPv6 egress is enabled and the host/port are correct."
                    )
                )

        # ── Send the test email ───────────────────────────────────────────────
        body = (
            "This is an automated test message from the FemiCare SMTP diagnostic tool.\n\n"
            "If you received this email, your SMTP configuration is working correctly.\n\n"
            f"Settings used:\n"
            f"  EMAIL_HOST      : {email_host}\n"
            f"  EMAIL_PORT      : {email_port}\n"
            f"  EMAIL_USE_TLS   : {email_use_tls}\n"
            f"  EMAIL_HOST_USER : {email_host_user}\n"
            f"  DEFAULT_FROM_EMAIL: {from_email}\n"
        )

        self.stdout.write(f"\nSending test email to {recipient} …")
        logger.info("test_email command: sending test email to %s via %s:%s", recipient, email_host, email_port)

        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=from_email if from_email != "<not set>" else None,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except smtplib.SMTPAuthenticationError as exc:
            raise CommandError(
                f"SMTP authentication failed: {exc}\n"
                "For Gmail, make sure you are using an App Password (not your account password) "
                "and that 2-Step Verification is enabled on the sending account."
            ) from exc
        except smtplib.SMTPException as exc:
            raise CommandError(f"SMTP error while sending test email: {exc}") from exc
        except Exception as exc:
            raise CommandError(f"Unexpected error while sending test email: {exc}") from exc

        logger.info("test_email command: test email delivered successfully to %s", recipient)
        self.stdout.write(
            self.style.SUCCESS(
                f"\nTest email sent successfully to {recipient}.\n"
                "If it doesn't arrive within a few minutes, check the recipient's spam folder."
            )
        )
