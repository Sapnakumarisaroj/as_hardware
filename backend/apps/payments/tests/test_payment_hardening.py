"""Payment fixes (2026-10): gateway errors never become 500s or half-made orders, a capture that loses
the race to the webhook still confirms the order, redelivered `payment.authorized` events don't fail
forever, the product page only offers online payment when checkout accepts it, and the site's
Permissions-Policy lets Razorpay use the browser Payment Request API (Google Pay / UPI apps)."""

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings as django_settings

from apps.carts.services import add_item
from apps.core.testing import create_product
from apps.inventory.models import Inventory
from apps.orders.models import Order
from apps.orders.services import PaymentGatewayUnavailable, place_order
from apps.payments.models import Payment, WebhookEvent
from integrations.payments import GatewayError, GatewayPayment, GatewayRejected
from integrations.payments.mock import mock_webhook_body, sign_mock_webhook

pytestmark = pytest.mark.django_db


def _online_order(user, shop):
    add_item(user, shop["tape"].id, 1)
    return place_order(user=user, address_id=shop["address"].id, payment_method="online")


def _webhook(client, payment, *, status, event="payment.captured", event_id="evt_1", pid="pay_W1"):
    body = mock_webhook_body(
        event,
        payment={
            "id": pid,
            "entity": "payment",
            "status": status,
            "order_id": payment.provider_order_id,
            "amount": int(payment.amount * 100),
            "currency": "INR",
            "method": "upi",
        },
    )
    return client.post(
        "/api/payments/webhooks/razorpay/",
        body,
        content_type="application/json",
        HTTP_X_MOCK_SIGNATURE=sign_mock_webhook(body),
        HTTP_X_MOCK_EVENT_ID=event_id,
    )


# --- Opening a payment ----------------------------------------------------------------------------


@pytest.mark.parametrize("error", [GatewayError("timeout"), GatewayRejected("Authentication failed")])
def test_gateway_failure_at_checkout_is_a_clear_503_and_nothing_is_kept(auth_client, user, shop, gateway, error):
    add_item(user, shop["tape"].id, 2)
    stock_before = list(Inventory.objects.values_list("pk", "available_quantity", "reserved_quantity"))
    gateway.create_payment = lambda **kwargs: (_ for _ in ()).throw(error)

    res = auth_client.post(
        "/api/orders/", {"address_id": shop["address"].id, "payment_method": "online"}, format="json"
    )

    assert res.status_code == 503
    body = res.json()["error"]
    assert body["code"] == "payment_gateway_unavailable" and "Nothing was charged" in body["message"]
    assert not Order.objects.exists() and not Payment.objects.exists()
    assert list(Inventory.objects.values_list("pk", "available_quantity", "reserved_quantity")) == stock_before
    assert user.cart.items.count() == 1  # the cart is untouched: the customer can try again


def test_gateway_failure_on_retry_keeps_the_previous_attempt(auth_client, user, shop, gateway):
    order, payment = _online_order(user, shop)
    Payment.objects.filter(pk=payment.pk).update(status=Payment.Status.FAILED)
    gateway.create_payment = lambda **kwargs: (_ for _ in ()).throw(GatewayError("down"))

    res = auth_client.post(f"/api/orders/{order.order_number}/retry-payment/", {}, format="json")

    assert res.status_code == 503 and res.json()["error"]["code"] == "payment_gateway_unavailable"
    assert list(order.payments.values_list("status", flat=True)) == ["failed"]


def test_place_order_raises_the_service_error(user, shop, gateway):
    gateway.create_payment = lambda **kwargs: (_ for _ in ()).throw(GatewayError("down"))
    add_item(user, shop["tape"].id, 1)
    with pytest.raises(PaymentGatewayUnavailable):
        place_order(user=user, address_id=shop["address"].id, payment_method="online")


# --- Verification ---------------------------------------------------------------------------------


