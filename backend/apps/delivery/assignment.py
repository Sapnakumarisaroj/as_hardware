"""Who carries a shipment: eligibility, assigning, reassigning and releasing riders.

Phase 9 built eligibility and safe assignment; Phase 10 adds reassignment, re-dispatch after a
failed delivery, return pickups and the cash a rider must collect. What the rider then does
with the job (accept … deliver) is apps.delivery.workflow.

Eligible partner: active, verified, status "available", fewer active assignments than
`max_active_assignments`, and either based at the shipment's store or currently within
DELIVERY_PARTNER_PICKUP_RADIUS_KM of it. Ranked: same store first, fewest active deliveries,
then distance to the store.

Every function here locks the order first and the rider second, and refuses:
  - orders that are not waiting for a rider
  - a shipment that already has an active assignment (no duplicates)
  - a partner who is not eligible or is at capacity
  - taking a shipment away from a rider who already has the goods
"""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError
from apps.notifications.services import notify, notify_order
from apps.orders.models import Order, OrderShipment, OrderStatus, PaymentMethod, PaymentStatus, ShipmentStatus
from apps.orders.shipments import shipment_amounts, sync_order_status
from integrations.maps import Point, haversine_km

from .models import DeliveryAssignment, DeliveryPartner, DeliveryStatusHistory

# Statuses in which the goods are already packed, so a newly assigned rider can come for them at once.
PACKED_STATUSES = (OrderStatus.PACKED, OrderStatus.DELIVERY_FAILED)

ASSIGNABLE_ORDER_STATUSES = (
    OrderStatus.CONFIRMED,
    OrderStatus.PROCESSING,
    OrderStatus.PACKED,
    OrderStatus.ASSIGNED,
    OrderStatus.DELIVERY_FAILED,  # send it out again
)
ASSIGNABLE_SHIPMENT_STATUSES = (ShipmentStatus.PENDING, ShipmentStatus.ASSIGNED, ShipmentStatus.FAILED)
ACTIVE = DeliveryAssignment.ACTIVE_STATUSES
A = DeliveryAssignment.Status
KIND = DeliveryAssignment.Kind


class AssignmentError(ConflictError):
    default_code = "assignment_invalid"


@dataclass
class Candidate:
    partner: DeliveryPartner
    active_assignments: int
    same_store: bool
    distance_km: float | None


# --- Riders --------------------------------------------------------------------------------------


def partners_with_load(queryset=None):
    queryset = DeliveryPartner.objects.all() if queryset is None else queryset
    return queryset.select_related("user", "home_store").annotate(
        active_count=Count("assignments", filter=Q(assignments__status__in=ACTIVE), distinct=True)
    )


def eligible_partners(shipment: OrderShipment) -> list[Candidate]:
    store = shipment.store
    store_point = Point.of(store.latitude, store.longitude)
    radius = float(settings.DELIVERY_PARTNER_PICKUP_RADIUS_KM)
    result = []
    available = partners_with_load().filter(is_active=True, is_verified=True, status=DeliveryPartner.Status.AVAILABLE)
    for partner in available:
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


def refresh_partner_status(partner: DeliveryPartner) -> None:
    """busy ⇄ available follows the rider's load. Offline riders stay offline."""
    if partner.status == DeliveryPartner.Status.OFFLINE:
        return
    active = partner.assignments.filter(status__in=ACTIVE).count()
    status = (
        DeliveryPartner.Status.BUSY if active >= partner.max_active_assignments else DeliveryPartner.Status.AVAILABLE
    )
    if status != partner.status:
        partner.status = status
        partner.save(update_fields=["status", "updated_at"])


def has_rider_in_charge(order: Order) -> bool:
    """A delivery partner holds (or is about to hold) part of this order."""
    return DeliveryAssignment.objects.filter(order=order, kind=KIND.DELIVERY, status__in=ACTIVE).exists()


def record_history(assignment, from_status: str, *, actor=None, note: str = "", latitude=None, longitude=None) -> None:
    DeliveryStatusHistory.objects.create(
        assignment=assignment,
        from_status=from_status,
        to_status=assignment.status,
        changed_by=actor if getattr(actor, "pk", None) else None,
        note=note[:255],
        latitude=latitude,
        longitude=longitude,
    )


# --- Assigning -----------------------------------------------------------------------------------


def _require_eligible(shipment: OrderShipment, partner: DeliveryPartner) -> DeliveryPartner:
    partner = DeliveryPartner.objects.select_for_update().get(pk=partner.pk)
    if partner.pk not in {c.partner.pk for c in eligible_partners(shipment)}:
        raise AssignmentError(
            "This delivery partner isn't available for this store right now (offline, busy or too far).",
            code="partner_unavailable",
        )
    return partner


def _cod_due(order: Order, shipment: OrderShipment) -> Decimal:
    if order.payment_method != PaymentMethod.COD or order.payment_status == PaymentStatus.PAID:
        return Decimal("0.00")
    return shipment_amounts(order).get(shipment.pk, Decimal("0.00"))


