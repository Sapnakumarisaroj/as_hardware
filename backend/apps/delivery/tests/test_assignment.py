"""Phase 9: who may carry a shipment, and the safety rules of assigning one
(apps/delivery/assignment.py). The rider's own workflow is Phase 10."""

from decimal import Decimal

import pytest

from apps.carts.services import add_item
from apps.core.models import AuditLog
from apps.core.testing import create_product
from apps.delivery.assignment import assign_shipment, eligible_partners
from apps.delivery.eta import store_capacity
from apps.delivery.models import DeliveryAssignment, DeliveryPartner
from apps.orders.models import OrderStatus
from apps.orders.services import cancel_order_by_customer, place_order, transition_order
from apps.orders.tests.test_concurrency import _customers, _error_codes, _ok, run_concurrently

from .helpers import KM, STORE_LAT, STORE_LNG, address_at, create_partner, store_at, zone_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop():
    store = store_at(0, riders=0)
    zone_for(store)
    _, variant = create_product(stock=20, store=store)
    return {"store": store, "variant": variant}


def _shipment(user, shop, quantity=1):
    add_item(user, shop["variant"].id, quantity)
    order, _ = place_order(user=user, address_id=address_at(user, 2).id, payment_method="cod")
    return order.shipments.get()


def _codes(candidates):
    return [c.partner.user.email for c in candidates]


# --- Eligibility ---------------------------------------------------------------------------------


def test_only_available_verified_active_partners_with_capacity_are_eligible(user, shop):
    store = shop["store"]
    create_partner(store, email="ok@example.com")
    create_partner(store, email="offline@example.com", status="offline")
    create_partner(store, email="busy@example.com", status="busy")
    create_partner(store, email="unverified@example.com", is_verified=False)
    create_partner(store, email="inactive@example.com", is_active=False)
    assert _codes(eligible_partners(_shipment(user, shop))) == ["ok@example.com"]


def test_partners_of_other_stores_must_be_near_the_pickup_store(user, shop, settings):
    settings.DELIVERY_PARTNER_PICKUP_RADIUS_KM = 3.0
    other = store_at(8)
    create_partner(other, email="near@example.com", current_latitude=STORE_LAT + KM * 2, current_longitude=STORE_LNG)
    create_partner(other, email="far@example.com", current_latitude=STORE_LAT + KM * 6, current_longitude=STORE_LNG)
    create_partner(other, email="nowhere@example.com")  # no known position
    create_partner(None, email="freelance@example.com", current_latitude=STORE_LAT, current_longitude=STORE_LNG)
    home = create_partner(shop["store"], email="home@example.com")
    ranked = eligible_partners(_shipment(user, shop))
    # Own store first, then by workload, then by distance to the store.
    assert _codes(ranked) == ["home@example.com", "freelance@example.com", "near@example.com"]
    assert ranked[0].same_store and ranked[0].partner == home
    assert ranked[2].distance_km == pytest.approx(2.0, abs=0.05)


def test_workload_ranks_and_limits_partners(user, shop, other_user):
    store = shop["store"]
    loaded = create_partner(store, email="loaded@example.com", max_active_assignments=2)
    create_partner(store, email="idle@example.com", max_active_assignments=2)
    first = _shipment(user, shop)
    assign_shipment(first, loaded, actor=None)
    second = _shipment(other_user, shop)
    ranked = eligible_partners(second)
    assert _codes(ranked) == ["idle@example.com", "loaded@example.com"]
    assert [c.active_assignments for c in ranked] == [0, 1]
    assign_shipment(second, loaded, actor=None)
    loaded.refresh_from_db()
    assert loaded.status == DeliveryPartner.Status.BUSY  # at capacity → no longer offered
    third = _shipment(_customers(1)[0], shop)
    assert _codes(eligible_partners(third)) == ["idle@example.com"]


def test_available_riders_feed_the_eta(user, shop):
    store = shop["store"]
    assert store_capacity(store).available_riders == 0
    partner = create_partner(store)
    assert store_capacity(store).available_riders == 1
    assign_shipment(_shipment(user, shop), partner, actor=None)
    capacity = store_capacity(store)
    assert (capacity.available_riders, capacity.riders_on_shift, capacity.queue) == (0, 1, 0)


# --- Assigning -----------------------------------------------------------------------------------


def test_assign_records_the_assignment(user, shop, admin_user):
    partner = create_partner(shop["store"])
    shipment = _shipment(user, shop)
    assignment = assign_shipment(shipment, partner, actor=admin_user)
    assert assignment.status == "assigned" and assignment.shipment == shipment and assignment.order == shipment.order
    assert assignment.distance_km == Decimal("2.70")
    assert [h.to_status for h in assignment.status_history.all()] == ["assigned"]
    shipment.order.refresh_from_db()
    assert shipment.order.status == OrderStatus.CONFIRMED  # not packed yet
    assert AuditLog.objects.filter(action="delivery.assign").count() == 1


