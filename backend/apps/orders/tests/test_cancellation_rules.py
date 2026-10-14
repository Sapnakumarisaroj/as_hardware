"""Customer cancellation rules: online only within CUSTOMER_CANCEL_WINDOW_MINUTES (5) of placing the order, and a
₹200 fee for a cash-on-delivery order the shop has started preparing, added to the customer's next order."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.testing import create_address, create_product, create_store
from apps.orders.models import Order, OrderStatus
from apps.orders.services import transition_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(user):
    store = create_store()
    _, tape = create_product(name="PTFE Tape", price="70.00", mrp="100.00", stock=50, store=store, gst_rate="5.00")
    return {"tape": tape, "address": create_address(user)}


def _place(client, shop, method="cod"):
    res = client.post("/api/cart/items/", {"variant_id": shop["tape"].id, "quantity": 1}, format="json")
    assert res.status_code == 201, res.json()
    res = client.post("/api/orders/", {"address_id": shop["address"].id, "payment_method": method}, format="json")
    assert res.status_code == 201, res.json()
    return res.json()


def _cancel(client, number):
    return client.post(f"/api/orders/{number}/cancel/", {"reason": "Ordered by mistake"}, format="json")


def _age(number, minutes):
    Order.objects.filter(order_number=number).update(created_at=timezone.now() - timedelta(minutes=minutes))


def _processing(number, staff_user):
    order = Order.objects.get(order_number=number)
    transition_order(order, OrderStatus.PROCESSING, actor=staff_user)


def test_customer_can_cancel_within_five_minutes(auth_client, shop):
    order = _place(auth_client, shop)
    assert order["can_cancel"] is True and order["cancel_deadline"]
    assert order["cancellation_fee_if_cancelled"] == "0.00"  # just confirmed: free
    res = _cancel(auth_client, order["order_number"])
    assert res.status_code == 200 and res.json()["status"] == "cancelled"
    assert res.json()["cancellation_fee"] == "0.00"


def test_customer_cannot_cancel_after_five_minutes(auth_client, shop):
    order = _place(auth_client, shop)
    _age(order["order_number"], 6)
    detail = auth_client.get(f"/api/orders/{order['order_number']}/").json()
    assert detail["can_cancel"] is False and detail["cancel_deadline"] is None
    res = _cancel(auth_client, order["order_number"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "cancel_window_passed"
    assert "within 5 minutes" in res.json()["error"]["message"]
    assert Order.objects.get(order_number=order["order_number"]).status == OrderStatus.CONFIRMED


def test_staff_can_still_cancel_after_the_window_without_a_fee(auth_client, shop, staff_user):
    order = _place(auth_client, shop)
    _processing(order["order_number"], staff_user)
    _age(order["order_number"], 60)
    transition_order(Order.objects.get(order_number=order["order_number"]), OrderStatus.CANCELLED, actor=staff_user)
    cancelled = Order.objects.get(order_number=order["order_number"])
    assert cancelled.status == OrderStatus.CANCELLED and cancelled.cancellation_fee == Decimal("0.00")


def test_cod_order_cancelled_while_being_prepared_pays_200_on_the_next_order(auth_client, shop, staff_user):
    first = _place(auth_client, shop)
    _processing(first["order_number"], staff_user)
    detail = auth_client.get(f"/api/orders/{first['order_number']}/").json()
    assert detail["cancellation_fee_if_cancelled"] == "200.00"  # the page warns before cancelling
    res = _cancel(auth_client, first["order_number"])
    assert res.status_code == 200 and res.json()["cancellation_fee"] == "200.00"

    preview = (
        auth_client.post("/api/cart/items/", {"variant_id": shop["tape"].id, "quantity": 1}, format="json")
        and auth_client.post("/api/checkout/preview/", {"address_id": shop["address"].id}, format="json").json()
    )
    totals = preview["totals"]
    assert totals["previous_cancellation_fees"] == "200.00"
    assert totals["cancellation_fee_orders"] == [first["order_number"]]
    goods_and_delivery = (
        Decimal(totals["subtotal"]) - Decimal(totals["discount_total"]) + Decimal(totals["delivery_fee"])
    )
    assert Decimal(totals["grand_total"]) == goods_and_delivery + Decimal("200.00")

    res = auth_client.post(
        "/api/orders/",
        {"address_id": shop["address"].id, "payment_method": "cod", "expected_total": totals["grand_total"]},
        format="json",
    )
    assert res.status_code == 201, res.json()
    second = res.json()
    assert second["previous_cancellation_fees"] == "200.00" and second["grand_total"] == totals["grand_total"]
    assert (
        Order.objects.get(order_number=first["order_number"]).cancellation_fee_collected_on.order_number
        == (second["order_number"])
    )
    # Collected once: a third order no longer carries it.
    auth_client.post("/api/cart/items/", {"variant_id": shop["tape"].id, "quantity": 1}, format="json")
    third = auth_client.post("/api/checkout/preview/", {"address_id": shop["address"].id}, format="json").json()
    assert third["totals"]["previous_cancellation_fees"] == "0.00"


def test_fee_goes_back_to_the_next_order_if_the_order_carrying_it_is_cancelled(auth_client, shop, staff_user):
    first = _place(auth_client, shop)
    _processing(first["order_number"], staff_user)
    _cancel(auth_client, first["order_number"])
    second = _place(auth_client, shop)
    assert second["previous_cancellation_fees"] == "200.00"
    assert _cancel(auth_client, second["order_number"]).status_code == 200  # free: not being prepared yet
    third = _place(auth_client, shop)
    assert third["previous_cancellation_fees"] == "200.00"  # still owed once, now on this order
    assert (
        Order.objects.get(order_number=first["order_number"]).cancellation_fee_collected_on.order_number
        == (third["order_number"])
    )


def test_online_orders_never_pay_the_cancellation_fee(auth_client, shop, staff_user):
    order = _place(auth_client, shop, method="online")
    Order.objects.filter(order_number=order["order_number"]).update(status=OrderStatus.CONFIRMED)
    _processing(order["order_number"], staff_user)
    res = _cancel(auth_client, order["order_number"])
    assert res.status_code == 200 and res.json()["cancellation_fee"] == "0.00"


def test_the_fee_is_shown_on_the_invoice(auth_client, shop, staff_user):
    first = _place(auth_client, shop)
    _processing(first["order_number"], staff_user)
    _cancel(auth_client, first["order_number"])
    second = _place(auth_client, shop)
    res = auth_client.get(f"/api/orders/{second['order_number']}/invoice/")
    assert res.status_code == 200
    html = res.content.decode()
    assert "Cancellation fee" in html and first["order_number"] in html and "₹200.00" in html
