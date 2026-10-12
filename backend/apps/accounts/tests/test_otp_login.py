"""Customer sign-in with a mobile number and an SMS code (accounts.otp)."""

import re
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import PhoneOTP, User
from integrations.messaging import OUTBOX, reset_messaging_providers

pytestmark = pytest.mark.django_db
REQUEST, VERIFY = "/api/auth/otp/request/", "/api/auth/otp/verify/"
PHONE = "9876501234"


@pytest.fixture(autouse=True)
def _mock_sms(settings):
    settings.OTP_LOGIN_ENABLED = True  # off by default until a real SMS gateway is set up
    settings.SMS_PROVIDER = "mock"
    settings.OTP_MOCK_ALLOWED = True
    reset_messaging_providers()
    OUTBOX.clear()
    yield
    reset_messaging_providers()


def last_code(phone=PHONE) -> str:
    message = [m for m in OUTBOX if m["to"] == f"91{phone}"][-1]
    return re.match(r"^(\d{6}) is your ", message["text"])[1]


def send(client, phone=PHONE, **extra):
    return client.post(REQUEST, {"phone": phone, **extra}, format="json")


def verify(client, code, phone=PHONE, **extra):
    return client.post(VERIFY, {"phone": phone, "code": code, **extra}, format="json")


def test_new_number_signs_up_with_a_name_and_gets_tokens(api_client):
    res = send(api_client, "+91 98765 01234")
    assert res.status_code == 200, res.json()
    body = res.json()
    assert body == {"phone": "+91 ******1234", "expires_in": 300, "resend_in": 30, "length": 6, "sms_sent": False}
    code = last_code()
    assert code not in str(body)  # the code is only in the SMS
    stored = PhoneOTP.objects.get()
    assert code not in stored.code_hash and len(stored.code_hash) == 64

    needs_name = verify(api_client, code)
    assert needs_name.status_code == 400 and needs_name.json()["error"]["code"] == "name_required"
    created = verify(api_client, code, full_name="Ravi Kumar")
    assert created.status_code == 201, created.json()
    data = created.json()
    assert data["access"] and data["refresh"] and data["user"]["phone"] == PHONE
    user = User.objects.get(phone=PHONE)
    assert user.full_name == "Ravi Kumar" and user.email is None and user.phone_verified
    assert not user.has_usable_password() and user.role == User.Role.CUSTOMER
    # Used once: the same code can't sign in again.
    assert verify(api_client, code).json()["error"]["code"] == "otp_expired"


def test_existing_customer_signs_in_and_their_phone_is_verified(api_client, user):
    user.phone = PHONE
    user.save()
    send(api_client)
    res = verify(api_client, last_code())
    assert res.status_code == 200 and res.json()["user"]["email"] == user.email
    user.refresh_from_db()
    assert user.phone_verified
    assert User.objects.count() == 1  # no duplicate account


def test_wrong_codes_count_down_and_then_the_code_is_dead(api_client, settings):
    settings.OTP_MAX_ATTEMPTS = 3
    send(api_client)
    good = last_code()
    wrong = "000000" if good != "000000" else "111111"
    first = verify(api_client, wrong).json()["error"]
    assert first["code"] == "otp_invalid" and "2 attempts left" in first["message"]
    verify(api_client, wrong)
    third = verify(api_client, wrong)
    assert third.status_code == 429 and third.json()["error"]["code"] == "otp_too_many_attempts"
    assert verify(api_client, good, full_name="X").json()["error"]["code"] == "otp_too_many_attempts"
    assert PhoneOTP.objects.get().attempts == 3  # every wrong guess was stored, not rolled back
    assert not User.objects.filter(phone=PHONE).exists()


def test_expired_code_is_refused(api_client):
    send(api_client)
    code = last_code()
    PhoneOTP.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    res = verify(api_client, code, full_name="Late")
    assert res.status_code == 400 and res.json()["error"]["code"] == "otp_expired"


