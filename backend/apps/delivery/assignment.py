"""Rider assignment foundation (Phase 9). The rider's own workflow (accept, pickup, OTP, proof of
delivery) is Phase 10; this module decides *who may* carry a shipment and records the assignment.

Eligible partner: active, verified, status "available", fewer active assignments than
`max_active_assignments`, and either based at the shipment's store or currently within
DELIVERY_PARTNER_PICKUP_RADIUS_KM of it. Ranked: same store first, fewest active deliveries,
then distance to the store.

`assign_shipment` locks the order, then the partner, and refuses:
  - orders that are not waiting for a rider (confirmed / processing / packed)
  - a shipment that already has an active assignment (no duplicates)
  - a partner who is not eligible or is at capacity
When every shipment of a packed order has a rider, the order moves to "assigned".
"""

from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError
from apps.orders.models import Order, OrderShipment, OrderStatus
from integrations.maps import Point, haversine_km

from .models import DeliveryAssignment, DeliveryPartner, DeliveryStatusHistory

ASSIGNABLE_ORDER_STATUSES = (OrderStatus.CONFIRMED, OrderStatus.PROCESSING, OrderStatus.PACKED)
ACTIVE = DeliveryAssignment.ACTIVE_STATUSES


class AssignmentError(ConflictError):
    default_code = "assignment_invalid"


@dataclass
class Candidate:
    partner: DeliveryPartner
    active_assignments: int
    same_store: bool
    distance_km: float | None


def _partners_with_load():
    return (
        DeliveryPartner.objects.filter(is_active=True, is_verified=True)
        .select_related("user", "home_store")
        .annotate(active_count=Count("assignments", filter=Q(assignments__status__in=ACTIVE)))
    )


def eligible_partners(shipment: OrderShipment) -> list[Candidate]:
    store = shipment.store
    store_point = Point.of(store.latitude, store.longitude)
    radius = float(settings.DELIVERY_PARTNER_PICKUP_RADIUS_KM)
    result = []
    for partner in _partners_with_load().filter(status=DeliveryPartner.Status.AVAILABLE):
        if partner.active_count >= partner.max_active_assignments:
            continue
        here = Point.of(partner.current_latitude, partner.current_longitude)
        distance = haversine_km(here, store_point) if here and store_point else None
        same_store = partner.home_store_id == store.pk
        if not same_store and (distance is None or distance > radius):
            continue
        result.append(Candidate(partner, partner.active_count, same_store, distance))
    result.sort(
        key=lambda c: (not c.same_store, c.active_assignments, c.distance_km if c.distance_km is not None else 1e9)
    )
    return result


@transaction.atomic
def assign_shipment(shipment: OrderShipment, partner: DeliveryPartner, *, actor) -> DeliveryAssignment:
    order = Order.objects.select_for_update().get(pk=shipment.order_id)
    shipment = OrderShipment.objects.select_related("store").get(pk=shipment.pk)
    if order.status not in ASSIGNABLE_ORDER_STATUSES:
        raise AssignmentError(
            f"Order {order.order_number} is {order.get_status_display().lower()} and can't get a rider now.",
            code="invalid_delivery_state",
            details={"status": order.status},
        )
    if shipment.assignments.filter(status__in=ACTIVE).exists():
        raise AssignmentError("This shipment already has a delivery partner.", code="already_assigned")

    partner = DeliveryPartner.objects.select_for_update().get(pk=partner.pk)
    if partner.pk not in {c.partner.pk for c in eligible_partners(shipment)}:
        raise AssignmentError(
            "This delivery partner isn't available for this store right now (offline, busy or too far).",
            code="partner_unavailable",
        )

    assignment = DeliveryAssignment.objects.create(
        order=order, shipment=shipment, partner=partner, distance_km=shipment.distance_km
    )
    DeliveryStatusHistory.objects.create(
        assignment=assignment, to_status=DeliveryAssignment.Status.ASSIGNED, note="Assigned by store"
    )
    active_now = partner.assignments.filter(status__in=ACTIVE).count()
    if active_now >= partner.max_active_assignments:
        partner.status = DeliveryPartner.Status.BUSY
        partner.save(update_fields=["status", "updated_at"])

    unassigned = order.shipments.exclude(assignments__status__in=ACTIVE).exists()
    if order.status == OrderStatus.PACKED and not unassigned:
        from apps.orders.services import apply_locked_transition

        apply_locked_transition(order, OrderStatus.ASSIGNED, actor=actor, note="Delivery partner assigned")
    record_audit(
        action="delivery.assign",
        actor=actor,
        target=assignment,
        changes={"order": order.order_number, "shipment": shipment.sequence, "partner": partner.pk},
    )
    return assignment


def release_assignments(order: Order, *, reason: str) -> int:
    """Cancel the order's active assignments (order cancelled or sent back to packing) and free
    the riders. Caller holds the order lock."""
    released = 0
    for assignment in DeliveryAssignment.objects.select_for_update().filter(order=order, status__in=ACTIVE):
        previous = assignment.status
        assignment.status = DeliveryAssignment.Status.CANCELLED
        assignment.save(update_fields=["status", "updated_at"])
        DeliveryStatusHistory.objects.create(
            assignment=assignment, from_status=previous, to_status=assignment.status, note=reason[:255]
        )
        partner = assignment.partner
        if partner.status == DeliveryPartner.Status.BUSY and not partner.assignments.filter(status__in=ACTIVE).exists():
            partner.status = DeliveryPartner.Status.AVAILABLE
            partner.save(update_fields=["status", "updated_at"])
        released += 1
    return released
