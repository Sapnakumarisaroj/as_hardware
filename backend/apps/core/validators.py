from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils.deconstruct import deconstructible

# Indian mobile numbers, optionally prefixed with +91 / 91 / 0.
phone_validator = RegexValidator(
    regex=r"^(?:\+?91|0)?[6-9]\d{9}$",
    message="Enter a valid 10-digit Indian mobile number.",
)

postal_code_validator = RegexValidator(regex=r"^[1-9]\d{5}$", message="Enter a valid 6-digit PIN code.")


def normalize_phone(value: str) -> str:
    """Return the bare 10-digit number (storage format)."""
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


@deconstructible
class MaxFileSizeValidator:
    def __init__(self, max_mb: int):
        self.max_mb = max_mb

    def __call__(self, file):
        if file and file.size > self.max_mb * 1024 * 1024:
            raise ValidationError(f"File too large. Maximum size is {self.max_mb} MB.")

    def __eq__(self, other):
        return isinstance(other, MaxFileSizeValidator) and other.max_mb == self.max_mb
