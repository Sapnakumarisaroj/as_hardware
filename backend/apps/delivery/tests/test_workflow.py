"""Phase 10: the delivery partner workflow (apps/delivery/workflow.py) and what it does to
shipments, orders and stock."""

from decimal import Decimal

import pytest

from apps.core.exceptions import ServiceError
from apps.core.models import AuditLog
from apps.core.testing import create_product
from apps.delivery import workflow
from apps.delivery.assignment import reassign_shipment, unassign_shipment
from apps.delivery.models import DeliveryAssignment, DeliveryPartner
from apps.inventory.models import Inventory, StockMovement
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderStatus
from apps.orders.services import cancel_order_by_customer, transition_order
from apps.payments.models import Payment

from .helpers import advance, assign, create_partner, deliver_job, packed_order, store_at, zone_for

pytestmark = pytest.mark.django_db
A = DeliveryAssignment.Status


def levels(store, variant):
    inv = Inventory.objects.get(store=store, variant=variant)
    return inv.available_quantity, inv.reserved_quantity


def statuses(order):
    order.refresh_from_db()
    return order.status, [s.status for s in order.shipments.order_by("sequence")]


def history(order):
    return [h.to_status for h in order.status_history.all()]


def code_of(exc) -> str:
    return exc.value.error_code


@pytest.fixture
def shop():
    store = store_at(0, riders=0)
    zone_for(store)
    _, drill = create_product(name="Drill", price="600.00", mrp="700.00", stock=10, store=store)
    return {"store": store, "drill": drill, "rider": create_partner(store)}


@pytest.fixture
def job(user, shop, admin_user):
    order = packed_order(user, (shop["drill"], 2), actor=admin_user)
    return assign(order.shipments.get(), shop["rider"], actor=admin_user)


# --- The whole delivery --------------------------------------------------------------------------


def test_a_delivery_from_assignment_to_the_door(user, shop, job, django_capture_on_commit_callbacks):
    rider, order, store = shop["rider"].user, job.order, shop["store"]
    assert statuses(order) == ("assigned", ["assigned"]) and levels(store, shop["drill"]) == (8, 2)

    workflow.accept(job.pk, rider=rider)
    assert statuses(order) == ("assigned", ["assigned"])

    workflow.pickup(job.pk, rider=rider, position=(Decimal("18.5074"), Decimal("73.8077")))
    assert statuses(order) == ("picked_up", ["picked_up"])
    assert levels(store, shop["drill"]) == (8, 0)  # the reservation became a sale
    assert StockMovement.objects.filter(movement_type="sale", reference_id=order.order_number).count() == 1

    with django_capture_on_commit_callbacks(execute=True):
        workflow.start_delivery(job.pk, rider=rider)
    assert statuses(order) == ("out_for_delivery", ["out_for_delivery"])
    note = Notification.objects.filter(user=user, event="order.out_for_delivery", channel="in_app").get()
    assert "delivery code" in note.body and not any(ch.isdigit() for ch in note.body.split("code")[1][:40])

    with django_capture_on_commit_callbacks(execute=True):
        done = deliver_job(job, received_by="Asha (neighbour)", notes="Left with the neighbour as asked")
    assert done.status == A.DELIVERED and done.received_by == "Asha (neighbour)"
    assert done.otp_verified_at and not done.completed_without_otp
    assert done.earning_amount == Decimal("41.20")  # 25 + 6 × 2.70 km
    assert statuses(order) == ("delivered", ["delivered"])
    order.refresh_from_db()
    shipment = order.shipments.get()
    assert order.delivered_at and shipment.delivered_at and shipment.delivery_attempts == 1
    assert levels(store, shop["drill"]) == (8, 0)
    assert history(order)[-5:] == ["packed", "assigned", "picked_up", "out_for_delivery", "delivered"]
    assert Notification.objects.filter(user=user, event="order.delivered").exists()

    steps = [(h.from_status, h.to_status) for h in done.status_history.all()]
    assert steps == [
        ("", "assigned"),
        ("assigned", "accepted"),
        ("accepted", "picked_up"),
        ("picked_up", "out_for_delivery"),
        ("out_for_delivery", "delivered"),
    ]
    pickup_row = done.status_history.get(to_status="picked_up")
    assert pickup_row.latitude == Decimal("18.507400") and pickup_row.changed_by == rider
    shop["rider"].refresh_from_db()
    assert shop["rider"].status == DeliveryPartner.Status.AVAILABLE