def test_gateway_refusing_verification_is_a_409_and_changes_nothing(auth_client, user, shop, gateway):
    order, payment = _online_order(user, shop)
    gateway.verify_result = GatewayRejected("The id provided does not exist")

    res = auth_client.post(f"/api/payments/{payment.public_id}/verify/", {"payload": {"x": "y"}}, format="json")

    assert res.status_code == 409 and res.json()["error"]["code"] == "payment_verification_failed"
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == "created" and order.payment_status == "pending" and order.status == "pending"


# --- Webhooks: payment.authorized ------------------------------------------------------------------


def test_authorized_webhook_whose_capture_lost_the_race_still_confirms(api_client, user, shop, gateway):
    order, payment = _online_order(user, shop)

    def already_captured(**kwargs):
        raise GatewayRejected("This payment has already been captured")

    gateway.capture = already_captured
    gateway.order_payments[payment.provider_order_id] = [
        GatewayPayment(provider_payment_id="pay_W1", status="captured", amount=payment.amount, method="upi")
    ]

    res = _webhook(api_client, payment, status="authorized", event="payment.authorized")

    assert res.status_code == 200
    assert WebhookEvent.objects.get().status == "processed"
    order.refresh_from_db()
    assert (order.status, order.payment_status) == ("confirmed", "paid")


def test_authorized_webhook_after_capture_is_ignored_without_capturing_again(api_client, user, shop, gateway):
    order, payment = _online_order(user, shop)
    assert _webhook(api_client, payment, status="captured", event_id="evt_cap").status_code == 200

    res = _webhook(api_client, payment, status="authorized", event="payment.authorized", event_id="evt_auth")

    assert res.status_code == 200 and gateway.captures == []
    assert WebhookEvent.objects.get(event_id="evt_auth").status == "ignored"
    assert Payment.objects.filter(status="captured").count() == 1


def test_failed_webhook_marks_payment_failed_and_never_paid(api_client, user, shop, gateway):
    order, payment = _online_order(user, shop)
    assert _webhook(api_client, payment, status="failed", event="payment.failed").status_code == 200
    order.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == "failed" and order.payment_status == "failed" and order.status == "pending"


# --- What the customer is told --------------------------------------------------------------------


@pytest.mark.parametrize(("provider", "online"), [("none", False), ("mock", True)])
def test_product_quote_only_offers_online_payment_when_checkout_accepts_it(api_client, settings, provider, online):
    settings.PAYMENT_PROVIDER = provider
    product, _ = create_product(price="500.00", mrp="600.00", stock=5)
    quote = api_client.get(f"/api/products/{product.slug}/quote/", {"quantity": 1}).json()
    assert quote["payment_options"]["online"] is online


def test_site_permissions_policy_allows_razorpay_payment_requests():
    """`payment=()` blocked the Payment Request API that Razorpay uses for Google Pay / UPI apps."""
    conf = Path(django_settings.BASE_DIR).parent / "frontend" / "nginx" / "security-headers.conf"
    if not conf.exists():
        pytest.skip("frontend/ is not next to backend/ (e.g. inside the backend image)")
    header = re.search(r"Permissions-Policy\s+'([^']+)'", conf.read_text(encoding="utf-8"))
    assert header, "Permissions-Policy header not found (or not single-quoted)"
    payment = re.search(r"payment=\(([^)]*)\)", header.group(1))
    assert payment, "payment directive missing"
    allowed = payment.group(1).split()
    assert "self" in allowed and json.dumps("https://api.razorpay.com") in allowed
    assert "*" not in allowed  # only our page and Razorpay's frames


def test_amounts_are_decided_by_the_server(auth_client, user, shop, gateway):
    """The gateway order is opened for the server's total; a browser can't send its own amount."""
    add_item(user, shop["tape"].id, 3)
    res = auth_client.post(
        "/api/orders/",
        {"address_id": shop["address"].id, "payment_method": "online", "amount": "1.00", "grand_total": "1.00"},
        format="json",
    )
    assert res.status_code == 201, res.content
    payment = Payment.objects.get()
    assert payment.amount == payment.order.grand_total and payment.amount > Decimal("1.00")
