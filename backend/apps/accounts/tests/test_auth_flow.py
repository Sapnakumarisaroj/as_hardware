"""End-to-end auth API: register, login + lockout, refresh rotation, logout, password change/reset."""

import re
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db

PASSWORD = "S3cure-pass!"  # conftest default
NEW_PASSWORD = "Fresh-Pass-2026"


def _bearer(token: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _login(api_client, email, password=PASSWORD):
    return api_client.post("/api/auth/login/", {"email": email, "password": password}, format="json")


def _old_access_token(user) -> str:
    """An access token issued a few seconds ago (JWT `iat` has whole-second precision)."""
    access = RefreshToken.for_user(user).access_token
    access.set_iat(at_time=timezone.now() - timedelta(seconds=10))
    return str(access)


def test_register_creates_customer_and_ignores_requested_role(api_client):
    payload = {
        "full_name": "New Buyer",
        "email": "New.Buyer@Example.com",
        "phone": "9876543210",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
        "role": "admin",
    }
    res = api_client.post("/api/auth/register/", payload, format="json")
    assert res.status_code == 201, res.json()
    body = res.json()
    assert body["access"] and body["refresh"]
    assert body["user"]["email"] == "new.buyer@example.com"
    assert body["user"]["role"] == "customer"

    again = api_client.post("/api/auth/register/", {**payload, "phone": "9876543211"}, format="json")
    assert again.status_code == 400


def test_login_rejects_bad_password_then_locks_the_account(api_client, user, settings):
    assert _login(api_client, user.email, "wrong-password").status_code == 401
    for _ in range(settings.LOGIN_MAX_FAILURES - 1):
        _login(api_client, user.email, "wrong-password")
    res = _login(api_client, user.email)  # correct password, but locked
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "too_many_attempts"


def _login_phone(api_client, phone, password=PASSWORD):
    return api_client.post("/api/auth/login/", {"phone": phone, "password": password}, format="json")


def test_customer_logs_in_with_mobile_number_and_password(api_client, user):
    user.phone = "9876543210"
    user.save()
    for typed in ("9876543210", "+91 98765 43210", "098765-43210"):
        res = _login_phone(api_client, typed)
        assert res.status_code == 200, res.json()
        assert res.json()["access"] and res.json()["user"]["id"] == user.id


def test_mobile_login_errors_are_generic(api_client, user):
    user.phone = "9876543210"
    user.save()
    wrong_password = _login_phone(api_client, "9876543210", "wrong-password")
    unknown_number = _login_phone(api_client, "9876543299")
    assert wrong_password.status_code == unknown_number.status_code == 401
    assert wrong_password.json()["error"] == unknown_number.json()["error"]


def test_mobile_and_email_share_one_lockout(api_client, user, settings):
    user.phone = "9876543210"
    user.save()
    for i in range(settings.LOGIN_MAX_FAILURES):
        if i % 2:
            _login(api_client, user.email, "wrong-password")
        else:
            _login_phone(api_client, "9876543210", "wrong-password")
    assert _login_phone(api_client, "9876543210").status_code == 429
    assert _login(api_client, user.email).status_code == 429


def test_phone_only_account_has_no_password_to_log_in_with(api_client):
    from apps.accounts.models import User

    User.objects.create_user(email=None, full_name="Ravi", phone="9876543210")  # unusable password
    assert _login_phone(api_client, "9876543210", "").status_code == 400
    assert _login_phone(api_client, "9876543210", "anything-at-all").status_code == 401


def test_login_needs_a_mobile_number_or_email(api_client, user):
    res = api_client.post("/api/auth/login/", {"password": PASSWORD}, format="json")
    assert res.status_code == 400
    both = api_client.post(
        "/api/auth/login/", {"email": user.email, "phone": "9876543210", "password": PASSWORD}, format="json"
    )
    assert both.status_code == 400


def test_staff_role_is_unchanged_by_mobile_login(api_client, admin_user):
    admin_user.phone = "9876543211"
    admin_user.save()
    res = _login_phone(api_client, "9876543211")
    assert res.status_code == 200 and res.json()["user"]["role"] == "admin"


def test_inactive_account_cannot_log_in(api_client, user):
    user.is_active = False
    user.save()
    assert _login(api_client, user.email).status_code == 403


def test_refresh_rotates_and_logout_blacklists(api_client, user):
    refresh = _login(api_client, user.email).json()["refresh"]

    res = api_client.post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")
    assert res.status_code == 200
    rotated = res.json()["refresh"]
    assert rotated != refresh
    # The old refresh token was blacklisted by rotation.
    assert api_client.post("/api/auth/token/refresh/", {"refresh": refresh}, format="json").status_code == 401

    assert api_client.post("/api/auth/logout/", {"refresh": rotated}, format="json").status_code == 205
    assert api_client.post("/api/auth/token/refresh/", {"refresh": rotated}, format="json").status_code == 401


def test_password_change_revokes_older_tokens_and_keeps_this_session(api_client, user):
    user.password_changed_at = timezone.now() - timedelta(hours=1)
    user.save(update_fields=["password_changed_at"])
    old_refresh = _login(api_client, user.email).json()["refresh"]
    old_client = _bearer(_old_access_token(user))
    assert old_client.get("/api/auth/me/").status_code == 200

    res = old_client.post(
        "/api/auth/password/change/",
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD, "new_password_confirm": NEW_PASSWORD},
        format="json",
    )
    assert res.status_code == 200, res.json()

    assert old_client.get("/api/auth/me/").status_code == 401
    assert api_client.post("/api/auth/token/refresh/", {"refresh": old_refresh}, format="json").status_code == 401
    assert _bearer(res.json()["access"]).get("/api/auth/me/").status_code == 200
    assert _login(api_client, user.email, NEW_PASSWORD).status_code == 200


