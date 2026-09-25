"""Phase 8: payment state is decided by the gateway (checkout verification, webhooks, reconciliation),
never by the browser; webhooks are applied once; unpaid orders expire; late or duplicate money is refunded."""

import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.utils import timezone

from apps.carts.services import add_item
from apps.core.models import AuditLog
from apps.inventory.models import Inventory
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderStatus, OrderStatusHistory
from apps.orders.services import cancel_order_by_customer, place_order
from apps.payments import services
from apps.payments.models import Payment, Refund, WebhookEvent
from apps.payments.refunds import process_refund
from integrations.payments import GatewayError, GatewayPayment, RefundResult, VerificationResult
from integrations.payments.mock import mock_webhook_body, sign_mock_webhook

pytestmark = pytest.mark.django_db


def _online_order(user, shop, variant="tape", qty=1):
    add_item(user, shop[variant].id, qty)
    return place_order(user=user, address_id=shop["address"].id, payment_method="online")


def _post_webhook(client, body, provider="razorpay", event_id="evt_1", signature=None):
    headers = {"HTTP_X_MOCK_SIGNATURE": signature or sign_mock_webhook(body), "HTTP_X_MOCK_EVENT_ID": event_id}
    return client.post(f"/api/payments/webhooks/{provider}/", body, content_type="application/json", **headers)


def _captured_body(payment, amount=None, pid="pay_W1", event="payment.captured", status="captured"):
    entity = {
        "id": pid,
        "entity": "payment",
        "status": status,
        "order_id": payment.provider_order_id,
        "amount": int((amount if amount is not None else payment.amount) * 100),
        "currency": "INR",
        "method": "card",
        "card": {"last4": "4242"},
        "email": "a@example.com",
        "error_description": "Bank declined" if status == "failed" else None,
    }
    return mock_webhook_body(event, payment=entity)


# --- Checkout verification ----------------------------------------------------------------------


def test_checkout_success_is_confirmed_with_the_gateway(auth_client, user, shop, gateway):
    order, payment = _online_order(user, shop)
    assert payment.provider == "razorpay"
    res = auth_client.post(
        f"/api/payments/{payment.public_id}/verify/", {"payload": {"razorpay_payment_id": "x"}}, format="json"
    )
    data = res.json()
    assert (data["status"], data["payment_status"]) == ("confirmed", "paid")
    payment.refresh_from_db()
    assert payment.metadata["captured_via"] == "checkout" and payment.provider_payment_id.startswith("pay_fake_")


def test_browser_claiming_success_is_not_enough(auth_client, user, shop, gateway):
    order, payment = _online_order(user, shop)
    gateway.verify_result = VerificationResult(success=False, failure_reason="Invalid payment signature.")
    data = auth_client.post(
        f"/api/payments/{payment.public_id}/verify/", {"payload": {"status": "success", "paid": True}}, format="json"
    ).json()
    assert (data["status"], data["payment_status"]) == ("pending", "failed")
    assert not Payment.objects.filter(status="captured").exists()


def test_gateway_still_processing_keeps_the_attempt_open(auth_client, user, shop, gateway):
    order, payment = _online_order(user, shop)
    gateway.verify_result = VerificationResult(success=False, pending=True)
    data = auth_client.post(f"/api/payments/{payment.public_id}/verify/", {"payload": {}}, format="json").json()
    assert (data["status"], data["payment_status"]) == ("pending", "pending")
    assert data["payments"][0]["status"] == "created"  # a webhook or reconciliation will finish it


def test_gateway_outage_during_verify_changes_nothing(auth_client, user, shop, gateway):
    order, payment = _online_order(user, shop)
    gateway.verify_result = GatewayError("timeout")
    res = auth_client.post(f"/api/payments/{payment.public_id}/verify/", {"payload": {}}, format="json")
    assert res.status_code == 409 and res.json()["error"]["code"] == "payment_verification_unavailable"
    payment.refresh_from_db()
    assert payment.status == "created"


