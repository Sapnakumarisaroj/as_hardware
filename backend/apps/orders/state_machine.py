"""Allowed order status transitions — the single source of truth."""

from .models import OrderStatus as S

TRANSITIONS: dict[str, frozenset[str]] = {
    S.PENDING: frozenset({S.CONFIRMED, S.CANCELLED}),
    S.CONFIRMED: frozenset({S.PROCESSING, S.CANCELLED}),
    S.PROCESSING: frozenset({S.PACKED, S.CANCELLED}),
    S.PACKED: frozenset({S.ASSIGNED, S.CANCELLED, S.DELIVERY_FAILED}),
    # back to PACKED = partner unassigned; DELIVERY_FAILED from here = another shipment of the order failed
    S.ASSIGNED: frozenset({S.PICKED_UP, S.PACKED, S.CANCELLED, S.DELIVERY_FAILED}),
    S.PICKED_UP: frozenset({S.OUT_FOR_DELIVERY, S.DELIVERY_FAILED}),
    S.OUT_FOR_DELIVERY: frozenset({S.DELIVERED, S.DELIVERY_FAILED}),
    # Phase 10: the goods are back at the store. Send them out again (new rider) or cancel the order.
    S.DELIVERY_FAILED: frozenset({S.ASSIGNED, S.PACKED, S.CANCELLED}),
    S.DELIVERED: frozenset({S.RETURN_REQUESTED}),
    S.RETURN_REQUESTED: frozenset({S.RETURNED, S.DELIVERED}),  # back to DELIVERED = return rejected
    S.CANCELLED: frozenset(),
    S.RETURNED: frozenset(),
}

# Statuses in which the customer may still cancel on their own (before packing).
CUSTOMER_CANCELLABLE = frozenset({S.PENDING, S.CONFIRMED, S.PROCESSING})
# Moves into, out of and within the return statuses happen only through `orders.returns`
# (which restocks and records refunds); the generic staff transition refuses them.
RETURN_WORKFLOW_STATUSES = frozenset({S.RETURN_REQUESTED, S.RETURNED})
# Stock is still reserved (not yet left the store) in these statuses.
STOCK_RESERVED_STATUSES = frozenset({S.PENDING, S.CONFIRMED, S.PROCESSING, S.PACKED, S.ASSIGNED})
# The delivery leg. While a delivery partner holds a shipment, only the partner's own steps
# (apps.delivery.workflow) move the order through these; staff reassign or unassign instead.
DELIVERY_STATUSES = frozenset({S.PICKED_UP, S.OUT_FOR_DELIVERY, S.DELIVERED, S.DELIVERY_FAILED})
# The order of the delivery leg, used to derive the order status from its shipments.
DELIVERY_PATH = (S.PACKED, S.ASSIGNED, S.PICKED_UP, S.OUT_FOR_DELIVERY, S.DELIVERED)


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in TRANSITIONS.get(from_status, frozenset())
