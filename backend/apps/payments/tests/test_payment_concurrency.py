"""Phase 8 races with real threads: duplicate webhook deliveries, checkout verification racing its
own webhook, double refund processing, and expiry racing a late payment."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.carts.services import add_item
from apps.core.testing import create_address
from apps.orders.models import Order, OrderStatusHistory
from apps.orders.services import cancel_order_by_customer, place_order
from apps.orders.tests.test_concurrency import run_concurrently
from apps.payments import services
from apps.payments.consistency import find_issues
from apps.payments.models import Payment, Refund, WebhookEvent
from apps.payments.refunds import process_refund
from integrations.payments.mock import mock_webhook_body, sign_mock_webhook

pytestmark = pytest.mark.django_db(transaction=True)


def _online(user, shop):
    add_item(user, shop["tape"].id, 1)
    return place_order(user=user, address_id=create_address(user).id, payment_method="online")


def _deliver_webhook(payment, event_id="evt_race"):
    body = mock_webhook_body(
        "payment.captured",
        payment={
            "id": "pay_race",
            "status": "captured",
            "order_id": payment.provider_order_id,
            "amount": int(payment.amount * 100),
            "currency": "INR",
            "method": "upi",
        },  # fmt: skip
    )
    headers = {"X-Mock-Signature": sign_mock_webhook(body), "X-Mock-Event-Id": event_id}
    return lambda: services.process_webhook("razorpay", body=body, headers=headers)


def test_same_webhook_delivered_concurrently_is_applied_once(user, shop, gateway):
    order, payment = _online(user, shop)
    deliver = _deliver_webhook(payment)

    results = run_concurrently(deliver, deliver, deliver, deliver)

    assert all(outcome == "ok" for outcome, _ in results), results
    event = WebhookEvent.objects.get()
    assert event.status == "processed" and event.deliveries == 4
    assert OrderStatusHistory.objects.filter(order=order, to_status="confirmed").count() == 1
    assert Payment.objects.get().status == "captured"


def test_checkout_verification_racing_its_webhook_captures_once(user, shop, gateway):
    order, payment = _online(user, shop)

    results = run_concurrently(
        lambda: services.verify_payment(payment.public_id, user=user, payload={}), _deliver_webhook(payment)
    )

    assert all(outcome == "ok" for outcome, _ in results), results
    order.refresh_from_db()
    assert (order.status, order.payment_status) == ("confirmed", "paid")
    assert OrderStatusHistory.objects.filter(order=order, to_status="confirmed").count() == 1
    assert not Refund.objects.exists() and find_issues() == []


def test_refund_processed_twice_at_once_refunds_once(user, shop, gateway):
    order, payment = _online(user, shop)
    services.verify_payment(payment.public_id, user=user, payload={})
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    refund = Refund.objects.get()

    results = run_concurrently(lambda: process_refund(refund.pk), lambda: process_refund(refund.pk))

    assert all(outcome == "ok" for outcome, _ in results), results
    refund.refresh_from_db()
    assert refund.status == "processed"
    # Both workers may have called the gateway, but always with the same reference → one refund there.
    assert {call[2] for call in gateway.refund_calls} == {refund.provider_reference}
    assert len(gateway._refunds_by_reference) == 1
    assert find_issues() == []


def test_expiry_racing_a_late_payment_never_loses_money(user, shop, gateway):
    order, payment = _online(user, shop)
    past = timezone.now() - timedelta(minutes=45)
    Order.objects.filter(pk=order.pk).update(created_at=past)
    Payment.objects.filter(pk=payment.pk).update(created_at=past)

    results = run_concurrently(services.expire_unpaid_orders, _deliver_webhook(payment))

    assert all(outcome == "ok" for outcome, _ in results), results
    order.refresh_from_db()
    if order.status == "cancelled":
        assert Refund.objects.get().amount == payment.amount  # paid after expiry: money goes back
    else:
        assert order.status == "confirmed" and not Refund.objects.exists()
    assert find_issues() == []