def test_resend_waits_for_the_cooldown_and_supersedes_the_old_code(api_client):
    send(api_client)
    old = last_code()
    again = send(api_client)
    assert again.status_code == 429 and again.json()["error"]["code"] == "otp_cooldown"
    assert 0 < again.json()["error"]["details"]["retry_after"] <= 30
    PhoneOTP.objects.update(created_at=timezone.now() - timedelta(seconds=31))
    assert send(api_client).status_code == 200
    new = last_code()
    if new != old:
        assert verify(api_client, old, full_name="A").json()["error"]["code"] in ("otp_invalid", "otp_expired")
    assert verify(api_client, new, full_name="A").status_code == 201


def test_hourly_limit_per_number(api_client, settings):
    settings.OTP_MAX_SENDS_PER_HOUR = 2
    send(api_client)
    PhoneOTP.objects.update(created_at=timezone.now() - timedelta(minutes=5))
    assert send(api_client).status_code == 200
    PhoneOTP.objects.update(created_at=timezone.now() - timedelta(minutes=5))
    res = send(api_client)
    assert res.status_code == 429 and res.json()["error"]["code"] == "too_many_otp_requests"


@pytest.mark.parametrize("phone", ["12345", "5876501234", "98765012345678", "abcdefghij"])
def test_invalid_numbers(api_client, phone):
    res = send(api_client, phone)
    assert res.status_code == 400 and res.json()["error"]["code"] == "invalid_phone"
    assert not OUTBOX


def test_only_indian_numbers(api_client):
    assert send(api_client, country_code="+1").json()["error"]["code"] == "invalid_phone"


def test_staff_accounts_keep_email_login(api_client, admin_user):
    admin_user.phone = PHONE
    admin_user.save()
    send(api_client)
    res = verify(api_client, last_code())
    assert res.status_code == 403 and res.json()["error"]["code"] == "use_email_login"


def test_no_sms_provider_means_no_code_and_no_pretending(api_client, settings):
    settings.SMS_PROVIDER = "none"
    reset_messaging_providers()
    res = send(api_client)
    assert res.status_code == 503 and res.json()["error"]["code"] == "sms_unavailable"
    assert not PhoneOTP.objects.exists()


def test_mock_sms_is_refused_where_not_allowed(api_client, settings):
    settings.OTP_MOCK_ALLOWED = False  # production
    res = send(api_client)
    assert res.status_code == 503 and not OUTBOX and not PhoneOTP.objects.exists()


def test_a_failed_send_leaves_no_usable_code(api_client):
    res = send(api_client, "9876500000")  # the mock treats …0000 as unreachable
    assert res.status_code == 503
    assert not PhoneOTP.objects.filter(consumed_at__isnull=True).exists()


def test_email_given_at_sign_up_must_be_free(api_client, user):
    send(api_client)
    res = verify(api_client, last_code(), full_name="Asha", email=user.email)
    assert res.status_code == 409 and res.json()["error"]["code"] == "email_taken"


def test_phone_only_customer_can_add_a_first_email_without_a_password(api_client):
    send(api_client)
    tokens = verify(api_client, last_code(), full_name="Ravi").json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    res = api_client.patch("/api/profile/", {"email": "ravi@example.com"}, format="json")
    assert res.status_code == 200, res.json()
    assert User.objects.get(phone=PHONE).email == "ravi@example.com"


def test_email_password_login_still_works(api_client, user):
    res = api_client.post("/api/auth/login/", {"email": user.email, "password": "S3cure-pass!"}, format="json")
    assert res.status_code == 200


def test_switched_off_no_code_is_made_and_nothing_is_sent(api_client, settings):
    settings.OTP_LOGIN_ENABLED = False  # the launch default
    res = send(api_client)
    assert res.status_code == 503 and res.json()["error"]["code"] == "otp_login_disabled"
    assert not PhoneOTP.objects.exists() and not OUTBOX
    res = verify(api_client, "123456")
    assert res.status_code == 503 and res.json()["error"]["code"] == "otp_login_disabled"


def test_the_mock_says_no_sms_was_sent(api_client):
    res = send(api_client)
    assert res.status_code == 200 and res.json()["sms_sent"] is False  # the page must not claim "Code sent"