def test_rider_is_notified_of_a_new_job(shop, user, admin_user, django_capture_on_commit_callbacks):
    order = packed_order(user, (shop["drill"], 1), actor=admin_user)
    with django_capture_on_commit_callbacks(execute=True):
        job = assign(order.shipments.get(), shop["rider"], actor=admin_user)
    note = Notification.objects.get(user=shop["rider"].user, event="delivery.assigned")
    assert order.order_number in note.title and note.data["assignment_id"] == job.pk


# --- Invalid status changes ----------------------------------------------------------------------

ACTIONS = {
    "accept": lambda job, rider: workflow.accept(job.pk, rider=rider),
    "reject": lambda job, rider: workflow.reject(job.pk, rider=rider, reason="Flat tyre"),
    "pickup": lambda job, rider: workflow.pickup(job.pk, rider=rider),
    "start": lambda job, rider: workflow.start_delivery(job.pk, rider=rider),
    "complete": lambda job, rider: deliver_job(job),
    "fail": lambda job, rider: workflow.fail_delivery(job.pk, rider=rider, reason_code="customer_unavailable"),
    "notes": lambda job, rider: workflow.update_notes(job.pk, rider=rider, notes="Gate 2"),
}
# status → actions that are allowed from it
ALLOWED = {
    "assigned": {"accept", "reject", "notes"},
    "accepted": {"reject", "pickup", "notes"},
    "picked_up": {"start", "fail", "notes"},
    "out_for_delivery": {"complete", "fail", "notes"},
    "delivered": set(),
    "failed": set(),
    "rejected": set(),
    "cancelled": set(),
}


def _job_in(job, status: str, admin_user):
    rider = job.partner.user
    if status in ("accepted", "picked_up", "out_for_delivery"):
        return advance(job, status)
    if status == "delivered":
        advance(job, "out_for_delivery")
        return deliver_job(job)
    if status == "failed":
        advance(job, "picked_up")
        return workflow.fail_delivery(job.pk, rider=rider, reason_code="wrong_address")
    if status == "rejected":
        return workflow.reject(job.pk, rider=rider, reason="Sick")
    if status == "cancelled":
        unassign_shipment(job.shipment, actor=admin_user)
    job.refresh_from_db()
    return job


@pytest.mark.parametrize(("status", "action"), [(status, action) for status in ALLOWED for action in ACTIONS])
def test_every_action_from_every_status(job, admin_user, status, action):
    job = _job_in(job, status, admin_user)
    assert job.status == status
    rider = job.partner.user
    before = (job.status, job.order.status, job.status_history.count())
    if action in ALLOWED[status]:
        ACTIONS[action](job, rider)
        return
    with pytest.raises(ServiceError) as exc:
        ACTIONS[action](job, rider)
    assert code_of(exc) in ("invalid_delivery_state", "otp_not_issued", "otp_used") and exc.value.status_code in (
        400,
        409,
    )
    job.refresh_from_db()
    job.order.refresh_from_db()
    assert (job.status, job.order.status, job.status_history.count()) == before


def test_pickup_needs_a_packed_order(user, shop, admin_user):
    from apps.carts.services import add_item
    from apps.orders.services import place_order

    from .helpers import address_at

    add_item(user, shop["drill"].id, 1)
    order, _ = place_order(user=user, address_id=address_at(user, 2).id, payment_method="cod")
    job = assign(order.shipments.get(), shop["rider"], actor=admin_user)
    workflow.accept(job.pk, rider=job.partner.user)
    with pytest.raises(ServiceError) as exc:
        workflow.pickup(job.pk, rider=job.partner.user)
    assert code_of(exc) == "order_not_packed" and exc.value.details == {"order_status": "confirmed"}
    assert levels(shop["store"], shop["drill"]) == (9, 1)

    for status in ("processing", "packed"):
        order = transition_order(order, status, actor=admin_user)
    assert order.status == OrderStatus.ASSIGNED  # the rider was already assigned while packing
    workflow.pickup(job.pk, rider=job.partner.user)
    assert statuses(order) == ("picked_up", ["picked_up"])