def test_retry_inside_the_widget_after_a_failure_is_accepted_when_the_gateway_confirms(
    auth_client, user, shop, gateway
):
    order, payment = _online_order(user, shop)
    Payment.objects.filter(pk=payment.pk).update(status="failed", failure_reason="Bank declined")
    data = auth_client.post(f"/api/payments/{payment.public_id}/verify/", {"payload": {}}, format="json").json()
    assert data["payment_status"] == "paid" and data["status"] == "confirmed"


def test_other_customers_payment_is_invisible(api_client, other_user, user, shop, gateway):
    _, payment = _online_order(user, shop)
    api_client.force_authenticate(other_user)
    assert (
        api_client.post(f"/api/payments/{payment.public_id}/verify/", {"payload": {}}, format="json").status_code == 404
    )


def test_amount_mismatch_is_never_confirmed_and_is_refunded(user, shop, gateway):
    order, payment = _online_order(user, shop)
    gateway.verify_result = VerificationResult(success=True, provider_payment_id="pay_x", amount=Decimal("1.00"))
    services.verify_payment(payment.public_id, user=user, payload={})
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.status == "pending" and order.payment_status != "paid"
    assert payment.status == "captured" and payment.amount == Decimal("1.00") and "mismatch" in payment.failure_reason
    assert Refund.objects.get().amount == Decimal("1.00")
    assert AuditLog.objects.filter(action="payment.amount_mismatch").exists()


# --- Webhooks ---------------------------------------------------------------------------------


def test_webhook_confirms_order_once_even_when_redelivered(api_client, user, shop, gateway):
    order, payment = _online_order(user, shop)
    body = _captured_body(payment)
    for _ in range(3):
        res = _post_webhook(api_client, body)
        assert res.status_code == 200
    order.refresh_from_db()
    assert (order.status, order.payment_status) == ("confirmed", "paid")
    assert OrderStatusHistory.objects.filter(order=order, to_status="confirmed").count() == 1
    event = WebhookEvent.objects.get()
    assert (event.status, event.deliveries, event.event_type) == ("processed", 3, "payment.captured")
    stored = json.dumps(event.payload)
    assert "4242" not in stored and "a@example.com" not in stored  # no card or contact data kept
    payment.refresh_from_db()
    assert payment.provider_payment_id == "pay_W1" and payment.method == "card"


def test_webhook_with_bad_signature_is_rejected_and_not_stored(api_client, user, shop, gateway):
    _, payment = _online_order(user, shop)
    body = _captured_body(payment)
    res = _post_webhook(api_client, body, signature="0" * 64)
    assert res.status_code == 400 and res.json()["error"]["code"] == "invalid_webhook"
    tampered = body.replace(b'"status": "captured"', b'"status": "captured", "x": 1')
    assert _post_webhook(api_client, tampered, signature=sign_mock_webhook(body)).status_code == 400
    assert not WebhookEvent.objects.exists() and Payment.objects.get().status == "created"


def test_webhook_for_a_provider_that_is_not_configured_is_404(api_client, user, shop, gateway):
    _, payment = _online_order(user, shop)
    assert _post_webhook(api_client, _captured_body(payment), provider="mock").status_code == 404
    assert _post_webhook(api_client, _captured_body(payment), provider="stripe").status_code == 404


def test_failed_then_captured_in_the_same_gateway_order(
    api_client, user, shop, gateway, django_capture_on_commit_callbacks
):
    order, payment = _online_order(user, shop)
    with django_capture_on_commit_callbacks(execute=True):
        _post_webhook(
            api_client, _captured_body(payment, event="payment.failed", status="failed", pid="pay_A"), event_id="e1"
        )
    order.refresh_from_db()
    assert order.payment_status == "failed"
    assert Notification.objects.filter(event="payment.failed").exists()
    _post_webhook(api_client, _captured_body(payment, pid="pay_B"), event_id="e2")
    order.refresh_from_db()
    payment.refresh_from_db()
    assert (order.status, order.payment_status, payment.provider_payment_id) == ("confirmed", "paid", "pay_B")