def test_forgot_password_does_not_reveal_whether_an_account_exists(
    api_client, user, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):  # the email is sent by a job, after the request
        unknown = api_client.post("/api/auth/password/forgot/", {"email": "nobody@example.com"}, format="json")
        known = api_client.post("/api/auth/password/forgot/", {"email": user.email}, format="json")
    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json()
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [user.email]


def test_password_reset_link_works_once_and_signs_out_other_sessions(
    api_client, user, django_capture_on_commit_callbacks
):
    old_refresh = _login(api_client, user.email).json()["refresh"]
    with django_capture_on_commit_callbacks(execute=True):
        api_client.post("/api/auth/password/forgot/", {"email": user.email}, format="json")
    link = re.search(r"http\S+reset-password\S+", mail.outbox[0].body).group(0)
    assert link.startswith("http://testserver-frontend/reset-password?")
    query = parse_qs(urlparse(link).query)
    payload = {
        "uid": query["uid"][0],
        "token": query["token"][0],
        "password": NEW_PASSWORD,
        "password_confirm": NEW_PASSWORD,
    }

    assert api_client.post("/api/auth/password/reset/", payload, format="json").status_code == 200
    reused = api_client.post("/api/auth/password/reset/", payload, format="json")
    assert reused.status_code == 400 and reused.json()["error"]["code"] == "invalid_reset_token"

    assert api_client.post("/api/auth/token/refresh/", {"refresh": old_refresh}, format="json").status_code == 401
    assert _login(api_client, user.email).status_code == 401
    assert _login(api_client, user.email, NEW_PASSWORD).status_code == 200


def test_tampered_reset_token_is_rejected(api_client, user):
    payload = {"uid": "MQ", "token": "bogus-token", "password": NEW_PASSWORD, "password_confirm": NEW_PASSWORD}
    res = api_client.post("/api/auth/password/reset/", payload, format="json")
    assert res.status_code == 400 and res.json()["error"]["code"] == "invalid_reset_token"
