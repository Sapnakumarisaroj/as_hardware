"""Phase 8: refunds go to the gateway (idempotently), are tracked to "processed", and only then move
payment/order to refunded; COD money is refunded by staff with a reference."""

from decimal import Decimal

import pytest

from apps.carts.services import add_item
from apps.core.jobs import run_due_jobs
from apps.core.models import Job
from apps.notifications.models import Notification
from apps.orders.returns import approve_return, receive_return, request_return
from apps.orders.services import cancel_order_by_customer, place_order, transition_order
from apps.payments import refunds, services
from apps.payments.models import Payment, Refund
from apps.payments.refunds import RefundError, create_refund, process_refund
from integrations.payments import GatewayError, GatewayRejected, RefundResult

pytestmark = pytest.mark.django_db
FULFIL = ("processing", "packed", "assigned", "picked_up", "out_for_delivery", "delivered")


def _paid_order(user, shop, qty=2, variant="tape"):
    add_item(user, shop[variant].id, qty)
    order, payment = place_order(user=user, address_id=shop["address"].id, payment_method="online")
    services.verify_payment(payment.public_id, user=user, payload={})
    payment.refresh_from_db()
    return order, payment


def _cod_delivered(user, shop, staff, qty=2):
    add_item(user, shop["tape"].id, qty)
    order, payment = place_order(user=user, address_id=shop["address"].id, payment_method="cod")
    for status in FULFIL:
        order = transition_order(order, status, actor=staff)
    payment.refresh_from_db()
    return order, payment


def test_cancelled_paid_order_is_refunded_through_the_gateway(user, shop, gateway, django_capture_on_commit_callbacks):
    order, payment = _paid_order(user, shop)
    with django_capture_on_commit_callbacks(execute=True):  # inline mode: the job runs after commit
        cancel_order_by_customer(order, user=user, reason="Changed my mind")
    refund = Refund.objects.get()
    assert refund.status == "processed" and refund.provider_refund_id.startswith("rfnd_")
    assert gateway.refund_calls == [(payment.provider_payment_id, payment.amount, refund.provider_reference)]
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == "refunded" and order.payment_status == "refunded"
    assert Job.objects.get(name="payments.process_refund").status == "done"
    assert Notification.objects.filter(event="refund.processed").exists()


def test_cron_mode_only_queues(user, shop, gateway, settings, django_capture_on_commit_callbacks):
    settings.BACKGROUND_JOBS_MODE = "cron"
    order, _ = _paid_order(user, shop)
    with django_capture_on_commit_callbacks(execute=True):
        cancel_order_by_customer(order, user=user, reason="Changed my mind")
    assert Refund.objects.get().status == "pending" and gateway.refund_calls == []
    assert run_due_jobs() >= 1  # the refund (and the cancellation messages)
    assert Refund.objects.get().status == "processed"


def test_outage_is_retried_with_the_same_reference(user, shop, gateway, settings):
    settings.BACKGROUND_JOBS_MODE = "cron"
    order, _ = _paid_order(user, shop)
    gateway.refund_outcomes = [GatewayError("timeout")]
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    run_due_jobs()
    job = Job.objects.get()
    refund = Refund.objects.get()
    assert (job.status, job.attempts, refund.status) == ("queued", 1, "pending") and "timeout" in job.last_error
    Job.objects.filter(pk=job.pk).update(run_after=job.created_at)  # backoff elapsed
    run_due_jobs()
    refund.refresh_from_db()
    assert refund.status == "processed" and refund.attempts == 2
    assert {call[2] for call in gateway.refund_calls} == {refund.provider_reference}  # one refund at the gateway


def test_repeated_processing_never_refunds_twice(user, shop, gateway):
    order, payment = _paid_order(user, shop)
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    refund = Refund.objects.get()
    assert process_refund(refund.pk) == "processed"
    assert process_refund(refund.pk) == "skipped"
    assert len(gateway.refund_calls) == 1


def test_rejected_refund_fails_and_staff_retry_uses_a_new_reference(
    user, shop, gateway, admin_client, django_capture_on_commit_callbacks
):
    order, _ = _paid_order(user, shop)
    gateway.refund_outcomes = [GatewayRejected("Payment already refunded")]
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    refund = Refund.objects.get()
    process_refund(refund.pk)
    refund.refresh_from_db()
    assert refund.status == "failed" and "already refunded" in refund.failure_reason
    first_reference = refund.provider_reference

    with django_capture_on_commit_callbacks(execute=True):
        res = admin_client.post(f"/api/payments/refunds/{refund.public_id}/retry/")
    assert res.status_code == 200
    refund.refresh_from_db()
    assert refund.status == "processed" and refund.provider_reference != first_reference
    assert refund.provider_reference.endswith("-2")
    assert admin_client.post(f"/api/payments/refunds/{refund.public_id}/retry/").status_code == 409