def test_late_failure_never_undoes_a_capture(api_client, user, shop, gateway):
    order, payment = _online_order(user, shop)
    _post_webhook(api_client, _captured_body(payment), event_id="e1")
    _post_webhook(
        api_client, _captured_body(payment, event="payment.failed", status="failed", pid="pay_Z"), event_id="e2"
    )
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == "captured" and order.payment_status == "paid"


def test_money_arriving_after_cancellation_is_refunded(api_client, user, shop, gateway):
    order, payment = _online_order(user, shop)
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    _post_webhook(api_client, _captured_body(payment))
    order.refresh_from_db()
    refund = Refund.objects.get()
    assert order.status == "cancelled" and refund.amount == payment.amount
    assert "after the order was cancelled" in refund.reason


def test_second_paid_attempt_is_refunded_as_duplicate(api_client, auth_client, user, shop, gateway):
    order, first = _online_order(user, shop)
    Payment.objects.filter(pk=first.pk).update(status="cancelled")  # customer closed the widget…
    auth_client.post(f"/api/orders/{order.order_number}/retry-payment/")
    second = order.payments.get(status="created")
    _post_webhook(api_client, _captured_body(second, pid="pay_2"), event_id="e2")
    first.refresh_from_db()
    _post_webhook(api_client, _captured_body(first, pid="pay_1"), event_id="e1")  # …but had paid after all
    refund = Refund.objects.get()
    assert refund.payment_id == first.pk and "Duplicate" in refund.reason
    order.refresh_from_db()
    assert order.payment_status == "paid" and order.status == "confirmed"


def test_unknown_event_is_ignored_and_processing_errors_are_retried(api_client, user, shop, gateway):
    _, payment = _online_order(user, shop)
    res = _post_webhook(api_client, mock_webhook_body("settlement.processed"), event_id="e0")
    assert res.status_code == 200 and WebhookEvent.objects.get(event_id="e0").status == "ignored"

    body = _captured_body(payment)
    with mock.patch.object(services, "apply_gateway_payment", side_effect=RuntimeError("db down")):
        assert _post_webhook(api_client, body, event_id="e9").status_code == 500
    assert WebhookEvent.objects.get(event_id="e9").status == "failed"
    assert _post_webhook(api_client, body, event_id="e9").status_code == 200  # the gateway's redelivery
    assert WebhookEvent.objects.get(event_id="e9").status == "processed"
    assert Payment.objects.get().status == "captured"


def test_refund_webhook_updates_the_refund(api_client, user, shop, gateway, staff_user):
    order, payment = _online_order(user, shop)
    services.verify_payment(payment.public_id, user=user, payload={})
    gateway.refund_outcomes = [RefundResult(True, "rfnd_W", "pending")]
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    refund = Refund.objects.get()
    process_refund(refund.pk)
    refund.refresh_from_db()
    assert (refund.status, refund.provider_refund_id) == ("pending", "rfnd_W")
    body = mock_webhook_body(
        "refund.processed", refund={"id": "rfnd_W", "payment_id": "pay_x", "status": "processed", "amount": 7000}
    )
    assert _post_webhook(api_client, body, event_id="r1").status_code == 200
    refund.refresh_from_db()
    order.refresh_from_db()
    assert refund.status == "processed" and order.payment_status == "refunded"
    unknown = mock_webhook_body("refund.processed", refund={"id": "rfnd_nope", "status": "processed", "amount": 1})
    _post_webhook(api_client, unknown, event_id="r2")
    assert WebhookEvent.objects.get(event_id="r2").status == "ignored"


# --- Reconciliation and expiry -----------------------------------------------------------------


def _age(order, minutes):
    past = timezone.now() - timedelta(minutes=minutes)
    Order.objects.filter(pk=order.pk).update(created_at=past)
    Payment.objects.filter(order=order).update(created_at=past)


