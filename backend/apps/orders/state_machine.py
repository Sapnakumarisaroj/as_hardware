"""Allowed order status transitions — the single source of truth."""

from .models import OrderStatus as S

TRANSITIONS: dict[str, frozenset[str]] = {
    S.PENDING: frozenset({S.CONFIRMED, S.CANCELLED}),
    S.CONFIRMED: frozenset({S.PROCESSING, S.CANCELLED}),
    S.PROCESSING: frozenset({S.PACKED, S.CANCELLED}),
    S.PACKED: frozenset({S.ASSIGNED, S.CANCELLED}),
    S.ASSIGNED: frozenset({S.PICKED_UP, S.PACKED, S.CANCELLED}),  # back to PACKED = partner unassigned
    S.PICKED_UP: frozenset({S.OUT_FOR_DELIVERY}),
    S.OUT_FOR_DELIVERY: frozenset({S.DELIVERED}),
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


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in TRANSITIONS.get(from_status, frozenset())
