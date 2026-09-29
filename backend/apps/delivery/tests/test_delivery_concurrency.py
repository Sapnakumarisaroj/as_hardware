"""Phase 10: two people acting on the same delivery at the same moment (real threads, each with
its own database connection). Exactly one wins; the loser gets a clean refusal; stock, cash and
statuses stay consistent. See orders/tests/test_concurrency.py for how the threads are run."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.core.testing import create_product
from apps.delivery import workflow
from apps.delivery.assignment import reassign_shipment, unassign_shipment
from apps.delivery.cod import cash_in_hand
from apps.delivery.models import DeliveryAssignment, DeliveryPartner, DeliveryStatusHistory
from apps.inventory.models import Inventory, StockMovement
from apps.orders.models import Order, OrderStatusHistory
from apps.orders.services import cancel_order_by_customer, transition_order
from apps.orders.tests.test_concurrency import _error_codes, _ok, run_concurrently
from apps.payments.models import Payment

from .helpers import advance, assign, create_partner, delivery_code, packed_order, store_at

pytestmark = pytest.mark.django_db(transaction=True)
A = DeliveryAssignment.Status
CASH = {"collected": True, "amount": "1200.00", "method": "cash"}


def _user(email: str, **extra):
    return get_user_model().objects.create_user(email, "S3cure-pass!", full_name=email.split("@")[0], **extra)


@pytest.fixture
def scene():
    store = store_at(0, riders=0, zone=True)
    _, drill = create_product(name="Drill", price="600.00", stock=10, store=store)
    customer, admin = _user("buyer@example.com"), _user("boss@example.com", role="admin")
    rider = create_partner(store)
    order = packed_order(customer, (drill, 2), actor=admin)
    job = assign(order.shipments.get(), rider, actor=admin)
    return {"store": store, "drill": drill, "customer": customer, "admin": admin, "rider": rider, "job": job}


def levels(scene):
    inv = Inventory.objects.get(store=scene["store"], variant=scene["drill"])
    return inv.available_quantity, inv.reserved_quantity


def steps(job):
    return [h.to_status for h in DeliveryStatusHistory.objects.filter(assignment=job).order_by("id")]


def order_steps(job):
    return [h.to_status for h in OrderStatusHistory.objects.filter(order_id=job.order_id).order_by("id")]


def test_double_tap_on_accept_and_pickup(scene):
    job, rider = scene["job"], scene["rider"].user
    results = run_concurrently(*[lambda: workflow.accept(job.pk, rider=rider)] * 3)
    assert len(_ok(results)) == 1 and _error_codes(results) == ["invalid_delivery_state"] * 2

    results = run_concurrently(*[lambda: workflow.pickup(job.pk, rider=rider)] * 3)
    assert len(_ok(results)) == 1 and _error_codes(results) == ["invalid_delivery_state"] * 2
    assert steps(job) == ["assigned", "accepted", "picked_up"]
    assert levels(scene) == (8, 0)  # sold once
    assert StockMovement.objects.filter(movement_type="sale").count() == 1
    assert order_steps(job).count("picked_up") == 1


def test_double_tap_on_deliver_collects_the_cash_once(scene):
    job, rider = advance(scene["job"], "out_for_delivery"), scene["rider"].user
    code = delivery_code(job)
    results = run_concurrently(*[lambda: workflow.complete_delivery(job.pk, rider=rider, code=code, cod=CASH)] * 4)
    assert len(_ok(results)) == 1 and _error_codes(results) == ["invalid_delivery_state"] * 3
    job.refresh_from_db()
    assert job.status == A.DELIVERED and job.cod_collected_amount == Decimal("1200.00")
    assert cash_in_hand(scene["rider"]) == Decimal("1200.00")
    assert steps(job).count("delivered") == 1 and order_steps(job).count("delivered") == 1
    order = Order.objects.get(pk=job.order_id)
    assert order.status == "delivered" and order.payment_status == "paid"
    assert Payment.objects.filter(order=order, status="captured").count() == 1
    scene["rider"].refresh_from_db()
    assert scene["rider"].status == DeliveryPartner.Status.AVAILABLE


def test_deliver_racing_with_failed_delivery(scene):
    job, rider = advance(scene["job"], "out_for_delivery"), scene["rider"].user
    code = delivery_code(job)
    results = run_concurrently(
        lambda: workflow.complete_delivery(job.pk, rider=rider, code=code, cod=CASH),
        lambda: workflow.fail_delivery(job.pk, rider=rider, reason_code="customer_unavailable"),
    )
    assert len(_ok(results)) == 1 and _error_codes(results) == ["invalid_delivery_state"]
    job.refresh_from_db()
    order = Order.objects.get(pk=job.order_id)
    shipment = order.shipments.get()
    assert (job.status, shipment.status, order.status) in {
        ("delivered", "delivered", "delivered"),
        ("failed", "failed", "delivery_failed"),
    }
    # Cash is recorded only for the delivery that really happened.
    assert (job.cod_collected_at is not None) == (job.status == A.DELIVERED)
    assert (order.payment_status == "paid") == (job.status == A.DELIVERED)


def test_many_wrong_codes_at_once_never_exceed_the_limit(scene, settings):
    settings.DELIVERY_OTP_MAX_ATTEMPTS = 3
    job, rider = advance(scene["job"], "out_for_delivery"), scene["rider"].user
    code = delivery_code(job)
    wrong = str((int(code) + 7) % 1_000_000).zfill(6)
    results = run_concurrently(*[lambda: workflow.complete_delivery(job.pk, rider=rider, code=wrong, cod=CASH)] * 6)
    assert _ok(results) == []
    assert _error_codes(results) == ["otp_invalid"] * 2 + ["otp_locked"] * 4
    job.refresh_from_db()
    assert job.otp_attempts == 3 and job.status == A.OUT_FOR_DELIVERY and job.cod_collected_at is None
    with pytest.raises(Exception) as exc:  # noqa: PT011 — the right code comes too late
        workflow.complete_delivery(job.pk, rider=rider, code=code, cod=CASH)
    assert exc.value.error_code == "otp_locked"


def test_right_code_racing_with_a_new_code(scene):
    from datetime import timedelta

    from django.utils import timezone

    job, rider = advance(scene["job"], "out_for_delivery"), scene["rider"].user
    DeliveryAssignment.objects.filter(pk=job.pk).update(otp_issued_at=timezone.now() - timedelta(minutes=5))
    code, order, customer = delivery_code(job), scene["job"].order, scene["customer"]
    results = run_concurrently(
        lambda: workflow.complete_delivery(job.pk, rider=rider, code=code, cod=CASH),
        lambda: workflow.new_delivery_code(order, 1, user=customer),
    )
    job.refresh_from_db()
    codes = _error_codes(results)
    if job.status == A.DELIVERED:  # delivered first: no code is needed any more
        assert codes == ["otp_not_needed"]
    else:  # the new code came first: the old one no longer works
        assert codes == ["otp_invalid"] and job.otp_attempts == 1
        assert delivery_code(job) != code
        assert workflow.complete_delivery(job.pk, rider=rider, code=delivery_code(job), cod=CASH).status == A.DELIVERED


def test_accept_racing_with_reassignment(scene):
    job, rider, admin = scene["job"], scene["rider"].user, scene["admin"]
    second = create_partner(scene["store"], email="second@example.com")
    results = run_concurrently(
        lambda: workflow.accept(job.pk, rider=rider),
        lambda: reassign_shipment(job.shipment, second, actor=admin),
    )
    job.refresh_from_db()
    active = DeliveryAssignment.objects.filter(shipment=job.shipment, status__in=DeliveryAssignment.ACTIVE_STATUSES)
    assert active.count() == 1  # never two riders for one shipment
    if len(_ok(results)) == 2:  # accepted first, then taken away
        assert job.status == A.CANCELLED and active.get().partner == second
    else:  # reassigned first: the old rider's accept is refused
        assert _error_codes(results) == ["invalid_delivery_state"] and active.get().partner == second


def test_pickup_racing_with_unassign_and_cancel(scene):
    job, rider, admin, customer = scene["job"], scene["rider"].user, scene["admin"], scene["customer"]
    workflow.accept(job.pk, rider=rider)
    results = run_concurrently(
        lambda: workflow.pickup(job.pk, rider=rider),
        lambda: unassign_shipment(job.shipment, actor=admin),
        lambda: transition_order(job.order, "cancelled", actor=admin, note="Customer called"),
    )
    job.refresh_from_db()
    order = Order.objects.get(pk=job.order_id)
    shipment = order.shipments.get()
    assert len(_ok(results)) >= 1
    if job.status == A.PICKED_UP:  # the rider got the goods: nobody may take them away or cancel
        # The order is "picked up" by then, from where the state machine has no way to "cancelled".
        assert _error_codes(results) == ["already_picked_up", "invalid_transition"]
        assert (order.status, shipment.status, shipment.stock_state) == ("picked_up", "picked_up", "sold")
        assert levels(scene) == (8, 0)
    else:
        assert job.status == A.CANCELLED and "invalid_delivery_state" in _error_codes(results)
        assert shipment.stock_state in ("reserved", "released")
        assert levels(scene) == ((10, 0) if order.status == "cancelled" else (8, 2))
    assert StockMovement.objects.filter(movement_type="sale").count() == (1 if job.status == A.PICKED_UP else 0)
    del customer


def test_customer_cancel_racing_with_pickup(scene):
    """Cancelling is only possible before packing, so here the order is forced back to
    "processing" with a rider already assigned (riders can be assigned while packing)."""
    job, rider, customer = scene["job"], scene["rider"].user, scene["customer"]
    workflow.accept(job.pk, rider=rider)
    Order.objects.filter(pk=job.order_id).update(status="processing")
    results = run_concurrently(
        lambda: cancel_order_by_customer(job.order, user=customer, reason="Changed my mind"),
        lambda: workflow.pickup(job.pk, rider=rider),
    )
    job.refresh_from_db()
    order = Order.objects.get(pk=job.order_id)
    # Whatever the order of arrival, the goods don't leave for a cancelled order.
    assert order.status == "cancelled" and job.status == A.CANCELLED
    assert set(_error_codes(results)) <= {"order_not_packed", "invalid_delivery_state"}
    assert levels(scene) == (10, 0) and not StockMovement.objects.filter(movement_type="sale").exists()


def test_cash_handover_recorded_once(scene):
    job, admin = advance(scene["job"], "out_for_delivery"), scene["admin"]
    workflow.complete_delivery(job.pk, rider=scene["rider"].user, code=delivery_code(job), cod=CASH)
    clerk = _user("clerk@example.com", role="store_manager")
    results = run_concurrently(
        lambda: workflow.hand_over_cash(job.pk, actor=admin),
        lambda: workflow.hand_over_cash(job.pk, actor=clerk),
        lambda: workflow.hand_over_cash(job.pk, actor=admin),
    )
    assert len(_ok(results)) == 1 and _error_codes(results) == ["cod_already_handed_over"] * 2
    assert cash_in_hand(scene["rider"]) == Decimal("0.00")


def test_two_shipments_of_one_order_delivered_at_the_same_time():
    a, b = store_at(0, riders=0, zone=True), store_at(1, riders=0, zone=True)
    _, drill = create_product(name="Drill", price="600.00", stock=5, store=a)
    _, tape = create_product(name="Tape", price="50.00", stock=5, store=b)
    customer, admin = _user("buyer@example.com"), _user("boss@example.com", role="admin")
    order = packed_order(customer, (drill, 1), (tape, 2), km_north=0.5, actor=admin)
    jobs = []
    for index, shipment in enumerate(order.shipments.order_by("sequence")):
        job = assign(shipment, create_partner(shipment.store, email=f"r{index}@example.com"), actor=admin)
        jobs.append(advance(job, "out_for_delivery"))
    codes = [delivery_code(job) for job in jobs]

    def deliver(job, code):
        cod = {"collected": True, "amount": job.cod_amount_due, "method": "cash"}
        return lambda: workflow.complete_delivery(job.pk, rider=job.partner.user, code=code, cod=cod)

    results = run_concurrently(*[deliver(job, code) for job, code in zip(jobs, codes, strict=True)])
    assert len(_ok(results)) == 2
    order.refresh_from_db()
    assert order.status == "delivered" and order.payment_status == "paid" and order.delivered_at
    assert [s.status for s in order.shipments.all()] == ["delivered", "delivered"]
    history = [h.to_status for h in order.status_history.all()]
    assert history.count("delivered") == 1 and history[-1] == "delivered"
    assert Payment.objects.filter(order=order, status="captured").count() == 1
    collected = sum(DeliveryAssignment.objects.filter(order=order).values_list("cod_collected_amount", flat=True))
    assert collected == order.grand_total


def test_going_offline_racing_with_an_assignment():
    """A rider can't end up offline while holding a fresh job."""
    from rest_framework.test import APIClient

    store = store_at(0, riders=0, zone=True)
    _, drill = create_product(name="Drill", stock=5, store=store)
    customer, admin = _user("buyer@example.com"), _user("boss@example.com", role="admin")
    rider = create_partner(store)
    shipment = packed_order(customer, (drill, 1), actor=admin).shipments.get()

    def go_offline():
        client = APIClient()
        client.force_authenticate(get_user_model().objects.get(pk=rider.user_id))
        res = client.patch("/api/delivery/me/", {"status": "offline"}, format="json")
        if res.status_code != 200:
            raise AssertionError(res.json()["error"]["code"])
        return res

    results = run_concurrently(lambda: assign(shipment, rider, actor=admin), go_offline)
    rider.refresh_from_db()
    has_job = DeliveryAssignment.objects.filter(partner=rider, status__in=DeliveryAssignment.ACTIVE_STATUSES).exists()
    assert len(_ok(results)) == 1
    assert (rider.status, has_job) in {("offline", False), ("busy", True)}
