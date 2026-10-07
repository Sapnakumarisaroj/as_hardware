"""Phase 25 security regression tests: one or more per issue found in the security review."""

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core import mail
from django.test import RequestFactory
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts import auth_services, security
from apps.core.audit import _client_ip
from apps.core.models import AuditLog
from apps.core.testing import create_product, create_store
from apps.delivery.models import DeliveryZone
from apps.inventory.models import Inventory

pytestmark = pytest.mark.django_db
BACKEND = Path(__file__).resolve().parents[3]


@pytest.fixture
def real_auth_limit(monkeypatch):
    """The production `auth` rate (tests otherwise run with generous limits)."""
    from rest_framework.throttling import ScopedRateThrottle

    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {**ScopedRateThrottle.THROTTLE_RATES, "auth": "10/min"})


PASSWORD = "S3cure-pass!"


def login(client, email, password=PASSWORD, ip="10.0.0.1", forwarded=None):
    extra = {"REMOTE_ADDR": ip}
    if forwarded:
        extra["HTTP_X_FORWARDED_FOR"] = forwarded
    return client.post("/api/auth/login/", {"email": email, "password": password}, format="json", **extra)


# --- Rate limits can't be dodged with a fake X-Forwarded-For --------------------------------------------


def test_fake_forwarded_for_headers_do_not_reset_the_login_rate_limit(user, real_auth_limit):
    client = APIClient()
    codes = [login(client, f"nobody{i}@example.com", forwarded=f"203.0.113.{i}").status_code for i in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429  # same REMOTE_ADDR → same bucket


def test_audit_ip_trusts_only_our_own_proxies(settings):
    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR="6.6.6.6, 198.51.100.7")
    assert _client_ip(request) == "10.0.0.9"  # no trusted proxy: the header is ignored
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    assert _client_ip(request) == "198.51.100.7"  # the address our proxy added, not the forged one


# --- Login lockout and timing -------------------------------------------------------------------------------


def test_lockout_window_is_restored_after_each_failure(settings, monkeypatch):
    settings.LOGIN_LOCKOUT_SECONDS = 900
    touched = []
    monkeypatch.setattr(security.cache, "touch", lambda key, timeout: touched.append(timeout) or True)
    for _ in range(3):
        security.register_failure("someone@example.com")
    assert touched == [900, 900]  # the first failure creates the key with the window; later ones restore it


def test_every_failed_login_costs_one_extra_hash(user, monkeypatch):
    calls = []
    monkeypatch.setattr(auth_services, "make_password", lambda pw: calls.append(pw) or "x")
    client = APIClient()
    assert login(client, "nobody@example.com", "wrong-pass1").status_code == 401
    assert login(client, user.email, "wrong-pass1").status_code == 401
    user.is_active = False
    user.save(update_fields=["is_active"])
    assert login(client, user.email, "wrong-pass1").status_code == 401
    assert calls == ["wrong-pass1", "wrong-pass1"]  # inactive accounts pay for their own second check


# --- Forgot password: no account oracle --------------------------------------------------------------------


def test_reset_email_failure_never_reaches_the_client(user, monkeypatch, django_capture_on_commit_callbacks):
    def broken(**kwargs):
        raise ConnectionRefusedError("SMTP down")

    monkeypatch.setattr(auth_services, "send_mail", broken)
    with django_capture_on_commit_callbacks(execute=True):
        known = APIClient().post("/api/auth/password/forgot/", {"email": user.email}, format="json")
        unknown = APIClient().post("/api/auth/password/forgot/", {"email": "x@example.com"}, format="json")
    assert known.status_code == unknown.status_code == 200 and known.json() == unknown.json()


# --- Profile changes ---------------------------------------------------------------------------------------------


def test_profile_changes_share_the_account_rate_limit(auth_client, real_auth_limit):
    codes = [
        auth_client.patch("/api/profile/", {"full_name": f"Name {i}"}, format="json").status_code for i in range(11)
    ]
    assert codes[:10] == [200] * 10 and codes[10] == 429
    assert auth_client.get("/api/profile/").status_code == 200  # reading isn't limited this way


