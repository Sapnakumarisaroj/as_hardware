"""Phase 7: every (from, to) order-status pair against the state machine, plus stock accounting
through a full lifecycle. Invalid moves must change nothing."""

import itertools

import pytest

from apps.core.exceptions import ServiceError
from apps.core.testing import create_product, create_store
from apps.inventory.models import Inventory
from apps.orders.models import Order, OrderStatus, OrderStatusHistory
from apps.orders.returns import approve_return, receive_return, request_return
from apps.orders.services import cancel_order_by_customer, transition_order
from apps.orders.state_machine import (
    CUSTOMER_CANCELLABLE,
    RETURN_WORKFLOW_STATUSES,
    TRANSITIONS,
    can_transition,
)

from .helpers import deliver, order_with

pytestmark = pytest.mark.django_db
STATUSES = list(OrderStatus.values)


@pytest.fixture
def stock(user):
    store = create_store()
    _, variant = create_product(name="Hammer", price="400.00", mrp="500.00", stock=10, store=store)
    return store, variant


def _order_in(user, variant, status: str) -> Order:
    """A real COD order (2 units reserved) with its status forced to `status`."""
    order, _ = order_with(user, (variant, 2))
    Order.objects.filter(pk=order.pk).update(status=status)
    order.refresh_from_db()
    return order


def test_every_status_has_a_rule_and_terminal_states_are_final():
    assert set(TRANSITIONS) == set(STATUSES)
    assert all(to in STATUSES for targets in TRANSITIONS.values() for to in targets)
    assert TRANSITIONS[OrderStatus.CANCELLED] == frozenset() and TRANSITIONS[OrderStatus.RETURNED] == frozenset()
    for from_status, to_status in itertools.product(STATUSES, STATUSES):
        assert can_transition(from_status, to_status) is (to_status in TRANSITIONS[from_status])


@pytest.mark.parametrize(("from_status", "to_status"), list(itertools.product(STATUSES, STATUSES)))
def test_staff_transition_matrix(user, staff_user, stock, from_status, to_status):
    order = _order_in(user, stock[1], from_status)
    history_before = OrderStatusHistory.objects.filter(order=order).count()
    via_returns = from_status in RETURN_WORKFLOW_STATUSES or to_status in RETURN_WORKFLOW_STATUSES
    allowed = can_transition(from_status, to_status) and not via_returns

    if allowed:
        result = transition_order(order, to_status, actor=staff_user)
        assert result.status == to_status
        last = OrderStatusHistory.objects.filter(order=order).last()
        assert (last.from_status, last.to_status) == (from_status, to_status)
    else:
        with pytest.raises(ServiceError) as exc:
            transition_order(order, to_status, actor=staff_user)
        assert exc.value.error_code == "invalid_transition"
        order.refresh_from_db()
        assert order.status == from_status
        assert OrderStatusHistory.objects.filter(order=order).count() == history_before


@pytest.mark.parametrize("status", STATUSES)
def test_customer_cancel_only_before_packing(user, stock, status):
    order = _order_in(user, stock[1], status)
    if status in CUSTOMER_CANCELLABLE:
        assert cancel_order_by_customer(order, user=user, reason="No longer needed").status == OrderStatus.CANCELLED
    else:
        with pytest.raises(ServiceError):
            cancel_order_by_customer(order, user=user, reason="No longer needed")
        order.refresh_from_db()
        assert order.status == status


def test_stock_is_conserved_through_the_whole_lifecycle(user, staff_user, stock):
    store, variant = stock

    def levels():
        inv = Inventory.objects.get(store=store, variant=variant)
        return inv.available_quantity, inv.reserved_quantity

    order, _ = order_with(user, (variant, 2))
    assert levels() == (8, 2)  # reserved at placement
    cancel_order_by_customer(order, user=user, reason="Mistake")
    assert levels() == (10, 0)  # released on cancel

    order, _ = order_with(user, (variant, 3))
    assert levels() == (7, 3)
    order = deliver(order, staff_user)
    assert levels() == (7, 0)  # sold at pickup, nothing left reserved

    item = order.items.get()
    ret = request_return(order, user=user, items=[{"order_item_id": item.id, "quantity": 3}], reason="defective")
    approve_return(ret, actor=staff_user)
    receive_return(ret, actor=staff_user, restock=True)
    assert levels() == (10, 0)  # back on the shelf
    order.refresh_from_db()
    assert order.status == OrderStatus.RETURNED
    assert [h.to_status for h in order.status_history.all()] == [
        "pending",
        "confirmed",
        "processing",
        "packed",
        "assigned",
        "picked_up",
        "out_for_delivery",
        "delivered",
        "return_requested",
        "returned",
    ]
