"""Customer sign-in with a mobile number and a one-time code (OTP) sent by SMS.

    request_login_code(phone)                → sends a code (or explains why it can't)
    verify_login_code(phone, code, …)        → the customer, signed up on first use

Rules:
- Indian mobile numbers only (+91, 10 digits starting 6-9); stored as 10 digits like `User.phone`.
- A 6-digit code from `secrets`, stored as HMAC-SHA256(SECRET_KEY, phone:code); valid OTP_TTL_SECONDS,
  OTP_MAX_ATTEMPTS wrong guesses, then it is dead. A correct code is used once (row lock + consumed_at).
- A new code supersedes the previous one. Resend only after OTP_RESEND_SECONDS; at most
  OTP_MAX_SENDS_PER_HOUR codes per number per hour (the API is also throttled per IP).
- Off unless OTP_LOGIN_ENABLED (it is off until a real SMS gateway is set up): both endpoints then refuse
  before a code is made or a provider is called, and customers sign in with mobile number + password.
- Nothing is "sent" without a configured SMS provider. The mock provider is accepted only when
  OTP_MOCK_ALLOWED (development and tests); in production a mock never pretends to send. The code is
  never returned by the API; in DEBUG with the mock provider it is printed to the server console.
- Only customer accounts sign in this way. Staff, managers and riders keep email + password.
- A new number creates a customer account (name required; email optional). An existing customer whose
  phone was not verified yet gets it verified by this sign-in.
"""

import hashlib
import hmac
import logging
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import update_last_login
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, ServiceError
from integrations.messaging import MessagingError, OutgoingMessage, get_sms_provider

from .models import PhoneOTP, User

logger = logging.getLogger(__name__)
PHONE_RE = re.compile(r"^[6-9]\d{9}$")


class OtpError(ServiceError):
    default_code = "otp_error"


class InvalidPhone(OtpError):
    status_code = 400
    default_code = "invalid_phone"
    default_detail = "Enter a valid 10-digit Indian mobile number."


class SmsUnavailable(OtpError):
    status_code = 503
    default_code = "sms_unavailable"
    default_detail = "Sign-in by SMS code isn't available right now. Please sign in with your email instead."


class OtpLoginDisabled(OtpError):
    status_code = 503
    default_code = "otp_login_disabled"
    default_detail = "Sign-in by SMS code isn't available yet. Please sign in with your mobile number and password."


class OtpCooldown(OtpError):
    status_code = 429
    default_code = "otp_cooldown"


class TooManyCodes(OtpError):
    status_code = 429
    default_code = "too_many_otp_requests"


class OtpInvalid(OtpError):
    status_code = 400
    default_code = "otp_invalid"


class OtpExpired(OtpError):
    status_code = 400
    default_code = "otp_expired"
    default_detail = "This code has expired or was replaced. Request a new code."


class OtpAttemptsExceeded(OtpError):
    status_code = 429
    default_code = "otp_too_many_attempts"
    default_detail = "Too many wrong codes. Request a new code."


class NameRequired(OtpError):
    status_code = 400
    default_code = "name_required"
    default_detail = "Welcome! Tell us your name to create your account."


class StaffUseEmail(OtpError):
    status_code = 403
    default_code = "use_email_login"
    default_detail = "This number belongs to a staff account. Please sign in with your email and password."


class AccountInactive(OtpError):
    status_code = 403
    default_code = "account_inactive"
    default_detail = "This account is deactivated. Please contact the shop."


def normalize_mobile(value: str, country_code: str = "+91") -> str:
    if (country_code or "+91").replace(" ", "") not in ("+91", "91"):
        raise InvalidPhone("Only Indian mobile numbers (+91) are supported.")
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not PHONE_RE.match(digits):
        raise InvalidPhone()
    return digits


