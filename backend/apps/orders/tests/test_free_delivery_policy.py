"""The shop's checkout policy: free delivery from ₹2,000, payment labels that say what really happens, and the
browser being allowed to place an order from the development site (another origin than the API)."""

import os
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from apps.core.testing import create_address, create_product, create_store

pytestmark = pytest.mark.django_db
BACKEND = Path(__file__).resolve().parents[3]


@pytest.fixture
def shop(user, settings):
    settings.FREE_DELIVERY_MIN_ORDER = Decimal("2000.00")  # the shop's policy (tests otherwise pin ₹499)
    store = create_store()
    _, plank = create_product(name="Plank", price="1000.00", mrp="1200.00", stock=20, store=store)
    _, board = create_product(name="Board", price="999.50", mrp="1200.00", stock=20, store=store)
    return {"plank": plank, "board": board, "address": create_address(user)}


def _preview(client, shop, variant, quantity):
    res = client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": quantity}, format="json")
    assert res.status_code == 201, res.json()
    res = client.post("/api/checkout/preview/", {"address_id": shop["address"].id}, format="json")
    assert res.status_code == 200, res.json()
    return res.json()


def test_shipped_default_is_free_delivery_from_2000():
    """What a server gets without FREE_DELIVERY_MIN_ORDER in its .env (the developer's .env is not read)."""
    empty_env = Path(tempfile.gettempdir()) / "as-hardware-tests-empty.env"
    empty_env.write_text("", encoding="utf-8")
    environment = {
        k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "FREE_DELIVERY", "DELIVERY_FEE"))
    }
    environment.update(
        DJANGO_SETTINGS_MODULE="config.settings.dev", ENV_FILE=str(empty_env), DJANGO_SECRET_KEY="x" * 60
    )
    code = (
        "import django; django.setup(); from django.conf import settings as s; "
        "print(s.FREE_DELIVERY_MIN_ORDER, s.DELIVERY_FEE)"
    )
    result = subprocess.run(  # noqa: S603 — our own interpreter and fixed code
        [sys.executable, "-c", code], cwd=BACKEND, env=environment, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2000.00", "40.00"]


def test_order_of_exactly_2000_ships_free(auth_client, shop):
    delivery = _preview(auth_client, shop, shop["plank"], 2)["delivery"]
    assert delivery["free_delivery_min_order"] == "2000.00"
    assert delivery["fee"] == "0.00" and delivery["amount_to_free_delivery"] == "0.00"


def test_order_just_below_2000_pays_the_fee_and_is_told_how_much_more(auth_client, shop):
    data = _preview(auth_client, shop, shop["board"], 2)  # ₹1,999.00
    assert data["delivery"]["fee"] == "40.00" and data["delivery"]["amount_to_free_delivery"] == "1.00"
    assert data["totals"]["grand_total"] == "2039.00"


def test_mock_and_razorpay_test_mode_are_labelled_for_what_they_are(auth_client, shop, settings):
    online = next(m for m in _preview(auth_client, shop, shop["plank"], 1)["payment_methods"] if m["value"] == "online")
    assert online["provider"] == "mock" and online["label"].startswith("Mock online payment")

    settings.PAYMENT_PROVIDER = "razorpay"
    settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET = "rzp_test_ABCDEF123456", "test-secret-not-real"
    res = auth_client.post("/api/checkout/preview/", {"address_id": shop["address"].id}, format="json")
    online = next(m for m in res.json()["payment_methods"] if m["value"] == "online")
    assert online["provider"] == "razorpay" and online["test_mode"] is True
    assert "Razorpay test mode" in online["label"] and "Mock" not in online["label"]


def test_browser_may_send_the_idempotency_key_from_the_development_site(api_client, settings):
    """The order request carries Idempotency-Key; the preflight must allow it or the browser never sends the order."""
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5173"]
    res = api_client.options(
        "/api/orders/",
        HTTP_ORIGIN="http://localhost:5173",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type,idempotency-key",
    )
    assert res.status_code == 200
    assert res["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "idempotency-key" in res["Access-Control-Allow-Headers"].lower()


def test_large_order_offers_cod_and_razorpay_and_cod_stays_unpaid(auth_client, shop, settings):
    """The shop takes COD for any total (no limit) next to Razorpay; a COD order is confirmed but unpaid."""
    from apps.payments.models import PaymentSettings

    payment = PaymentSettings.load()
    payment.cod_max_order_value = None
    payment.save()
    settings.PAYMENT_PROVIDER = "razorpay"
    settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET = "rzp_test_ABCDEF123456", "test-secret-not-real"
    data = _preview(auth_client, shop, shop["plank"], 3)  # ₹3,000: above the old ₹2,500 limit
    methods = {m["value"]: m for m in data["payment_methods"]}
    assert methods["online"]["available"] is True and methods["online"]["provider"] == "razorpay"
    assert methods["cod"]["available"] is True and methods["cod"]["max_order_value"] is None

    res = auth_client.post(
        "/api/orders/",
        {"address_id": shop["address"].id, "payment_method": "cod", "expected_total": data["totals"]["grand_total"]},
        format="json",
    )
    assert res.status_code == 201, res.json()
    order = res.json()
    assert (order["status"], order["payment_method"], order["payment_status"]) == ("confirmed", "cod", "pending")
    assert order["can_retry_payment"] is False