def _create(order, shipment, partner, *, actor, note: str, kind=KIND.DELIVERY, return_request=None):
    assignment = DeliveryAssignment.objects.create(
        order=order,
        shipment=shipment,
        partner=partner,
        kind=kind,
        return_request=return_request,
        distance_km=shipment.distance_km if shipment else None,
        cod_amount_due=_cod_due(order, shipment) if kind == KIND.DELIVERY and shipment else Decimal("0.00"),
    )
    record_history(assignment, "", actor=actor, note=note)
    refresh_partner_status(partner)
    what = "A delivery" if kind == KIND.DELIVERY else "A return pickup"
    refs = {"assignment_id": assignment.pk, "order_number": order.order_number, "kind": kind}
    notify(
        partner.user,
        event="delivery.assigned",
        context={"order_number": order.order_number, "job_kind": what},
        data=refs,
    )
    return assignment


def tell_riders_ready(order: Order) -> None:
    """The store finished packing: riders already holding a job for this order can come for it."""
    jobs = DeliveryAssignment.objects.filter(
        order=order, kind=KIND.DELIVERY, status__in=DeliveryAssignment.BEFORE_PICKUP
    )
    for job in jobs.select_related("partner__user", "shipment__store"):
        store = job.shipment.store.name if job.shipment_id else "The store"
        notify(
            job.partner.user,
            event="order.ready_for_pickup",
            context={"order_number": order.order_number, "store_name": store},
            data={"assignment_id": job.pk, "order_number": order.order_number},
        )


def _locked(shipment: OrderShipment) -> tuple[Order, OrderShipment]:
    order = Order.objects.select_for_update().get(pk=shipment.order_id)
    return order, OrderShipment.objects.select_related("store").get(pk=shipment.pk)


def _active_delivery(shipment: OrderShipment) -> DeliveryAssignment | None:
    return (
        DeliveryAssignment.objects.select_for_update()
        .filter(shipment=shipment, kind=KIND.DELIVERY, status__in=ACTIVE)
        .first()
    )


def _require_assignable(order: Order, shipment: OrderShipment) -> None:
    if order.status not in ASSIGNABLE_ORDER_STATUSES or shipment.status not in ASSIGNABLE_SHIPMENT_STATUSES:
        raise AssignmentError(
            f"Order {order.order_number} is {order.get_status_display().lower()} and can't get a rider now.",
            code="invalid_delivery_state",
            details={"status": order.status},
        )


@transaction.atomic
def assign_shipment(shipment: OrderShipment, partner: DeliveryPartner, *, actor) -> DeliveryAssignment:
    """Give a waiting shipment (or one that came back undelivered) to a rider."""
    order, shipment = _locked(shipment)
    _require_assignable(order, shipment)
    if _active_delivery(shipment) is not None:
        raise AssignmentError("This shipment already has a delivery partner.", code="already_assigned")
    partner = _require_eligible(shipment, partner)

    again = shipment.status == ShipmentStatus.FAILED
    packed = order.status in PACKED_STATUSES  # the rider can come for it straight away
    assignment = _create(order, shipment, partner, actor=actor, note="Sent out again" if again else "Assigned by store")
    shipment.status = ShipmentStatus.ASSIGNED
    shipment.save(update_fields=["status"])
    sync_order_status(order, actor=actor, note="Delivery partner assigned")
    rider = partner.user.full_name.split(" ")[0] or "A delivery partner"
    refs = {"shipment": shipment.sequence, "assignment_id": assignment.pk}
    if again:
        notify_order(order, "delivery.redispatched", data=refs, rider_name=rider)
    else:
        notify_order(order, "delivery.rider_assigned", data=refs, rider_name=rider, store_name=shipment.store.name)
    if packed:
        notify(
            partner.user,
            event="order.ready_for_pickup",
            context={"order_number": order.order_number, "store_name": shipment.store.name},
            data={"assignment_id": assignment.pk, "order_number": order.order_number},
        )
    record_audit(
        action="delivery.assign",
        actor=actor,
        target=assignment,
        changes={"order": order.order_number, "shipment": shipment.sequence, "partner": partner.pk},
    )
    return assignment


def _take_away(assignment: DeliveryAssignment, *, actor, note: str) -> None:
    previous = assignment.status
    assignment.status = A.CANCELLED
    assignment.save(update_fields=["status", "updated_at"])
    record_history(assignment, previous, actor=actor, note=note)
    refresh_partner_status(DeliveryPartner.objects.select_for_update().get(pk=assignment.partner_id))
    number = assignment.order.order_number
    notify(
        assignment.partner.user,
        event="delivery.unassigned",
        context={"order_number": number, "note": note},
        data={"assignment_id": assignment.pk, "order_number": number},
    )