def test_another_riders_job_is_not_found(job, shop):
    other = create_partner(shop["store"], email="other@example.com").user
    for action in ACTIONS.values():
        with pytest.raises(ServiceError) as exc:
            action(job, other) if action is not ACTIONS["complete"] else workflow.complete_delivery(
                job.pk, rider=other, code="123456"
            )
        assert code_of(exc) == "not_found" and exc.value.status_code == 404
    job.refresh_from_db()
    assert job.status == A.ASSIGNED and job.status_history.count() == 1


def test_a_deactivated_rider_cannot_continue(job):
    DeliveryPartner.objects.filter(pk=job.partner_id).update(is_active=False)
    with pytest.raises(ServiceError) as exc:
        workflow.accept(job.pk, rider=job.partner.user)
    assert code_of(exc) == "partner_inactive"


def test_reasons_are_required(job):
    rider = job.partner.user
    with pytest.raises(ServiceError) as exc:
        workflow.reject(job.pk, rider=rider, reason="  ")
    assert code_of(exc) == "reason_required"
    advance(job, "picked_up")
    with pytest.raises(ServiceError) as exc:
        workflow.fail_delivery(job.pk, rider=rider, reason_code="not-a-reason")
    assert code_of(exc) == "reason_required"
    with pytest.raises(ServiceError) as exc:
        workflow.fail_delivery(job.pk, rider=rider, reason_code="other", note="")
    assert code_of(exc) == "note_required"
    job.refresh_from_db()
    assert job.status == A.PICKED_UP


# --- Reject, reassign, unassign ------------------------------------------------------------------


def test_rejected_job_goes_back_to_the_waiting_list(job, shop, admin_user):
    rider = job.partner.user
    workflow.accept(job.pk, rider=rider)
    rejected = workflow.reject(job.pk, rider=rider, reason="Flat tyre")
    assert rejected.status == A.REJECTED and rejected.reject_reason == "Flat tyre" and rejected.rejected_at
    assert statuses(job.order) == ("packed", ["pending"])
    assert levels(shop["store"], shop["drill"]) == (8, 2)
    shop["rider"].refresh_from_db()
    assert shop["rider"].status == DeliveryPartner.Status.AVAILABLE
    assert AuditLog.objects.filter(action="delivery.reject").count() == 1

    again = assign(job.shipment, create_partner(shop["store"], email="b@example.com"), actor=admin_user)
    assert again.pk != job.pk and statuses(job.order) == ("assigned", ["assigned"])
    assert history(job.order)[-3:] == ["assigned", "packed", "assigned"]


def test_reassign_before_pickup(job, shop, admin_user):
    second = create_partner(shop["store"], email="second@example.com")
    new = reassign_shipment(job.shipment, second, actor=admin_user, reason="Closer to the store")
    job.refresh_from_db()
    assert job.status == A.CANCELLED and new.partner == second and new.status == A.ASSIGNED
    assert new.cod_amount_due == job.cod_amount_due == Decimal("1200.00")
    assert "Closer to the store" in job.status_history.last().note
    assert statuses(job.order) == ("assigned", ["assigned"])
    shop["rider"].refresh_from_db()
    second.refresh_from_db()
    assert (shop["rider"].status, second.status) == ("available", "busy")
    assert AuditLog.objects.filter(action="delivery.reassign").count() == 1

    with pytest.raises(ServiceError) as exc:
        reassign_shipment(job.shipment, second, actor=admin_user)
    assert code_of(exc) == "same_partner"
    with pytest.raises(ServiceError) as exc:
        reassign_shipment(job.shipment, create_partner(shop["store"], email="off@example.com", status="offline"),
                          actor=admin_user)  # fmt: skip
    assert code_of(exc) == "partner_unavailable"
    with pytest.raises(ServiceError) as exc:
        workflow.accept(job.pk, rider=job.partner.user)  # the old rider's job is gone
    assert code_of(exc) == "invalid_delivery_state"


