"""Authentication and account-lifecycle workflows.

Security notes
- Passwords and tokens are never logged or written to the audit log. Failed logins record
  only a truncated SHA-256 of the attempted email (people sometimes type passwords into it).
- Login errors are generic ("Invalid email or password.") so they don't reveal whether an
  email is registered. "Account deactivated" is only revealed after a *correct* password.
- Password reset responses are identical whether or not the email exists.
- Changing/resetting a password or deactivating revokes every session: all outstanding
  refresh tokens are blacklisted and older access tokens fail `password_changed_at` checks.
"""

import hashlib
import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, password_validation
from django.contrib.auth.models import update_last_login
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import exceptions, status
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, ServiceError

from . import security
from .models import Address

logger = logging.getLogger(__name__)
User = get_user_model()


class InvalidCredentials(ServiceError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = "invalid_credentials"
    default_detail = "Invalid email or password."


class AccountInactive(ServiceError):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "account_inactive"
    default_detail = "This account has been deactivated. Please contact support."


class TooManyAttempts(ServiceError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "too_many_attempts"
    default_detail = "Too many failed login attempts. Please wait a few minutes or reset your password."


def _email_fingerprint(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


def validate_new_password(password: str, user=None, field: str = "password") -> None:
    try:
        password_validation.validate_password(password, user)
    except DjangoValidationError as exc:
        raise exceptions.ValidationError({field: list(exc.messages)}) from exc


# --- Tokens ---------------------------------------------------------------------


def issue_tokens(user) -> dict:
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def revoke_all_sessions(user) -> int:
    """Blacklist every outstanding refresh token of the user."""
    revoked = 0
    for token in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        revoked += int(created)
    return revoked


def logout(refresh_token: str, *, request=None) -> None:
    """Blacklist the given refresh token. Idempotent; an invalid token is not an error."""
    try:
        token = RefreshToken(refresh_token)
        user_id = token.get("user_id")
        token.blacklist()
    except TokenError:
        return
    user = User.objects.filter(pk=user_id).first()
    if user:
        record_audit(action="auth.logout", actor=user, target=user, request=request)


# --- Registration & login -------------------------------------------------------------


@transaction.atomic
def register_customer(*, email: str, password: str, full_name: str, phone: str, request=None):
    user = User(email=email, full_name=full_name.strip(), phone=phone, role=User.Role.CUSTOMER)
    validate_new_password(password, user)
    user.set_password(password)
    try:
        with transaction.atomic():
            user.save()
    except IntegrityError as exc:  # race with a concurrent registration
        raise ConflictError("An account with this email or phone already exists.", code="account_exists") from exc
    record_audit(action="auth.register", actor=user, target=user, request=request)
    return user


def login(*, email: str, password: str, request=None):
    email = (email or "").strip().lower()
    if security.is_locked_out(email):
        record_audit(action="auth.login_locked", request=request, changes={"email_sha256": _email_fingerprint(email)})
        raise TooManyAttempts()

    user = authenticate(request, email=email, password=password)
    if user is None:
        candidate = User.objects.filter(email=email).first()
        if candidate is not None and not candidate.is_active and candidate.check_password(password):
            record_audit(action="auth.login_inactive", target=candidate, request=request)
            raise AccountInactive()
        security.register_failure(email)
        record_audit(action="auth.login_failed", request=request, changes={"email_sha256": _email_fingerprint(email)})
        raise InvalidCredentials()

    security.clear_failures(email)
    update_last_login(None, user)
    record_audit(action="auth.login", actor=user, target=user, request=request)
    return user


# --- Passwords ------------------------------------------------------------------------


@transaction.atomic
def change_password(user, *, current_password: str, new_password: str, request=None) -> dict:
    if not user.check_password(current_password):
        raise exceptions.ValidationError({"current_password": ["Current password is incorrect."]})
    if current_password == new_password:
        raise exceptions.ValidationError({"new_password": ["Choose a password different from the current one."]})
    validate_new_password(new_password, user, field="new_password")
    user.set_password(new_password)
    user.save(update_fields=["password", "password_changed_at", "updated_at"])
    revoke_all_sessions(user)
    record_audit(action="auth.password_change", actor=user, target=user, request=request)
    return issue_tokens(user)  # keep this session signed in


def build_reset_link(user) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"


def request_password_reset(*, email: str, request=None) -> None:
    """Always succeeds from the caller's point of view (no account enumeration)."""
    user = User.objects.filter(email=(email or "").strip().lower(), is_active=True).first()
    if user is None or not user.has_usable_password():
        return
    minutes = settings.PASSWORD_RESET_TIMEOUT // 60
    send_mail(
        subject=f"Reset your {settings.APP_NAME} password",
        message=(
            f"Hello {user.get_short_name()},\n\n"
            f"We received a request to reset your {settings.APP_NAME} password. Open this link to choose a new one:\n\n"
            f"{build_reset_link(user)}\n\n"
            f"The link expires in {minutes} minutes and can be used once. "
            "If you didn't ask for this, you can ignore this email; your password won't change.\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
    record_audit(action="auth.password_reset_requested", target=user, request=request)


@transaction.atomic
def reset_password(*, uid: str, token: str, new_password: str, request=None):
    invalid = ServiceError(
        "This reset link is invalid or has expired. Please request a new one.", code="invalid_reset_token"
    )
    try:
        user_pk = force_str(urlsafe_base64_decode(uid))
        user = User.objects.select_for_update().get(pk=user_pk, is_active=True)
    except (ValueError, TypeError, OverflowError, User.DoesNotExist):
        raise invalid from None
    if not default_token_generator.check_token(user, token):
        raise invalid
    validate_new_password(new_password, user)
    user.set_password(new_password)  # changes the hash → this token can never be reused
    user.save(update_fields=["password", "password_changed_at", "updated_at"])
    revoke_all_sessions(user)
    security.clear_failures(user.email)
    record_audit(action="auth.password_reset", actor=user, target=user, request=request)
    return user


# --- Account lifecycle ---------------------------------------------------------------------


@transaction.atomic
def deactivate_account(user, *, password: str, reason: str = "", actor=None, request=None) -> None:
    """Self-service deactivation (requires the password). Data is kept; an admin can reactivate."""
    if not user.check_password(password):
        raise exceptions.ValidationError({"password": ["Password is incorrect."]})
    _set_active(user, False, actor=actor or user, request=request, reason=reason)


def _set_active(user, active: bool, *, actor, request=None, reason: str = "") -> None:
    user.is_active = active
    user.deactivated_at = None if active else timezone.now()
    user.save(update_fields=["is_active", "deactivated_at", "updated_at"])
    if not active:
        revoke_all_sessions(user)
    record_audit(
        action="user.reactivate" if active else "user.deactivate",
        actor=actor,
        target=user,
        request=request,
        changes={"reason": reason[:200]} if reason else {},
    )


@transaction.atomic
def anonymize_user(user, *, actor, request=None) -> None:
    """Erase personal data on request while keeping orders/invoices (address snapshots are
    retained for accounting/legal reasons). Irreversible; admin-only."""
    user.email = f"deleted-user-{user.pk}@deleted.invalid"
    user.full_name = ""
    user.phone = None
    user.set_unusable_password()
    user.is_active = False
    user.deactivated_at = timezone.now()
    user.save()
    for address in Address.all_objects.filter(user=user):
        address.name, address.phone, address.address_line1, address.address_line2 = "Deleted", "0000000000", "-", ""
        address.landmark, address.latitude, address.longitude, address.is_deleted = "", None, None, True
        address.save()
    if hasattr(user, "profile"):
        user.profile.avatar.delete(save=False)
        user.profile.marketing_opt_in = user.profile.whatsapp_opt_in = False
        user.profile.save()
    revoke_all_sessions(user)
    record_audit(action="user.anonymize", actor=actor, target=user, request=request)