def _require_before_pickup(current: DeliveryAssignment | None) -> DeliveryAssignment:
    if current is None:
        raise AssignmentError("This shipment has no delivery partner.", code="not_assigned")
    if current.status not in DeliveryAssignment.BEFORE_PICKUP:
        raise AssignmentError(
            "The delivery partner already has the goods. They must deliver them or report a failed delivery.",
            code="already_picked_up",
            details={"status": current.status},
        )
    return current


@transaction.atomic
def reassign_shipment(shipment: OrderShipment, partner: DeliveryPartner, *, actor, reason: str = ""):
    """Give the shipment to another rider. Only before pickup: goods never change hands silently."""
    order, shipment = _locked(shipment)
    current = _require_before_pickup(_active_delivery(shipment))
    if current.partner_id == partner.pk:
        raise AssignmentError("This delivery partner already has the shipment.", code="same_partner")
    partner = _require_eligible(shipment, partner)
    _take_away(current, actor=actor, note=f"Reassigned. {reason}".strip())
    assignment = _create(order, shipment, partner, actor=actor, note=f"Reassigned by store. {reason}".strip())
    record_audit(
        action="delivery.reassign",
        actor=actor,
        target=assignment,
        changes={"order": order.order_number, "from": current.partner_id, "to": partner.pk, "reason": reason},
    )
    return assignment


@transaction.atomic
def unassign_shipment(shipment: OrderShipment, *, actor, reason: str = "") -> OrderShipment:
    """Take the shipment off its rider (before pickup); it waits for a rider again."""
    order, shipment = _locked(shipment)
    current = _require_before_pickup(_active_delivery(shipment))
    _take_away(current, actor=actor, note=f"Unassigned. {reason}".strip())
    shipment.status = ShipmentStatus.PENDING
    shipment.save(update_fields=["status"])
    sync_order_status(order, actor=actor, note="Delivery partner unassigned")
    record_audit(
        action="delivery.unassign",
        actor=actor,
        target=current,
        changes={"order": order.order_number, "partner": current.partner_id, "reason": reason},
    )
    return shipment


def release_assignments(order: Order, *, reason: str) -> int:
    """The order was cancelled or sent back to packing: cancel the jobs of riders who have not
    picked anything up yet and free them. Caller holds the order lock."""
    released = 0
    waiting = DeliveryAssignment.objects.select_for_update().filter(
        order=order, kind=KIND.DELIVERY, status__in=DeliveryAssignment.BEFORE_PICKUP
    )
    for assignment in waiting:
        previous = assignment.status
        assignment.status = A.CANCELLED
        assignment.save(update_fields=["status", "updated_at"])
        record_history(assignment, previous, note=reason)
        refresh_partner_status(assignment.partner)
        released += 1
    return released


# --- Return pickups ------------------------------------------------------------------------------


@transaction.atomic
def assign_return_pickup(return_request, partner: DeliveryPartner, *, actor) -> DeliveryAssignment:
    """Send a rider to collect an approved return from the customer and bring it to the store."""
    from apps.orders.models import ReturnRequest

    order = Order.objects.select_for_update().get(pk=return_request.order_id)
    ret = ReturnRequest.objects.select_for_update().get(pk=return_request.pk)
    if ret.status != ReturnRequest.Status.APPROVED:
        raise AssignmentError(
            f"This return is {ret.get_status_display().lower()}; only approved returns are picked up.",
            code="invalid_delivery_state",
            details={"status": ret.status},
        )
    if DeliveryAssignment.objects.filter(return_request=ret, status__in=ACTIVE).exists():
        raise AssignmentError("A delivery partner is already collecting this return.", code="already_assigned")
    line = ret.items.select_related("order_item__shipment__store").first()
    shipment = line.order_item.shipment if line else None
    if shipment is None:
        raise AssignmentError("This order has no store to bring the return to.", code="invalid_delivery_state")
    partner = _require_eligible(shipment, partner)
    assignment = _create(
        order,
        shipment,
        partner,
        actor=actor,
        note="Return pickup assigned",
        kind=KIND.RETURN_PICKUP,
        return_request=ret,
    )
    record_audit(
        action="delivery.assign_return_pickup",
        actor=actor,
        target=assignment,
        changes={"return": ret.return_number, "partner": partner.pk},
    )
    return assignment


def close_return_pickups(return_request, *, actor, received: bool) -> None:
    """The return was received at the store or rejected: no rider needs to go any more.
    Caller holds the order lock."""
    from .workflow import earning_for

    now = timezone.now()
    for assignment in DeliveryAssignment.objects.select_for_update().filter(
        return_request=return_request, status__in=ACTIVE
    ):
        previous = assignment.status
        if received and previous in DeliveryAssignment.WITH_GOODS:
            assignment.status, assignment.delivered_at = A.DELIVERED, now
            assignment.earning_amount = earning_for(assignment)
        else:
            assignment.status = A.CANCELLED
        assignment.save(update_fields=["status", "delivered_at", "earning_amount", "updated_at"])
        note = "Return received at the store" if received else "Return rejected"
        record_history(assignment, previous, actor=actor, note=note)
        refresh_partner_status(assignment.partner)