def test_goods_never_change_hands_silently(job, shop, admin_user):
    advance(job, "picked_up")
    second = create_partner(shop["store"], email="second@example.com")
    for call in (
        lambda: reassign_shipment(job.shipment, second, actor=admin_user),
        lambda: unassign_shipment(job.shipment, actor=admin_user),
    ):
        with pytest.raises(ServiceError) as exc:
            call()
        assert code_of(exc) == "already_picked_up"
    job.refresh_from_db()
    assert job.status == A.PICKED_UP and DeliveryAssignment.objects.count() == 1


def test_unassign_and_nothing_to_unassign(job, shop, admin_user):
    unassign_shipment(job.shipment, actor=admin_user, reason="Customer asked for later")
    assert statuses(job.order) == ("packed", ["pending"])
    with pytest.raises(ServiceError) as exc:
        unassign_shipment(job.shipment, actor=admin_user)
    assert code_of(exc) == "not_assigned"


def test_staff_cannot_move_an_order_a_rider_is_handling(job, admin_user):
    for target in ("picked_up", "delivery_failed"):
        with pytest.raises(ServiceError) as exc:
            transition_order(job.order, target, actor=admin_user)
        assert code_of(exc) == "rider_in_charge"
    assert statuses(job.order) == ("assigned", ["assigned"])
    # Unassigning through the order still works and frees the rider.
    transition_order(job.order, "packed", actor=admin_user)
    job.refresh_from_db()
    assert job.status == A.CANCELLED and statuses(job.order) == ("packed", ["pending"])


def test_stores_with_their_own_riders_still_use_the_order_steps(user, shop, admin_user):
    order = packed_order(user, (shop["drill"], 2), actor=admin_user)
    for target in ("assigned", "picked_up", "out_for_delivery", "delivered"):
        order = transition_order(order, target, actor=admin_user)
        assert statuses(order) == (target, [target])
    shipment = order.shipments.get()
    assert shipment.stock_state == "sold" and shipment.delivered_at and shipment.delivery_attempts == 1
    assert levels(shop["store"], shop["drill"]) == (8, 0)
    assert order.payment_status == "paid" and not DeliveryAssignment.objects.exists()


# --- Cancelling ----------------------------------------------------------------------------------


def test_customer_cancel_frees_the_rider_before_pickup_only(user, shop, admin_user):
    from apps.carts.services import add_item
    from apps.orders.services import place_order

    from .helpers import address_at

    add_item(user, shop["drill"].id, 1)
    order, _ = place_order(user=user, address_id=address_at(user, 2).id, payment_method="cod")
    job = assign(order.shipments.get(), shop["rider"], actor=admin_user)
    workflow.accept(job.pk, rider=job.partner.user)
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    job.refresh_from_db()
    assert job.status == A.CANCELLED and statuses(order) == ("cancelled", ["cancelled"])
    assert order.shipments.get().stock_state == "released" and levels(shop["store"], shop["drill"]) == (10, 0)


def test_order_with_goods_on_the_way_cannot_be_cancelled(job, admin_user, shop):
    advance(job, "picked_up")
    Order.objects.filter(pk=job.order_id).update(status="assigned")  # as for a split order
    with pytest.raises(ServiceError) as exc:
        transition_order(job.order, "cancelled", actor=admin_user)
    assert code_of(exc) == "shipment_on_the_way"
    assert levels(shop["store"], shop["drill"]) == (8, 0)


# --- Failed delivery -----------------------------------------------------------------------------


