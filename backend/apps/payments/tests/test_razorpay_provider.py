"""RazorpayPaymentProvider against a recorded fake of Razorpay's REST API (no network, no credentials)."""

import hashlib
import hmac
import io
import json
import urllib.error
from decimal import Decimal
from unittest import mock

import pytest
from django.core.exceptions import ImproperlyConfigured

from integrations.payments import GatewayError, GatewayRejected, InvalidSignature
from integrations.payments.razorpay import RazorpayClient, RazorpayPaymentProvider

KEY_ID, KEY_SECRET, WEBHOOK_SECRET = "rzp_test_abc123", "test-key-secret-not-real", "whsec_value"


class FakeApi:
    """Stands in for RazorpayClient: routes (method, path) to canned responses and records calls."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def request(self, method, path, body=None, params=None):
        self.calls.append((method, path, body))
        reply = self.routes[(method, path)]
        if isinstance(reply, Exception):
            raise reply
        return reply(body) if callable(reply) else reply


@pytest.fixture
def provider(settings):
    settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET = KEY_ID, KEY_SECRET
    settings.RAZORPAY_WEBHOOK_SECRET = WEBHOOK_SECRET
    return RazorpayPaymentProvider()


def _sig(order_id, payment_id, secret=KEY_SECRET):
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def _payment(status="captured", amount=11000, order_id="order_1", **extra):
    return {"id": "pay_1", "entity": "payment", "status": status, "amount": amount, "currency": "INR",
            "order_id": order_id, "method": "upi", **extra}  # fmt: skip


def test_missing_credentials_refuse_to_start(settings):
    settings.RAZORPAY_KEY_ID = settings.RAZORPAY_KEY_SECRET = ""
    with pytest.raises(ImproperlyConfigured):
        RazorpayPaymentProvider()


def test_create_payment_sends_paise_and_exposes_only_public_data(provider):
    provider.client = FakeApi({("POST", "/orders"): {"id": "order_1", "amount": 11050, "status": "created"}})
    intent = provider.create_payment(
        reference="OD260925ABCDEF",
        amount=Decimal("110.50"),
        customer={"name": "Asha", "email": "a@example.com", "contact": "9876543210", "password": "x"},
    )
    _, _, body = provider.client.calls[0]
    assert body == {
        "amount": 11050,
        "currency": "INR",
        "receipt": "OD260925ABCDEF",
        "notes": {"reference": "OD260925ABCDEF"},
    }
    assert intent.provider_order_id == "order_1"
    payload = intent.client_payload
    assert payload["key_id"] == KEY_ID and payload["order_id"] == "order_1" and payload["amount"] == 11050
    assert payload["prefill"] == {"name": "Asha", "email": "a@example.com", "contact": "9876543210"}
    dumped = json.dumps(payload)
    assert KEY_SECRET not in dumped and WEBHOOK_SECRET not in dumped
    assert provider.is_test_mode is True


def test_verify_checks_signature_then_asks_razorpay(provider):
    provider.client = FakeApi({("GET", "/payments/pay_1"): _payment()})
    payload = {
        "razorpay_order_id": "order_1",
        "razorpay_payment_id": "pay_1",
        "razorpay_signature": _sig("order_1", "pay_1"),
    }
    result = provider.verify_payment(provider_order_id="order_1", payload=payload, expected_amount=Decimal("110.00"))
    assert result.success and result.provider_payment_id == "pay_1" and result.amount == Decimal("110.00")
    assert result.method == "upi"


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"razorpay_order_id": "order_1", "razorpay_payment_id": "pay_1", "razorpay_signature": "forged"}, "Invalid"),
        (
            {"razorpay_order_id": "order_OTHER", "razorpay_payment_id": "pay_1", "razorpay_signature": "x"},
            "does not match",
        ),
        (
            {
                "razorpay_order_id": "order_1",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": _sig("order_1", "pay_1", secret="wrong"),
            },
            "Invalid",
        ),  # fmt: skip
        ({}, "does not match"),
    ],
)
def test_forged_or_mismatched_responses_fail_without_calling_razorpay(provider, payload, reason):
    provider.client = FakeApi({})
    result = provider.verify_payment(provider_order_id="order_1", payload=payload)
    assert not result.success and reason in result.failure_reason
    assert provider.client.calls == []


@pytest.mark.parametrize(
    ("gateway", "expected"),
    [
        (_payment(amount=100), "Paid amount does not match"),
        (_payment(order_id="order_2"), "different order"),
        (_payment(status="failed", error_description="Card declined"), "Card declined"),
    ],
)
def test_server_side_fetch_is_the_source_of_truth(provider, gateway, expected):
    provider.client = FakeApi({("GET", "/payments/pay_1"): gateway})
    payload = {
        "razorpay_order_id": "order_1",
        "razorpay_payment_id": "pay_1",
        "razorpay_signature": _sig("order_1", "pay_1"),
    }
    result = provider.verify_payment(provider_order_id="order_1", payload=payload, expected_amount=Decimal("110.00"))
    assert not result.success and expected in result.failure_reason


def test_authorized_payment_is_captured_and_created_one_is_pending(provider):
    provider.client = FakeApi(
        {
            ("GET", "/payments/pay_1"): _payment(status="authorized"),
            ("POST", "/payments/pay_1/capture"): _payment(status="captured"),
        }
    )
    payload = {
        "razorpay_order_id": "order_1",
        "razorpay_payment_id": "pay_1",
        "razorpay_signature": _sig("order_1", "pay_1"),
    }
    assert provider.verify_payment(provider_order_id="order_1", payload=payload).success
    assert provider.client.calls[-1] == ("POST", "/payments/pay_1/capture", {"amount": 11000, "currency": "INR"})

    provider.client = FakeApi({("GET", "/payments/pay_1"): _payment(status="created")})
    result = provider.verify_payment(provider_order_id="order_1", payload=payload)
    assert result.pending and not result.success and not result.failure_reason


def test_capture_refused_because_already_captured_is_still_a_success(provider):
    """Auto-capture or the webhook captured it between our fetch and our capture call."""
    replies = iter([_payment(status="authorized"), _payment(status="captured")])
    provider.client = FakeApi(
        {
            ("GET", "/payments/pay_1"): lambda body: next(replies),
            ("POST", "/payments/pay_1/capture"): GatewayRejected("This payment has already been captured"),
        }
    )
    payload = {
        "razorpay_order_id": "order_1",
        "razorpay_payment_id": "pay_1",
        "razorpay_signature": _sig("order_1", "pay_1"),
    }
    result = provider.verify_payment(provider_order_id="order_1", payload=payload, expected_amount=Decimal("110.00"))
    assert result.success and result.provider_payment_id == "pay_1" and result.amount == Decimal("110.00")
    assert [c[:2] for c in provider.client.calls] == [
        ("GET", "/payments/pay_1"), ("POST", "/payments/pay_1/capture"), ("GET", "/payments/pay_1")
    ]  # fmt: skip


def test_capture_refused_and_still_authorized_is_pending_not_paid(provider):
    provider.client = FakeApi(
        {
            ("GET", "/payments/pay_1"): _payment(status="authorized"),
            ("POST", "/payments/pay_1/capture"): GatewayRejected("Capture amount mismatch"),
        }
    )
    payload = {
        "razorpay_order_id": "order_1",
        "razorpay_payment_id": "pay_1",
        "razorpay_signature": _sig("order_1", "pay_1"),
    }
    result = provider.verify_payment(provider_order_id="order_1", payload=payload)
    assert result.pending and not result.success


def test_cancelled_checkout_needs_no_gateway_call(provider):
    provider.client = FakeApi({})
    result = provider.verify_payment(provider_order_id="order_1", payload={"cancelled": True})
    assert result.cancelled and not result.success


def test_refund_is_idempotent_on_our_reference(provider):
    existing = {"id": "rfnd_1", "status": "processed", "amount": 5000, "notes": {"reference": "ref-1"}}
    provider.client = FakeApi({("GET", "/payments/pay_1/refunds"): {"items": [existing]}})
    result = provider.refund(provider_payment_id="pay_1", amount=Decimal("50.00"), reference="ref-1")
    assert (result.provider_refund_id, result.status) == ("rfnd_1", "processed")
    assert [c[0] for c in provider.client.calls] == ["GET"]  # found the first attempt: no second refund

    provider.client = FakeApi(
        {
            ("GET", "/payments/pay_1/refunds"): {"items": [existing]},
            ("POST", "/payments/pay_1/refund"): {"id": "rfnd_2", "status": "pending", "amount": 2000},
        }
    )
    result = provider.refund(provider_payment_id="pay_1", amount=Decimal("20.00"), reference="ref-2")
    assert (result.provider_refund_id, result.status, result.success) == ("rfnd_2", "pending", True)
    assert provider.client.calls[-1][2] == {
        "amount": 2000, "speed": "normal", "receipt": "ref-2", "notes": {"reference": "ref-2"}
    }  # fmt: skip


def test_refund_status_mapping(provider):
    provider.client = FakeApi({("GET", "/payments/pay_1/refunds/rfnd_1"): {"id": "rfnd_1", "status": "failed"}})
    result = provider.fetch_refund(provider_payment_id="pay_1", provider_refund_id="rfnd_1")
    assert result.status == "failed" and not result.success and result.failure_reason


def _webhook(event="payment.captured"):
    entity = _payment(card={"last4": "4242", "network": "Visa"}, email="a@example.com", contact="+919876543210",
                      vpa="asha@upi", bank="HDFC", notes={"secret": "x"})  # fmt: skip
    return json.dumps({"entity": "event", "event": event, "payload": {"payment": {"entity": entity}}}).encode()


def test_webhook_signature_and_sanitised_payload(provider):
    body = _webhook()
    headers = {
        "X-Razorpay-Signature": hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest(),
        "X-Razorpay-Event-Id": "evt_1",
    }
    event = provider.parse_webhook(body=body, headers=headers)
    assert (event.event_id, event.event_type) == ("evt_1", "payment.captured")
    assert event.payment.provider_order_id == "order_1" and event.payment.amount == Decimal("110.00")
    stored = json.dumps(event.data)
    for secret_bit in ("4242", "Visa", "a@example.com", "9876543210", "asha@upi", "HDFC", '"secret"'):
        assert secret_bit not in stored


@pytest.mark.parametrize("tamper", ["body", "signature", "missing", "no_secret"])
def test_webhook_forgeries_are_rejected(provider, settings, tamper):
    body = _webhook()
    signature = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if tamper == "body":
        body = body.replace(b"11000", b"1")
    headers = {} if tamper == "missing" else {"X-Razorpay-Signature": "0" * 64 if tamper == "signature" else signature}
    if tamper == "no_secret":
        provider.webhook_secret = ""
    with pytest.raises(InvalidSignature):
        provider.parse_webhook(body=body, headers=headers)


def _http_error(code, description="Bad request"):
    return urllib.error.HTTPError(
        "https://api.razorpay.com/v1/orders",
        code,
        "err",
        {},
        io.BytesIO(json.dumps({"error": {"description": description}}).encode()),
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_http_error(400, "The amount must be at least INR 1.00"), GatewayRejected),
        (_http_error(401), GatewayRejected),
        (_http_error(429), GatewayError),
        (_http_error(502), GatewayError),
        (urllib.error.URLError("timed out"), GatewayError),
        (TimeoutError("read timeout"), GatewayError),
    ],
)
def test_http_errors_map_to_retryable_or_final(error, expected):
    client = RazorpayClient(KEY_ID, KEY_SECRET, "https://api.razorpay.com/v1")
    with mock.patch("urllib.request.urlopen", side_effect=error), pytest.raises(expected):
        client.request("POST", "/orders", {"amount": 100})


def test_client_uses_basic_auth_and_json(monkeypatch):
    captured = {}

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout):
        captured["req"], captured["timeout"] = req, timeout
        return _Response(b'{"id": "order_1"}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = RazorpayClient(KEY_ID, KEY_SECRET, "https://api.razorpay.com/v1/")
    assert client.request("POST", "/orders", {"amount": 100}) == {"id": "order_1"}
    req = captured["req"]
    assert req.full_url == "https://api.razorpay.com/v1/orders" and req.get_method() == "POST"
    assert req.get_header("Authorization").startswith("Basic ") and json.loads(req.data) == {"amount": 100}


@pytest.mark.parametrize("base", ["http://api.razorpay.com/v1", "file:///etc/passwd", "ftp://x"])
def test_client_refuses_non_https_endpoints(base):
    with pytest.raises(ImproperlyConfigured):
        RazorpayClient(KEY_ID, KEY_SECRET, base)