def test_email_change_is_announced_to_the_old_address(user, auth_client, django_capture_on_commit_callbacks):
    old = user.email
    with django_capture_on_commit_callbacks(execute=True):
        res = auth_client.patch(
            "/api/profile/", {"email": "new-address@example.com", "current_password": PASSWORD}, format="json"
        )
    assert res.status_code == 200
    notice = [m for m in mail.outbox if m.to == [old]]
    assert len(notice) == 1 and "ne•••@example.com" in notice[0].body and "new-address@" not in notice[0].body


# --- Uploads and request size -----------------------------------------------------------------------------------


def test_oversized_requests_are_refused_before_parsing(api_client, settings):
    settings.MAX_REQUEST_BYTES = 1000
    res = api_client.post("/api/auth/login/", data=b"x" * 2000, content_type="application/json")
    assert res.status_code == 413 and res.json()["error"]["code"] == "request_too_large"


def _jpeg_with_location():
    from django.core.files.uploadedfile import SimpleUploadedFile

    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    exif[0x8825] = {1: "N", 2: (18.0, 31.0, 0.0)}  # GPS
    out = io.BytesIO()
    Image.new("RGB", (300, 300), (10, 120, 200)).save(out, format="JPEG", exif=exif)
    return SimpleUploadedFile("me.jpg", out.getvalue(), content_type="image/jpeg")


def test_avatars_are_re_encoded_without_location_data(user, auth_client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    res = auth_client.post("/api/profile/avatar/", {"avatar": _jpeg_with_location()}, format="multipart")
    assert res.status_code == 200
    user.profile.refresh_from_db()
    with user.profile.avatar.open("rb") as handle, Image.open(handle) as stored:
        assert stored.format == "JPEG" and not stored.getexif()


def test_model_validation_errors_are_400_not_500(auth_client, settings, tmp_path):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = tmp_path
    out = io.BytesIO()
    Image.new("RGB", (20, 20)).save(out, format="GIF")
    gif = SimpleUploadedFile("me.gif", out.getvalue(), content_type="image/gif")
    res = auth_client.post("/api/profile/avatar/", {"avatar": gif}, format="multipart")
    assert res.status_code == 400 and res.json()["error"]["code"] == "validation_error"


# --- Administration ---------------------------------------------------------------------------------------------


def test_admins_cannot_change_the_owner_account(admin_client):
    from django.contrib.auth import get_user_model

    owner = get_user_model().objects.create_user("owner@example.com", PASSWORD, role="admin", is_superuser=True)
    for change in ({"is_active": False}, {"role": "customer"}, {"role": "store_manager"}):
        res = admin_client.patch(f"/api/admin/users/{owner.pk}/", change, format="json")
        assert res.status_code == 400 and res.json()["error"]["code"] == "owner_protected"
    owner.refresh_from_db()
    assert owner.is_active and owner.role == "admin"


def test_the_last_active_admin_cannot_be_demoted_or_deactivated(admin_user):
    from django.contrib.auth import get_user_model

    from apps.accounts.admin_services import UserManagementError, update_user

    root = get_user_model().objects.create_user("root@example.com", PASSWORD, role="customer", is_superuser=True)
    for change in ({"role": "customer"}, {"is_active": False}):
        with pytest.raises(UserManagementError, match="at least one active administrator"):
            update_user(admin_user, actor=root, **change)
    get_user_model().objects.create_user("admin2@example.com", PASSWORD, role="admin")
    assert update_user(admin_user, actor=root, role="customer").role == "customer"  # another admin remains


def test_managers_only_see_their_stores_cod_settings(staff_user, staff_client):
    mine, theirs = create_store(name="Mine"), create_store(name="Theirs")
    mine.managers.add(staff_user)
    for store in (mine, theirs):
        store.cod_enabled = False
        store.save(update_fields=["cod_enabled"])
    DeliveryZone.objects.filter(store=theirs).update(cod_enabled=False)
    data = staff_client.get("/api/admin/payment-settings/").json()
    assert [s["name"] for s in data["stores_without_cod"]] == ["Mine"]
    assert all(z["store_name"] == "Mine" for z in data["zones_without_cod"])


def test_inventory_threshold_changes_are_audited(staff_user, staff_client):
    store = create_store()
    store.managers.add(staff_user)
    _, variant = create_product(stock=5, store=store)
    row = Inventory.objects.get(variant=variant, store=store)
    res = staff_client.patch(f"/api/inventory/{row.pk}/", {"low_stock_threshold": 9}, format="json")
    assert res.status_code == 200
    entry = AuditLog.objects.get(action="inventory.update")
    assert entry.changes == {"low_stock_threshold": {"from": row.low_stock_threshold, "to": 9}}


def test_search_index_errors_do_not_echo_internal_details(admin_client, monkeypatch):
    from apps.catalog.semantic import index

    def broken(*args, **kwargs):
        raise RuntimeError(r"model missing at C:\secret\models\x.bin")

    monkeypatch.setattr(index, "sync_products", broken)
    res = admin_client.post("/api/admin/search/index/rebuild/", {"force": True}, format="json")
    assert (
        res.status_code == 503
        and "secret" not in res.content.decode()
        and "keyword search keeps working" in res.content.decode()
    )


# --- Production settings ---------------------------------------------------------------------------------------


def _settings_import(module: str, **env) -> subprocess.CompletedProcess:
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "PAYMENT_", "RAZORPAY_"))}
    environment.update(DJANGO_SETTINGS_MODULE=module, ENV_FILE=str(BACKEND / "no-such.env"), **env)
    code = "import django; django.setup(); from django.conf import settings; print(settings.DEBUG)"
    return subprocess.run(  # noqa: S603 — our own interpreter and fixed code
        [sys.executable, "-c", code], cwd=BACKEND, env=environment, capture_output=True, text=True, timeout=120
    )


