"""Shipments: one store's part of an order, with its own delivery status and stock (Phase 10).

The order status is *derived* from its shipments once the order is packed:

    any shipment failed                      → delivery_failed
    otherwise the least advanced shipment    → packed / assigned / picked_up / out_for_delivery / delivered

so an order is "delivered" only when every shipment is, and "out for delivery" only when
nothing is still waiting at a store. Cancelled shipments are ignored.

Two callers change shipments:
- `apps.delivery.workflow` (a delivery partner's own steps) changes one shipment and then calls
  `sync_order_status`, which walks the order through the state machine to the derived status.
- `orders.services` (staff, customers, payments) changes the order; `mirror_order_status` then
  brings every shipment along. That path serves stores whose own riders don't use the app.

Stock moves once per shipment, tracked by `stock_state`: reserved → sold (left the store) or
released (cancelled before pickup); sold → restocked (cancelled after a failed delivery).
"""

from decimal import Decimal

from django.utils import timezone

from apps.core.money import ZERO, q
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import apply_movement

from .models import Order, OrderShipment, OrderStatus, ShipmentStatus, StockState
from .state_machine import DELIVERY_PATH

SS = ShipmentStatus
_RANK = {SS.PENDING: 0, SS.ASSIGNED: 1, SS.PICKED_UP: 2, SS.OUT_FOR_DELIVERY: 3, SS.DELIVERED: 4}
# The goods are with a rider or already with the customer.
LEFT_THE_STORE = (SS.PICKED_UP, SS.OUT_FOR_DELIVERY, SS.DELIVERED)
# Order statuses in which shipments drive the order.
_DERIVED_FROM_SHIPMENTS = (*DELIVERY_PATH[:-1], OrderStatus.DELIVERY_FAILED)


# --- Stock ---------------------------------------------------------------------------------------


def _move(shipment: OrderShipment, movement_type: str, *, actor, reason: str) -> None:
    from .services import OrderError  # circular at import time

    order_number = shipment.order.order_number
    for item in shipment.items.all():
        if item.variant_id is None:
            continue
        inventory = Inventory.objects.filter(store_id=shipment.store_id, variant_id=item.variant_id).first()
        if inventory is None:
            if movement_type != StockMovement.Type.RETURN:
                raise OrderError(f"Inventory record missing for {item.sku}.", code="inventory_missing")
            inventory = Inventory.objects.create(store_id=shipment.store_id, variant_id=item.variant_id)
        apply_movement(
            inventory,
            movement_type,
            item.quantity,
            reason=reason,
            reference_type="order",
            reference_id=order_number,
            actor=actor,
        )


def sell_stock(shipment: OrderShipment, *, actor) -> None:
    """The goods leave the store: the reservation becomes a sale (once)."""
    if shipment.stock_state == StockState.RESERVED:
        _move(shipment, StockMovement.Type.SALE, actor=actor, reason="Picked up for delivery")
        shipment.stock_state = StockState.SOLD
        shipment.save(update_fields=["stock_state"])


def give_stock_back(shipment: OrderShipment, *, actor, reason: str) -> None:
    """Cancelled: release what is still reserved, or put back what came back undelivered."""
    if shipment.stock_state == StockState.RESERVED:
        _move(shipment, StockMovement.Type.RELEASE, actor=actor, reason=reason)
        shipment.stock_state = StockState.RELEASED
    elif shipment.stock_state == StockState.SOLD and shipment.status != SS.DELIVERED:
        _move(shipment, StockMovement.Type.RETURN, actor=actor, reason=f"{reason} (undelivered goods restocked)")
        shipment.stock_state = StockState.RESTOCKED
    else:
        return
    shipment.save(update_fields=["stock_state"])


# --- Money ---------------------------------------------------------------------------------------