def test_failed_delivery_then_a_second_attempt(user, shop, job, admin_user, django_capture_on_commit_callbacks):
    rider, order = job.partner.user, job.order
    advance(job, "out_for_delivery")
    with django_capture_on_commit_callbacks(execute=True):
        failed = workflow.fail_delivery(job.pk, rider=rider, reason_code="customer_unavailable", note="Door locked")
    assert failed.status == A.FAILED and failed.failure_code == "customer_unavailable"
    assert failed.failure_reason == "Customer not available: Door locked" and failed.failed_at
    assert failed.otp_nonce == "" and failed.earning_amount == Decimal("0.00")
    assert statuses(order) == ("delivery_failed", ["failed"])
    shipment = order.shipments.get()
    assert (shipment.failure_reason, shipment.failure_note, shipment.stock_state) == (
        "customer_unavailable",
        "Door locked",
        "sold",
    )
    assert levels(shop["store"], shop["drill"]) == (8, 0)  # the goods are back but still this order's
    assert order.payment_status == "pending" and Payment.objects.get(order=order).status == "pending"
    body = Notification.objects.filter(user=user, event="delivery.failed", channel="in_app").get().body
    assert "customer not available" in body
    shop["rider"].refresh_from_db()
    assert shop["rider"].status == "available"

    second = assign(shipment, create_partner(shop["store"], email="second@example.com"), actor=admin_user)
    assert second.status_history.first().note == "Sent out again"
    assert statuses(order) == ("assigned", ["assigned"])
    advance(second, "out_for_delivery")
    assert levels(shop["store"], shop["drill"]) == (8, 0)  # sold once, not twice
    deliver_job(second)
    assert statuses(order) == ("delivered", ["delivered"])
    shipment.refresh_from_db()
    assert shipment.delivery_attempts == 2
    assert history(order)[-6:] == [
        "out_for_delivery", "delivery_failed", "assigned", "picked_up", "out_for_delivery", "delivered",
    ]  # fmt: skip
    assert StockMovement.objects.filter(movement_type="sale").count() == 1


def test_cancelling_after_a_failed_delivery_restocks_and_refunds(user, shop, admin_user):
    order = packed_order(user, (shop["drill"], 2), method="online", actor=admin_user)
    job = assign(order.shipments.get(), shop["rider"], actor=admin_user)
    assert job.cod_amount_due == Decimal("0.00")
    advance(job, "picked_up")
    workflow.fail_delivery(job.pk, rider=job.partner.user, reason_code="customer_refused")
    assert levels(shop["store"], shop["drill"]) == (8, 0)

    transition_order(order, "cancelled", actor=admin_user, note="Customer refused the goods")
    assert statuses(order) == ("cancelled", ["cancelled"])
    assert order.shipments.get().stock_state == "restocked"
    assert levels(shop["store"], shop["drill"]) == (10, 0)
    assert StockMovement.objects.filter(movement_type="return", reference_id=order.order_number).count() == 1
    payment = Payment.objects.get(order=order)
    assert payment.refunds.get().amount == order.grand_total


# --- Orders from several stores ------------------------------------------------------------------


@pytest.fixture
def split(user, admin_user):
    a, b = store_at(0, riders=0), store_at(1, riders=0)
    zone_for(a, radius="10")
    zone_for(b, radius="10")
    _, drill = create_product(name="Drill", price="600.00", stock=5, store=a)
    _, tape = create_product(name="Tape", price="50.00", stock=5, store=b)
    order = packed_order(user, (drill, 1), (tape, 2), km_north=0.5, actor=admin_user)
    first, second = order.shipments.order_by("sequence")
    riders = {
        first.pk: create_partner(first.store, email="a@example.com"),
        second.pk: create_partner(second.store, email="b@example.com"),
    }
    return {
        "order": order, "first": first, "second": second, "riders": riders, "drill": drill, "tape": tape,
        "by_store": {a.pk: drill, b.pk: tape},
    }  # fmt: skip