STRONG = "k" * 30 + "Zq8-" + "x" * 30
PROD = {
    "PAYMENT_PROVIDER": "razorpay",
    "RAZORPAY_KEY_ID": "a",
    "RAZORPAY_KEY_SECRET": "b",
    "RAZORPAY_WEBHOOK_SECRET": "c",
}


@pytest.mark.parametrize(
    "env,message",
    [
        ({"DJANGO_SECRET_KEY": "django-insecure-abc", "DJANGO_ALLOWED_HOSTS": "api.example.com", **PROD}, "too weak"),
        ({"DJANGO_SECRET_KEY": STRONG, "DJANGO_ALLOWED_HOSTS": "*", **PROD}, "DJANGO_ALLOWED_HOSTS"),
    ],
)
def test_production_settings_refuse_unsafe_configuration(env, message):
    result = _settings_import("config.settings.prod", **env)
    assert result.returncode != 0 and message in result.stderr


def test_production_settings_never_enable_debug():
    result = _settings_import(
        "config.settings.prod",
        DJANGO_SECRET_KEY=STRONG,
        DJANGO_ALLOWED_HOSTS="api.example.com",
        DJANGO_DEBUG="true",
        **PROD,
    )
    assert result.returncode == 0 and result.stdout.strip() == "False"


def test_development_settings_refuse_a_production_environment():
    result = _settings_import("config.settings.dev", DJANGO_SECRET_KEY=STRONG, DJANGO_ENV="production")
    assert result.returncode != 0 and "DJANGO_ENV=production" in result.stderr


def test_secrets_and_local_files_are_not_tracked_by_git():
    git = ["git", "ls-files"]
    tracked = subprocess.run(git, cwd=BACKEND, capture_output=True, text=True).stdout.splitlines()  # noqa: S603, S607
    bad = [f for f in tracked if f.endswith((".sqlite3", ".env", ".log", ".pem", ".key")) or "settings.local.json" in f]
    assert bad == []