def shipment_amounts(order: Order) -> dict[int, Decimal]:
    """shipment.id → its share of the order total (what a rider collects for a COD order).

    Each shipment carries what was paid for its lines; the delivery fee travels with the first
    shipment; the last one takes the rounding remainder, so the shares add up to `grand_total`.
    """
    from .returns import paid_amounts  # circular at import time

    shipments = list(order.shipments.order_by("sequence"))
    if not shipments:
        return {}
    items = list(order.items.all())
    paid = paid_amounts(order, items)
    shares = {s.id: ZERO for s in shipments}
    for item in items:
        if item.shipment_id in shares:
            shares[item.shipment_id] += paid[item.id]
    shares[shipments[0].id] += order.delivery_fee
    *rest, last = shipments
    shares[last.id] = order.grand_total - sum((shares[s.id] for s in rest), ZERO)
    return {key: q(max(value, ZERO)) for key, value in shares.items()}


# --- Status --------------------------------------------------------------------------------------


def derived_order_status(shipments) -> str | None:
    live = [s for s in shipments if s.status != SS.CANCELLED]
    if not live:
        return None
    if any(s.status == SS.FAILED for s in live):
        return OrderStatus.DELIVERY_FAILED
    return DELIVERY_PATH[min(_RANK[s.status] for s in live)]


def sync_order_status(order: Order, *, actor, note: str = "") -> Order:
    """Bring a (locked) order to the status its shipments imply, one valid transition at a time.
    Orders that aren't packed yet are left alone: packing is the store's step."""
    from .services import apply_locked_transition

    if order.status not in _DERIVED_FROM_SHIPMENTS:
        return order
    target = derived_order_status(order.shipments.all())
    if target is None or target == order.status:
        return order

    steps: list[str] = []
    if target == OrderStatus.DELIVERY_FAILED:
        steps = [target]
    else:
        current = order.status
        if current == OrderStatus.DELIVERY_FAILED:
            current = OrderStatus.PACKED if target == OrderStatus.PACKED else OrderStatus.ASSIGNED
            steps.append(current)
        start, end = DELIVERY_PATH.index(current), DELIVERY_PATH.index(target)
        if end > start:
            steps += list(DELIVERY_PATH[start + 1 : end + 1])
        elif end < start:
            steps.append(target)  # only assigned → packed (the rider was taken off before pickup)
    for status in steps:
        apply_locked_transition(order, status, actor=actor, note=note, mirror=False)
    return order


def mirror_order_status(order: Order, to_status: str, *, actor) -> None:
    """The order was moved directly (staff, customer, payments): bring its shipments along and
    move their stock. Shipments that are already further on are not pulled back."""
    now = timezone.now()
    for shipment in order.shipments.prefetch_related("items"):
        status, fields = shipment.status, []
        if status in (SS.DELIVERED, SS.CANCELLED):
            continue
        if to_status == OrderStatus.CANCELLED:
            give_stock_back(shipment, actor=actor, reason="Order cancelled")
            shipment.status = SS.CANCELLED
        elif to_status == OrderStatus.PACKED and status in (SS.ASSIGNED, SS.FAILED):
            shipment.status = SS.PENDING
        elif to_status == OrderStatus.ASSIGNED and status in (SS.PENDING, SS.FAILED):
            shipment.status = SS.ASSIGNED
        elif to_status == OrderStatus.PICKED_UP and _RANK.get(status, 9) < _RANK[SS.PICKED_UP]:
            sell_stock(shipment, actor=actor)
            shipment.status, shipment.picked_up_at = SS.PICKED_UP, now
            fields.append("picked_up_at")
        elif to_status == OrderStatus.OUT_FOR_DELIVERY and _RANK.get(status, 9) < _RANK[SS.OUT_FOR_DELIVERY]:
            sell_stock(shipment, actor=actor)
            shipment.status, shipment.out_for_delivery_at = SS.OUT_FOR_DELIVERY, now
            shipment.delivery_attempts += 1
            fields += ["out_for_delivery_at", "delivery_attempts"]
        elif to_status == OrderStatus.DELIVERED and status != SS.FAILED:
            sell_stock(shipment, actor=actor)
            shipment.status, shipment.delivered_at = SS.DELIVERED, now
            fields.append("delivered_at")
        elif to_status == OrderStatus.DELIVERY_FAILED and status in (SS.PICKED_UP, SS.OUT_FOR_DELIVERY):
            shipment.status, shipment.failed_at = SS.FAILED, now
            shipment.failure_reason = shipment.failure_reason or "other"
            fields += ["failed_at", "failure_reason"]
        if shipment.status != status:
            shipment.save(update_fields=["status", *fields])