def test_the_order_follows_its_least_advanced_shipment(split, admin_user, user, django_capture_on_commit_callbacks):
    order, first, second = split["order"], split["first"], split["second"]
    one = assign(first, split["riders"][first.pk], actor=admin_user)
    assert statuses(order) == ("packed", ["assigned", "pending"])
    advance(one, "out_for_delivery")
    assert statuses(order) == ("packed", ["out_for_delivery", "pending"])  # the other part still waits

    two = assign(second, split["riders"][second.pk], actor=admin_user)
    assert statuses(order) == ("assigned", ["out_for_delivery", "assigned"])
    with django_capture_on_commit_callbacks(execute=True):
        deliver_job(one)
    assert statuses(order) == ("assigned", ["delivered", "assigned"])
    assert Notification.objects.filter(user=user, event="order.part_delivered").exists()
    order.refresh_from_db()
    assert order.delivered_at is None and order.payment_status == "pending"

    advance(two, "picked_up")
    assert statuses(order) == ("picked_up", ["delivered", "picked_up"])
    advance(two, "out_for_delivery")
    with django_capture_on_commit_callbacks(execute=True):
        deliver_job(two)
    assert statuses(order) == ("delivered", ["delivered", "delivered"])
    order.refresh_from_db()
    assert order.delivered_at and order.payment_status == "paid"
    assert Notification.objects.filter(user=user, event="order.delivered").exists()
    assert history(order)[-4:] == ["assigned", "picked_up", "out_for_delivery", "delivered"]


def test_each_shipment_sells_its_own_stock(split, admin_user):
    first, second = split["first"], split["second"]
    one = assign(first, split["riders"][first.pk], actor=admin_user)
    advance(one, "picked_up")
    mine, theirs = split["by_store"][first.store_id], split["by_store"][second.store_id]
    assert levels(first.store, mine)[1] == 0 and levels(second.store, theirs)[1] > 0
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.stock_state, second.stock_state) == ("sold", "reserved")


def test_one_failed_shipment_marks_the_order(split, admin_user):
    order, first, second = split["order"], split["first"], split["second"]
    one = assign(first, split["riders"][first.pk], actor=admin_user)
    two = assign(second, split["riders"][second.pk], actor=admin_user)
    advance(one, "picked_up")
    workflow.fail_delivery(one.pk, rider=one.partner.user, reason_code="vehicle_problem")
    assert statuses(order) == ("delivery_failed", ["failed", "assigned"])
    advance(two, "out_for_delivery")  # the other rider carries on
    deliver_job(two)
    assert statuses(order) == ("delivery_failed", ["failed", "delivered"])
    with pytest.raises(ServiceError) as exc:  # part of it was delivered
        transition_order(order, "cancelled", actor=admin_user)
    assert code_of(exc) == "shipment_on_the_way"

    again = assign(first, create_partner(first.store, email="c@example.com"), actor=admin_user)
    assert statuses(order) == ("assigned", ["assigned", "delivered"])
    advance(again, "out_for_delivery")
    deliver_job(again)
    assert statuses(order) == ("delivered", ["delivered", "delivered"])


# --- Notes and closing without the code ----------------------------------------------------------


def test_notes(job):
    rider = job.partner.user
    assert workflow.update_notes(job.pk, rider=rider, notes="  Ring twice  ").delivery_notes == "Ring twice"
    assert len(workflow.update_notes(job.pk, rider=rider, notes="x" * 900).delivery_notes) == 500


def test_staff_can_close_a_delivery_without_the_code(job, admin_user):
    advance(job, "out_for_delivery")
    with pytest.raises(ServiceError) as exc:
        workflow.complete_without_otp(job.pk, actor=admin_user, note=" ")
    assert code_of(exc) == "note_required"
    with pytest.raises(ServiceError) as exc:
        workflow.complete_without_otp(job.pk, actor=admin_user, note="Customer's phone was dead")
    assert code_of(exc) == "cod_not_collected"

    done = workflow.complete_without_otp(
        job.pk,
        actor=admin_user,
        note="Customer's phone was dead",
        cod={"collected": True, "amount": "1200.00", "method": "cash"},
    )
    assert done.status == A.DELIVERED and done.completed_without_otp and done.otp_verified_at is None
    assert done.status_history.last().changed_by == admin_user
    assert statuses(job.order) == ("delivered", ["delivered"])
    log = AuditLog.objects.get(action="delivery.complete_without_otp")
    assert log.actor == admin_user and log.changes["note"] == "Customer's phone was dead"
