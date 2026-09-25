"""Order-workflow builders shared by the Phase 7 tests."""

from apps.carts.services import add_item
from apps.core.testing import create_address
from apps.orders.models import Order, OrderStatus
from apps.orders.services import place_order, transition_order
from apps.payments.models import Payment
from apps.payments.services import verify_payment

TO_DELIVERED = ("processing", "packed", "assigned", "picked_up", "out_for_delivery", "delivered")


def order_with(user, *pairs, method: str = "cod", coupon_code: str = "") -> tuple[Order, Payment]:
    """Fill the cart with (variant, quantity) pairs and place an order."""
    for variant, quantity in pairs:
        add_item(user, variant.id, quantity)
    return place_order(user=user, address_id=create_address(user).id, payment_method=method, coupon_code=coupon_code)


def pay(order: Order, payment: Payment, outcome: str = "success") -> Payment:
    payload = {"mock_signature": payment.metadata["client_payload"]["mock_signature"], "mock_outcome": outcome}
    return verify_payment(payment.public_id, user=order.user, payload=payload)


def advance(order: Order, actor, *statuses: str) -> Order:
    for status in statuses:
        order = transition_order(order, status, actor=actor)
    return order


def deliver(order: Order, actor) -> Order:
    """Walk a confirmed order through the normal fulfilment steps to DELIVERED."""
    order.refresh_from_db()
    assert order.status == OrderStatus.CONFIRMED, order.status
    return advance(order, actor, *TO_DELIVERED)
