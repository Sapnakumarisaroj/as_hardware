"""Phase 7: real concurrent requests (threads, each with its own database connection).

Every scenario releases all threads at once through a barrier and then checks invariants: no
overselling, one order per idempotency key, coupon limits held, exactly one winner when two
state changes compete, one capture per payment, one refund per return.

On PostgreSQL/MySQL the services' SELECT … FOR UPDATE row locks do the serializing. SQLite has
no row locks, so settings use BEGIN IMMEDIATE (one writer at a time, others wait) and the tests
use a file database; see config/settings/base.py and test.py.
"""

import threading
from collections.abc import Callable

import pytest
from django.contrib.auth import get_user_model
from django.db import connections

from apps.carts.services import add_item
from apps.core.testing import create_address, create_coupon, create_product, create_store
from apps.inventory.models import Inventory, StockMovement
from apps.offers.models import Coupon
from apps.orders.models import Order, OrderStatus, OrderStatusHistory, ReturnRequest
from apps.orders.returns import approve_return, receive_return, request_return
from apps.orders.services import cancel_order_by_customer, place_order, transition_order
from apps.payments.models import Payment, Refund

from .helpers import advance, deliver, order_with, pay

pytestmark = pytest.mark.django_db(transaction=True)


def run_concurrently(*calls: Callable, timeout: float = 60) -> list[tuple[str, object]]:
    """Start every call at the same moment; return ("ok", result) or ("error", exception) each."""
    barrier = threading.Barrier(len(calls))
    results: list[tuple[str, object]] = [("error", TimeoutError("did not finish"))] * len(calls)

    def worker(index: int, call: Callable) -> None:
        try:
            barrier.wait(timeout)
            results[index] = ("ok", call())
        except Exception as exc:  # noqa: BLE001 — the test inspects whatever was raised
            results[index] = ("error", exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i, call)) for i, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)
    assert not any(thread.is_alive() for thread in threads), "a concurrent call hung"
    return results


def _ok(results):
    return [value for outcome, value in results if outcome == "ok"]


def _error_codes(results):
    return sorted(
        getattr(value, "error_code", type(value).__name__) for outcome, value in results if outcome == "error"
    )


def _customers(n: int):
    return [
        get_user_model().objects.create_user(f"buyer{i}@example.com", "S3cure-pass!", full_name=f"Buyer {i}")
        for i in range(n)
    ]


def _levels(store, variant):
    inv = Inventory.objects.get(store=store, variant=variant)
    return inv.available_quantity, inv.reserved_quantity


def _checkout(user, **kwargs):
    address_id = create_address(user).id
    return lambda: place_order(user=user, address_id=address_id, payment_method="cod", **kwargs)


# --- Stock ----------------------------------------------------------------------------------


def test_last_unit_is_sold_once():
    store = create_store()
    _, variant = create_product(stock=1, store=store)
    buyers = _customers(4)
    for buyer in buyers:
        add_item(buyer, variant.id, 1)  # all four saw it in stock

    results = run_concurrently(*[_checkout(buyer) for buyer in buyers])

    assert len(_ok(results)) == 1
    assert _error_codes(results) == ["insufficient_stock"] * 3
    assert _levels(store, variant) == (0, 1)
    assert Order.objects.count() == 1
    assert StockMovement.objects.filter(movement_type="reservation").count() == 1


def test_limited_stock_is_never_oversold():
    store = create_store()
    _, variant = create_product(stock=3, store=store)
    buyers = _customers(6)
    for buyer in buyers:
        add_item(buyer, variant.id, 1)

    results = run_concurrently(*[_checkout(buyer) for buyer in buyers])

    assert len(_ok(results)) == 3 and _error_codes(results) == ["insufficient_stock"] * 3
    assert _levels(store, variant) == (0, 3)
    orders = Order.objects.all()
    assert sum(item.quantity for order in orders for item in order.items.all()) == 3


# --- Double submits -------------------------------------------------------------------------


def test_same_idempotency_key_creates_one_order(user):
    store = create_store()
    _, variant = create_product(stock=5, store=store)
    add_item(user, variant.id, 2)
    submit = _checkout(user, idempotency_key="double-click-key-1")

    results = run_concurrently(submit, submit, submit)

    orders = _ok(results)
    assert len(orders) == 3
    assert len({order.pk for order, _payment in orders}) == 1
    assert Order.objects.count() == 1
    assert _levels(store, variant) == (3, 2)


def test_api_double_submit_answers_201_once_and_flags_the_replay(user):
    """Found by the Phase 7 live run: both racing requests used to answer 201 (still one order)."""
    from rest_framework.test import APIClient

    store = create_store()
    _, variant = create_product(stock=5, store=store)
    add_item(user, variant.id, 1)
    address_id = create_address(user).id

    def submit():
        client = APIClient()
        client.force_authenticate(user)
        body = {"address_id": address_id, "payment_method": "cod"}
        return client.post("/api/orders/", body, format="json", HTTP_IDEMPOTENCY_KEY="race-key-0001")

    responses = [value for _, value in run_concurrently(submit, submit)]

    assert sorted(r.status_code for r in responses) == [200, 201]
    replay = next(r for r in responses if r.status_code == 200)
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert len({r.json()["order_number"] for r in responses}) == 1 and Order.objects.count() == 1