def _hash(phone: str, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"login:{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def _require_enabled() -> None:
    if not settings.OTP_LOGIN_ENABLED:
        raise OtpLoginDisabled()


def _provider():
    provider = get_sms_provider()
    if not provider.configured or (getattr(provider, "is_mock", False) and not settings.OTP_MOCK_ALLOWED):
        raise SmsUnavailable()
    return provider


def request_login_code(phone: str, *, country_code: str = "+91", request=None) -> dict:
    _require_enabled()
    phone = normalize_mobile(phone, country_code)
    provider = _provider()
    now = timezone.now()
    with transaction.atomic():
        # Serialize requests for this number so two clicks can't both pass the cooldown.
        hour_ago = now - timedelta(hours=1)
        recent = list(PhoneOTP.objects.select_for_update().filter(phone=phone, created_at__gte=hour_ago))
        if recent:
            wait = settings.OTP_RESEND_SECONDS - int((now - recent[0].created_at).total_seconds())
            if wait > 0:
                message = f"Please wait {wait} seconds before asking for a new code."
                raise OtpCooldown(message, details={"retry_after": wait})
        if len(recent) >= settings.OTP_MAX_SENDS_PER_HOUR:
            oldest = min(r.created_at for r in recent)
            wait = max(60, int((oldest + timedelta(hours=1) - now).total_seconds()))
            raise TooManyCodes(
                "Too many codes requested for this number. Please try again later or sign in with your email.",
                details={"retry_after": wait},
            )
        PhoneOTP.objects.filter(phone=phone, consumed_at__isnull=True).update(consumed_at=now)  # supersede
        code = f"{secrets.randbelow(10**settings.OTP_LENGTH):0{settings.OTP_LENGTH}d}"
        otp = PhoneOTP.objects.create(
            phone=phone,
            code_hash=_hash(phone, code),
            expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
            ip_address=_ip(request),
        )
    minutes = max(1, settings.OTP_TTL_SECONDS // 60)
    text = (
        f"{code} is your {settings.APP_NAME} sign-in code. It expires in {minutes} minutes. "
        "Never share this code with anyone."
    )
    try:
        provider.send(OutgoingMessage(to=f"91{phone}", text=text, reference=f"otp-{otp.pk}"))
    except MessagingError as exc:
        PhoneOTP.objects.filter(pk=otp.pk).update(consumed_at=timezone.now())  # never usable if not delivered
        logger.warning("OTP SMS to ******%s failed: %s", phone[-4:], exc)
        raise SmsUnavailable("We couldn't send the code to this number. Please check it or try again later.") from exc
    if getattr(provider, "is_mock", False) and settings.DEBUG:
        # Development only: there is no real SMS, so show the code in the server console. Never in production.
        logger.warning("DEVELOPMENT ONLY - mock SMS sign-in code for ******%s: %s", phone[-4:], code)
    record_audit(action="auth.otp_sent", request=request, changes={"phone_last4": phone[-4:]})
    return {
        "phone": phone,
        "expires_in": settings.OTP_TTL_SECONDS,
        "resend_in": settings.OTP_RESEND_SECONDS,
        "length": settings.OTP_LENGTH,
        "sms_sent": not getattr(provider, "is_mock", False),  # a mock "sends" nothing: the page must not say so
    }


def verify_login_code(
    phone: str, code: str, *, country_code: str = "+91", full_name: str = "", email: str = "", request=None
) -> tuple[User, bool]:
    """(user, created). Raises for a wrong, expired, reused or exhausted code."""
    _require_enabled()
    phone = normalize_mobile(phone, country_code)
    code = re.sub(r"\D", "", code or "")
    now = timezone.now()
    with transaction.atomic():
        otp = (
            PhoneOTP.objects.select_for_update()
            .filter(phone=phone, consumed_at__isnull=True, expires_at__gt=now)
            .order_by("-created_at")
            .first()
        )
        if otp is None:
            raise OtpExpired()
        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            raise OtpAttemptsExceeded()
        if not hmac.compare_digest(otp.code_hash, _hash(phone, code)):
            otp.attempts += 1
            otp.save(update_fields=["attempts"])
            wrong = otp.attempts  # raised after this transaction commits, so the attempt is counted
        else:
            wrong = 0
    if wrong:
        left = settings.OTP_MAX_ATTEMPTS - wrong
        if left <= 0:
            raise OtpAttemptsExceeded()
        raise OtpInvalid(
            f"That code isn't right. {left} attempt{'s' if left != 1 else ''} left.", details={"attempts_left": left}
        )

    with transaction.atomic():
        # Re-lock the code: it must still be unused (a concurrent request may have used it meanwhile).
        otp = PhoneOTP.objects.select_for_update().filter(pk=otp.pk, consumed_at__isnull=True).first()
        if otp is None:
            raise OtpExpired()
        user = User.objects.select_for_update().filter(phone=phone).first()
        created = False
        if user is None:
            if not full_name.strip():
                raise NameRequired()  # the code stays valid: the customer resubmits it with their name
            email = (email or "").strip().lower() or None
            if email and User.objects.filter(email=email).exists():
                raise ConflictError(
                    "An account with this email already exists. Sign in with your email, or leave email blank.",
                    code="email_taken",
                )
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        email=email, full_name=full_name.strip()[:150], phone=phone, phone_verified=True,
                        role=User.Role.CUSTOMER,
                    )  # fmt: skip  (no password: create_user stores an unusable one)
            except IntegrityError as exc:
                raise ConflictError("An account with this number already exists.", code="account_exists") from exc
            created = True
        elif user.role != User.Role.CUSTOMER or user.is_staff or user.is_superuser:
            raise StaffUseEmail()
        elif not user.is_active:
            raise AccountInactive()
        elif not user.phone_verified:
            user.phone_verified = True
            user.save(update_fields=["phone_verified", "updated_at"])

        otp.consumed_at = now
        otp.save(update_fields=["consumed_at"])
    update_last_login(None, user)
    record_audit(action="auth.register_otp" if created else "auth.login_otp", actor=user, target=user, request=request)
    return user, created


def _ip(request) -> str | None:
    if request is None:
        return None
    from apps.core.audit import _client_ip

    return _client_ip(request)