def test_reconciliation_recovers_a_payment_the_browser_never_reported(user, shop, gateway):
    order, payment = _online_order(user, shop)
    _age(order, 15)
    gateway.order_payments[payment.provider_order_id] = [
        GatewayPayment("pay_R", "failed", payment.amount, payment.provider_order_id),
        GatewayPayment("pay_R2", "authorized", payment.amount, payment.provider_order_id),
    ]
    assert services.reconcile_stale_payments() == 1
    order.refresh_from_db()
    assert (order.status, order.payment_status) == ("confirmed", "paid") and gateway.captures == ["pay_R2"]
    assert services.reconcile_stale_payments() == 0  # captured now: nothing left to check


def test_recent_attempts_are_left_alone(user, shop, gateway):
    order, payment = _online_order(user, shop)
    gateway.order_payments[payment.provider_order_id] = GatewayError("should not be called")
    assert services.reconcile_stale_payments() == 0


def test_unpaid_order_expires_and_releases_stock(user, shop, gateway, django_capture_on_commit_callbacks):
    order, payment = _online_order(user, shop, qty=3)
    inv = Inventory.objects.get(store=shop["store"], variant=shop["tape"])
    assert (inv.available_quantity, inv.reserved_quantity) == (47, 3)
    _age(order, 31)
    with django_capture_on_commit_callbacks(execute=True):
        assert services.expire_unpaid_orders() == 1
    order.refresh_from_db()
    inv.refresh_from_db()
    assert order.status == "cancelled" and order.cancellation_reason == "Payment not completed in time"
    assert (inv.available_quantity, inv.reserved_quantity) == (50, 0)
    assert Payment.objects.get().status == "cancelled"
    assert Notification.objects.filter(event="order.expired").exists()


def test_expiry_confirms_instead_when_the_gateway_has_the_money(user, shop, gateway):
    order, payment = _online_order(user, shop)
    _age(order, 31)
    gateway.order_payments[payment.provider_order_id] = [
        GatewayPayment("pay_late", "captured", payment.amount, payment.provider_order_id)
    ]
    assert services.expire_unpaid_orders() == 0
    order.refresh_from_db()
    assert order.status == "confirmed"


def test_expiry_waits_while_the_gateway_is_unreachable(user, shop, gateway):
    order, payment = _online_order(user, shop)
    _age(order, 31)
    gateway.order_payments[payment.provider_order_id] = GatewayError("timeout")
    assert services.expire_unpaid_orders() == 0
    order.refresh_from_db()
    assert order.status == "pending"


def test_expiry_ignores_cod_recent_and_paid_orders(user, shop, gateway):
    add_item(user, shop["tape"].id, 1)
    cod, _ = place_order(user=user, address_id=shop["address"].id, payment_method="cod")
    recent, _ = _online_order(user, shop)
    _age(cod, 120)
    assert services.expire_unpaid_orders() == 0
    assert Order.objects.get(pk=cod.pk).status == OrderStatus.CONFIRMED
    assert Order.objects.get(pk=recent.pk).status == OrderStatus.PENDING


# --- Security ---------------------------------------------------------------------------------


def test_no_gateway_secret_reaches_the_customer(auth_client, user, shop, gateway, settings):
    settings.RAZORPAY_KEY_SECRET, settings.RAZORPAY_WEBHOOK_SECRET = "sk_secret_value_1", "whsec_value_2"
    order, _ = _online_order(user, shop)
    raw = auth_client.get(f"/api/orders/{order.order_number}/").content.decode()
    assert "sk_secret_value_1" not in raw and "whsec_value_2" not in raw
    assert '"key_id": "rzp_test_fake"' in raw.replace('":"', '": "')


def test_customers_cannot_use_staff_refund_endpoints(auth_client, api_client):
    assert auth_client.get("/api/payments/refunds/").status_code == 403
    assert api_client.get("/api/payments/refunds/").status_code == 401