def test_pending_gateway_refund_is_synced_until_processed(user, shop, gateway):
    order, payment = _paid_order(user, shop)
    gateway.refund_outcomes = [RefundResult(True, "rfnd_slow", "pending")]
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    refund = Refund.objects.get()
    process_refund(refund.pk)
    gateway.fetch_refund_result = RefundResult(True, "rfnd_slow", "pending")
    assert refunds.sync_refund(refund.pk) == "pending"
    gateway.fetch_refund_result = RefundResult(True, "rfnd_slow", "processed")
    assert refunds.sync_refund(refund.pk) == "processed"
    payment.refresh_from_db()
    assert payment.status == "refunded"


def test_partial_return_refund_marks_partially_refunded(user, shop, gateway, staff_user):
    shop["store"].managers.add(staff_user)
    order, payment = _paid_order(user, shop, qty=2)
    for status in FULFIL:
        order = transition_order(order, status, actor=staff_user)
    item = order.items.get()
    ret = request_return(order, user=user, items=[{"order_item_id": item.id, "quantity": 1}], reason="damaged")
    approve_return(ret, actor=staff_user)
    ret = receive_return(ret, actor=staff_user)
    assert ret.refund_method == "original_payment"
    process_refund(ret.refund.pk)
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == "partially_refunded" and order.payment_status == "partially_refunded"
    assert gateway.refund_calls[0][1] == Decimal("70.00")


def test_refunds_can_never_exceed_the_payment(user, shop, gateway):
    _, payment = _paid_order(user, shop)
    create_refund(payment, payment.amount - Decimal("10"), reason="Part")
    with pytest.raises(RefundError) as exc:
        create_refund(payment, Decimal("10.01"), reason="Too much")
    assert exc.value.error_code == "refund_exceeds_payment"
    with pytest.raises(RefundError):
        create_refund(payment, Decimal("0"), reason="Zero")


# --- Cash on delivery ---------------------------------------------------------------------------


def test_cod_cash_is_collected_on_delivery(user, shop, staff_user):
    order, payment = _cod_delivered(user, shop, staff_user)
    assert payment.status == "captured" and payment.method == "cod" and payment.captured_at
    assert order.payment_status == "paid"


def test_cod_return_is_refunded_by_staff_with_a_reference(
    user, shop, staff_user, staff_client, auth_client, gateway, django_capture_on_commit_callbacks
):
    shop["store"].managers.add(staff_user)
    order, payment = _cod_delivered(user, shop, staff_user)
    item = order.items.get()
    ret = request_return(order, user=user, items=[{"order_item_id": item.id, "quantity": 2}], reason="defective")
    approve_return(ret, actor=staff_user)
    with django_capture_on_commit_callbacks(execute=True):
        ret = receive_return(ret, actor=staff_user)
    refund = ret.refund
    assert ret.refund_method == "manual" and refund.is_manual and refund.status == "pending"
    assert gateway.refund_calls == [] and not Job.objects.exclude(name="notifications.deliver").exists()  # no gateway

    listing = staff_client.get("/api/payments/refunds/?status=pending").json()
    assert listing["count"] == 1 and listing["results"][0]["is_manual"] is True
    url = f"/api/payments/refunds/{refund.public_id}/mark-processed/"
    assert auth_client.post(url, {"reference": "x"}, format="json").status_code == 403
    res = staff_client.post(url, {"reference": " "}, format="json")
    assert res.status_code == 400
    with django_capture_on_commit_callbacks(execute=True):
        res = staff_client.post(url, {"reference": "UPI 4102 9921"}, format="json")
    assert res.status_code == 200 and res.json()["status"] == "processed"
    refund.refresh_from_db()
    order.refresh_from_db()
    assert refund.manual_reference == "UPI 4102 9921" and refund.processed_by == staff_user
    assert refund.amount == Decimal("140.00") and payment.amount == Decimal("180.00")  # ₹40 delivery kept
    assert order.payment_status == "partially_refunded"
    assert Notification.objects.filter(event="refund.processed", body__contains="by the store").exists()
    assert staff_client.post(url, {"reference": "again"}, format="json").status_code == 409


def test_gateway_refund_in_flight_cannot_be_marked_manually(user, shop, gateway, admin_client):
    order, _ = _paid_order(user, shop)
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    refund = Refund.objects.get()
    res = admin_client.post(
        f"/api/payments/refunds/{refund.public_id}/mark-processed/", {"reference": "x"}, format="json"
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "refund_state_invalid"


def test_managers_see_only_their_stores_refunds(user, shop, gateway, staff_client, staff_user):
    order, _ = _paid_order(user, shop)
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    assert staff_client.get("/api/payments/refunds/").json()["count"] == 0
    shop["store"].managers.add(staff_user)
    assert staff_client.get("/api/payments/refunds/").json()["count"] == 1


def test_payment_status_label_not_changed_by_a_merely_requested_refund(user, shop, gateway):
    order, payment = _paid_order(user, shop)
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == Payment.Status.CAPTURED and order.payment_status == "paid"