def test_double_submit_without_key_still_creates_one_order(user):
    store = create_store()
    _, variant = create_product(stock=5, store=store)
    add_item(user, variant.id, 2)
    submit = _checkout(user)

    results = run_concurrently(submit, submit)

    assert len(_ok(results)) == 1 and _error_codes(results) == ["cart_empty"]
    assert Order.objects.count() == 1 and _levels(store, variant) == (3, 2)


def test_coupon_usage_limit_holds_under_concurrency():
    store = create_store()
    _, variant = create_product(price="900.00", stock=10, store=store)
    create_coupon("ONCE", usage_limit=1)
    buyers = _customers(3)
    for buyer in buyers:
        add_item(buyer, variant.id, 1)

    results = run_concurrently(*[_checkout(buyer, coupon_code="ONCE") for buyer in buyers])

    assert len(_ok(results)) == 1 and _error_codes(results) == ["coupon_exhausted"] * 2
    assert Coupon.objects.get(code="ONCE").used_count == 1
    assert _levels(store, variant) == (9, 1)


# --- Competing state changes ----------------------------------------------------------------


def test_customer_cancel_racing_staff_packing_has_one_winner(user, staff_user):
    store = create_store()
    _, variant = create_product(stock=5, store=store)
    order, _ = order_with(user, (variant, 2))
    order = advance(order, staff_user, "processing")

    results = run_concurrently(
        lambda: cancel_order_by_customer(order, user=user, reason="Found it cheaper"),
        lambda: transition_order(order, OrderStatus.PACKED, actor=staff_user),
    )

    assert len(_ok(results)) == 1
    order.refresh_from_db()
    if order.status == OrderStatus.CANCELLED:
        assert _levels(store, variant) == (5, 0)  # reservation released exactly once
    else:
        assert order.status == OrderStatus.PACKED and _levels(store, variant) == (3, 2)
    assert OrderStatusHistory.objects.filter(order=order).count() == 4  # pending, confirmed, processing, winner


def test_cancel_racing_pickup_never_loses_or_duplicates_stock(user, staff_user):
    store = create_store()
    _, variant = create_product(stock=5, store=store)
    order, _ = order_with(user, (variant, 2))
    order = advance(order, staff_user, "processing", "packed", "assigned")

    results = run_concurrently(
        lambda: transition_order(order, OrderStatus.CANCELLED, actor=staff_user, note="Customer unreachable"),
        lambda: transition_order(order, OrderStatus.PICKED_UP, actor=staff_user),
    )

    assert len(_ok(results)) == 1
    order.refresh_from_db()
    expected = {OrderStatus.CANCELLED: (5, 0), OrderStatus.PICKED_UP: (3, 0)}[order.status]
    assert _levels(store, variant) == expected


def test_payment_is_captured_once_when_verified_twice(user):
    store = create_store()
    _, variant = create_product(stock=5, store=store)
    order, payment = order_with(user, (variant, 1), method="online")

    results = run_concurrently(lambda: pay(order, payment), lambda: pay(order, payment))

    assert len(_ok(results)) == 2  # the repeat is an idempotent success
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == Payment.Status.CAPTURED and order.status == OrderStatus.CONFIRMED
    assert OrderStatusHistory.objects.filter(order=order, to_status=OrderStatus.CONFIRMED).count() == 1
    assert not Refund.objects.exists()


# --- Returns --------------------------------------------------------------------------------


def test_concurrent_return_requests_open_only_one(user, staff_user):
    store = create_store()
    _, variant = create_product(stock=5, store=store)
    order, _ = order_with(user, (variant, 2))
    order = deliver(order, staff_user)
    item_id = order.items.get().id

    def ask():
        return request_return(order, user=user, items=[{"order_item_id": item_id, "quantity": 2}], reason="damaged")

    results = run_concurrently(ask, ask, ask)

    assert len(_ok(results)) == 1 and _error_codes(results) == ["return_open"] * 2
    assert ReturnRequest.objects.count() == 1


def test_return_received_twice_restocks_and_refunds_once(user, staff_user):
    store = create_store()
    _, variant = create_product(stock=5, store=store)
    order, _ = order_with(user, (variant, 2))
    order = deliver(order, staff_user)
    ret = request_return(
        order, user=user, items=[{"order_item_id": order.items.get().id, "quantity": 2}], reason="defective"
    )
    approve_return(ret, actor=staff_user)

    results = run_concurrently(
        lambda: receive_return(ret, actor=staff_user), lambda: receive_return(ret, actor=staff_user)
    )

    assert len(_ok(results)) == 1 and _error_codes(results) == ["return_state_invalid"]
    assert _levels(store, variant) == (5, 0)
    assert StockMovement.objects.filter(movement_type="return").count() == 1
    assert Refund.objects.count() == 1
