"""Delivery OTP: the code the customer tells the rider at the door (Phase 10).

- Six digits, issued when the rider starts the delivery.
- The code is never stored. It is derived from a random per-issue nonce with the server secret
  (HMAC-SHA256), so the customer's order page can show it again, while a copy of the database
  alone reveals nothing. `otp_hash` is a keyed hash of the code, used to check what the rider types.
- Expires after DELIVERY_OTP_TTL_MINUTES; locked after DELIVERY_OTP_MAX_ATTEMPTS wrong tries.
  Either way the customer asks for a new code, which replaces the old one.
- Single use: a correct code completes the delivery in the same transaction, after which the
  assignment is no longer active and no code is accepted for it.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.core.exceptions import ConflictError, ServiceError

from .models import DeliveryAssignment

DIGITS = 6


class OtpError(ServiceError):
    default_code = "otp_invalid"


def _key() -> bytes:
    return hashlib.sha256(f"{settings.SECRET_KEY}:delivery-otp".encode()).digest()


def _derive(assignment_id: int, nonce: str) -> str:
    digest = hmac.new(_key(), f"code:{assignment_id}:{nonce}".encode(), hashlib.sha256).digest()
    return str(int.from_bytes(digest[:8], "big") % 10**DIGITS).zfill(DIGITS)


def _hash(assignment_id: int, nonce: str, code: str) -> str:
    return hmac.new(_key(), f"hash:{assignment_id}:{nonce}:{code}".encode(), hashlib.sha256).hexdigest()


def issue(assignment: DeliveryAssignment, *, now=None) -> None:
    """New code for this assignment; any earlier code stops working. Caller saves/locks."""
    now = now or timezone.now()
    assignment.otp_nonce = secrets.token_hex(16)
    assignment.otp_hash = _hash(assignment.pk, assignment.otp_nonce, _derive(assignment.pk, assignment.otp_nonce))
    assignment.otp_issued_at = now
    assignment.otp_expires_at = now + timedelta(minutes=settings.DELIVERY_OTP_TTL_MINUTES)
    assignment.otp_attempts = 0
    assignment.otp_verified_at = None
    assignment.save(
        update_fields=[
            "otp_nonce",
            "otp_hash",
            "otp_issued_at",
            "otp_expires_at",
            "otp_attempts",
            "otp_verified_at",
            "updated_at",
        ]
    )


def state(assignment: DeliveryAssignment, *, now=None) -> str:
    """none | active | expired | locked | used"""
    now = now or timezone.now()
    if assignment.otp_verified_at:
        return "used"
    if not assignment.otp_nonce or assignment.status != DeliveryAssignment.Status.OUT_FOR_DELIVERY:
        return "none"
    if assignment.otp_attempts >= settings.DELIVERY_OTP_MAX_ATTEMPTS:
        return "locked"
    if assignment.otp_expires_at is None or now >= assignment.otp_expires_at:
        return "expired"
    return "active"


def code_for_customer(assignment: DeliveryAssignment, *, now=None) -> str | None:
    """The code to show on the customer's order page, only while it can be used."""
    if state(assignment, now=now) != "active":
        return None
    return _derive(assignment.pk, assignment.otp_nonce)


def can_reissue(assignment: DeliveryAssignment, *, now=None) -> bool:
    now = now or timezone.now()
    if assignment.status != DeliveryAssignment.Status.OUT_FOR_DELIVERY:
        return False
    wait = timedelta(seconds=settings.DELIVERY_OTP_RESEND_SECONDS)
    return assignment.otp_issued_at is None or now - assignment.otp_issued_at >= wait


def reissue(assignment: DeliveryAssignment, *, now=None) -> None:
    """The customer asks for a new code (expired, locked or lost). `assignment` is locked."""
    now = now or timezone.now()
    if assignment.status != DeliveryAssignment.Status.OUT_FOR_DELIVERY:
        raise ConflictError(
            "A delivery code is only needed while the order is out for delivery.", code="otp_not_needed"
        )
    if not can_reissue(assignment, now=now):
        raise ConflictError(
            f"Please wait {settings.DELIVERY_OTP_RESEND_SECONDS} seconds before asking for another code.",
            code="otp_too_soon",
        )
    issue(assignment, now=now)


def check(assignment: DeliveryAssignment, code: str, *, now=None) -> tuple[bool, str, str]:
    """(ok, error code, message). A wrong code is counted here and must be saved by the caller
    even though the delivery is refused (see workflow.complete_delivery)."""
    now = now or timezone.now()
    current = state(assignment, now=now)
    if current == "used":
        return False, "otp_used", "This delivery code was already used."
    if current == "none":
        return False, "otp_not_issued", "No delivery code has been issued for this delivery."
    if current == "locked":
        return False, "otp_locked", "Too many wrong codes. Ask the customer to get a new code on their order page."
    if current == "expired":
        return False, "otp_expired", "This code has expired. Ask the customer to get a new code on their order page."
    submitted = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(submitted) == DIGITS and hmac.compare_digest(
        _hash(assignment.pk, assignment.otp_nonce, submitted), assignment.otp_hash
    ):
        return True, "", ""
    assignment.otp_attempts += 1
    left = settings.DELIVERY_OTP_MAX_ATTEMPTS - assignment.otp_attempts
    if left <= 0:
        return False, "otp_locked", "Too many wrong codes. Ask the customer to get a new code on their order page."
    return False, "otp_invalid", f"That code is not correct. {left} {'try' if left == 1 else 'tries'} left."
