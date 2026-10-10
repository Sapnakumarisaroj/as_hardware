import re

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils.deconstruct import deconstructible

# Indian mobile numbers, optionally prefixed with +91 / 91 / 0.
phone_validator = RegexValidator(
    regex=r"^(?:\+?91|0)?[6-9]\d{9}$",
    message="Enter a valid 10-digit Indian mobile number.",
)

postal_code_validator = RegexValidator(regex=r"^[1-9]\d{5}$", message="Enter a valid 6-digit PIN code.")


_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_GSTIN_SHAPE = r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"


def gstin_checksum(first14: str) -> str:
    """The 15th GSTIN character: the GSTN mod-36 check over the first 14."""
    total = 0
    for position, char in enumerate(first14):
        product = _GSTIN_CHARS.index(char) * (2 if position % 2 else 1)
        total += product // 36 + product % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36]


def gstin_validator(value: str) -> None:
    """A GSTIN in the official shape (state code, PAN, entity number, 'Z', check character).
    Only the format and check character are verified; registration is not looked up online."""
    value = (value or "").strip().upper()
    if not re.match(_GSTIN_SHAPE, value):
        raise ValidationError("Enter a valid 15-character GSTIN, e.g. 29ABCDE1234F1ZW.")
    if not 1 <= int(value[:2]) <= 38 and value[:2] not in {"97", "99"}:
        raise ValidationError("The GSTIN state code isn't valid.")
    if gstin_checksum(value[:14]) != value[14]:
        raise ValidationError("This GSTIN's check character doesn't match. Please check it for typos.")


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
