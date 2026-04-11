import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class StrongPasswordValidator:
    """Enforce mixed-case, number, special char, and bounded length."""

    def __init__(self, min_length=8, max_length=12):
        self.min_length = int(min_length)
        self.max_length = int(max_length)

    def validate(self, password, user=None):
        if password is None:
            raise ValidationError(
                _("Password is required."),
                code="password_required",
            )

        length = len(password)
        if length < self.min_length or length > self.max_length:
            raise ValidationError(
                _("Password must be between %(min)s and %(max)s characters."),
                code="password_length",
                params={"min": self.min_length, "max": self.max_length},
            )

        missing_requirements = []
        if not re.search(r"[A-Z]", password):
            missing_requirements.append("uppercase letter")
        if not re.search(r"[a-z]", password):
            missing_requirements.append("lowercase letter")
        if not re.search(r"\d", password):
            missing_requirements.append("number")
        if not re.search(r"[^\w\s]", password):
            missing_requirements.append("special character")

        if missing_requirements:
            raise ValidationError(
                _(
                    "Password must include uppercase, lowercase, number, and special character. Missing: %(missing)s."
                ),
                code="password_complexity",
                params={"missing": ", ".join(missing_requirements)},
            )

    def get_help_text(self):
        return _(
            "Password must be 8-12 characters and include uppercase, lowercase, number, and special character."
        )