def test_packed_order_moves_to_assigned_once_every_shipment_has_a_rider(user, admin_user):
    a, b = store_at(0, riders=0), store_at(1, riders=0)
    zone_for(a)
    zone_for(b)
    _, drill = create_product(name="Drill", stock=5, store=a)
    _, tape = create_product(name="Tape", stock=5, store=b)
    add_item(user, drill.id, 1)
    add_item(user, tape.id, 1)
    order, _ = place_order(user=user, address_id=address_at(user, 0.5).id, payment_method="cod")
    for status in ("processing", "packed"):
        order = transition_order(order, status, actor=admin_user)
    first, second = order.shipments.order_by("sequence")
    assign_shipment(first, create_partner(first.store, email="a@example.com"), actor=admin_user)
    order.refresh_from_db()
    assert order.status == OrderStatus.PACKED
    assign_shipment(second, create_partner(second.store, email="b@example.com"), actor=admin_user)
    order.refresh_from_db()
    assert order.status == OrderStatus.ASSIGNED


def test_duplicate_assignment_is_refused(user, shop):
    first, second = (
        create_partner(shop["store"], email="a@example.com"),
        create_partner(shop["store"], email="b@example.com"),
    )
    shipment = _shipment(user, shop)
    assign_shipment(shipment, first, actor=None)
    with pytest.raises(Exception) as exc:  # noqa: PT011 — the code is what matters
        assign_shipment(shipment, second, actor=None)
    assert exc.value.error_code == "already_assigned"
    assert DeliveryAssignment.objects.count() == 1


@pytest.mark.parametrize("state", ["pending", "cancelled", "picked_up", "out_for_delivery", "delivered"])
def test_invalid_delivery_states_cannot_be_assigned(user, shop, admin_user, state):
    from apps.orders.models import Order

    partner = create_partner(shop["store"])
    shipment = _shipment(user, shop)
    Order.objects.filter(pk=shipment.order_id).update(status=state)
    with pytest.raises(Exception) as exc:  # noqa: PT011
        assign_shipment(shipment, partner, actor=admin_user)
    assert exc.value.error_code == "invalid_delivery_state" and exc.value.details == {"status": state}
    assert not DeliveryAssignment.objects.exists()


def test_ineligible_partner_is_refused(user, shop):
    shipment = _shipment(user, shop)
    for partner in (
        create_partner(shop["store"], email="offline@example.com", status="offline"),
        create_partner(shop["store"], email="unverified@example.com", is_verified=False),
        create_partner(store_at(9), email="elsewhere@example.com"),
    ):
        with pytest.raises(Exception) as exc:  # noqa: PT011
            assign_shipment(shipment, partner, actor=None)
        assert exc.value.error_code == "partner_unavailable"
    assert not DeliveryAssignment.objects.exists()


def test_cancelling_the_order_frees_the_rider(user, shop):
    partner = create_partner(shop["store"])
    shipment = _shipment(user, shop)
    assignment = assign_shipment(shipment, partner, actor=None)
    partner.refresh_from_db()
    assert partner.status == DeliveryPartner.Status.BUSY
    cancel_order_by_customer(shipment.order, user=user, reason="Changed my mind")
    assignment.refresh_from_db()
    partner.refresh_from_db()
    assert assignment.status == "cancelled" and partner.status == DeliveryPartner.Status.AVAILABLE
    assert [h.to_status for h in assignment.status_history.all()] == ["assigned", "cancelled"]


def test_unassigning_allows_a_new_rider(user, shop, admin_user):
    first, second = (
        create_partner(shop["store"], email="a@example.com"),
        create_partner(shop["store"], email="b@example.com"),
    )
    shipment = _shipment(user, shop)
    order = shipment.order
    for status in ("processing", "packed"):
        order = transition_order(order, status, actor=admin_user)
    assign_shipment(shipment, first, actor=admin_user)
    order.refresh_from_db()
    assert order.status == OrderStatus.ASSIGNED
    order = transition_order(order, "packed", actor=admin_user)  # rider dropped out
    assert not DeliveryAssignment.objects.filter(status__in=DeliveryAssignment.ACTIVE_STATUSES).exists()
    assign_shipment(shipment, second, actor=admin_user)
    assert DeliveryAssignment.objects.filter(shipment=shipment, status="assigned").get().partner == second


# --- Concurrency ---------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_staff_assigning_the_same_shipment_at_once():
    store = store_at(0, riders=0, zone=True)
    _, variant = create_product(stock=5, store=store)
    (buyer,) = _customers(1)
    shipment = _shipment(buyer, {"store": store, "variant": variant})
    riders = [create_partner(store, email=f"r{i}@example.com") for i in range(3)]

    results = run_concurrently(*[lambda r=r: assign_shipment(shipment, r, actor=None) for r in riders])

    assert len(_ok(results)) == 1 and _error_codes(results) == ["already_assigned"] * 2
    assert DeliveryAssignment.objects.filter(shipment=shipment).count() == 1


@pytest.mark.django_db(transaction=True)
def test_one_rider_is_never_given_more_than_their_capacity():
    store = store_at(0, riders=0, zone=True)
    _, variant = create_product(stock=5, store=store)
    shop = {"store": store, "variant": variant}
    shipments = [_shipment(buyer, shop) for buyer in _customers(3)]
    rider = create_partner(store, max_active_assignments=1)

    results = run_concurrently(*[lambda s=s: assign_shipment(s, rider, actor=None) for s in shipments])

    assert len(_ok(results)) == 1 and _error_codes(results) == ["partner_unavailable"] * 2
    assert rider.assignments.filter(status__in=DeliveryAssignment.ACTIVE_STATUSES).count() == 1
