"""Phase 7: "Buy again" puts a past order back in the cart at today's prices, within stock and limits."""

from decimal import Decimal

import pytest

from apps.carts.models import CartItem
from apps.carts.services import add_item
from apps.core.testing import create_product, create_store
from apps.inventory.models import Inventory
from apps.orders.services import cancel_order_by_customer

from .helpers import order_with

pytestmark = pytest.mark.django_db


@pytest.fixture
def past_order(user):
    store = create_store()
    _, drill = create_product(name="Drill", price="3000.00", mrp="3500.00", stock=10, store=store)
    _, tape = create_product(name="PTFE Tape", price="70.00", mrp="100.00", stock=50, store=store)
    _, glue = create_product(name="Glue", price="50.00", mrp="60.00", stock=10, store=store)
    order, _ = order_with(user, (drill, 2), (tape, 3), (glue, 1))
    return {"order": order, "store": store, "drill": drill, "tape": tape, "glue": glue}


def _reorder(client, order):
    return client.post(f"/api/orders/{order.order_number}/reorder/")


def test_reorder_adds_everything_at_current_prices(auth_client, user, past_order):
    past_order["tape"].price = Decimal("65.00")  # price dropped since the order
    past_order["tape"].save()
    res = _reorder(auth_client, past_order["order"])
    assert res.status_code == 200, res.json()
    body = res.json()
    assert {line["sku"]: line["added"] for line in body["added"]} == {
        past_order["drill"].sku: 2,
        past_order["tape"].sku: 3,
        past_order["glue"].sku: 1,
    }
    assert body["skipped"] == []
    lines = {line["sku"]: line for line in body["cart"]["items"]}
    assert lines[past_order["tape"].sku]["unit_price"] == "65.00"  # today's price, not the order's ₹70
    assert body["cart"]["totals"]["subtotal"] == "6245.00"


def test_reorder_caps_by_stock_limit_and_existing_cart_and_skips_unavailable(auth_client, user, past_order):
    store = past_order["store"]
    # Drill: only 1 left anywhere. Tape: order limit 4 and 2 already in the cart. Glue: unpublished.
    Inventory.objects.filter(store=store, variant=past_order["drill"]).update(available_quantity=1)
    past_order["tape"].product.max_order_quantity = 4
    past_order["tape"].product.save()
    add_item(user, past_order["tape"].id, 2)
    past_order["glue"].product.is_published = False
    past_order["glue"].product.save()

    body = _reorder(auth_client, past_order["order"]).json()
    added = {line["sku"]: line["added"] for line in body["added"]}
    assert added == {past_order["drill"].sku: 1, past_order["tape"].sku: 2}
    reasons = {line["sku"]: line["reason"] for line in body["skipped"]}
    assert reasons[past_order["drill"].sku].startswith("Only 1 added")
    assert reasons[past_order["tape"].sku].startswith("Only 2 added")
    assert reasons[past_order["glue"].sku] == "No longer sold."
    assert dict(CartItem.objects.filter(cart__user=user).values_list("variant__sku", "quantity")) == {
        past_order["drill"].sku: 1,
        past_order["tape"].sku: 4,
    }

    # Nothing more fits: a second reorder adds nothing and says why.
    Inventory.objects.filter(store=store, variant=past_order["drill"]).update(available_quantity=0)
    body = _reorder(auth_client, past_order["order"]).json()
    assert body["added"] == []
    reasons = {line["sku"]: line["reason"] for line in body["skipped"]}
    assert reasons[past_order["drill"].sku] == "Out of stock right now."
    assert reasons[past_order["tape"].sku] == "Your cart already has the most you can order."


def test_cancelled_orders_can_be_reordered_but_only_by_their_owner(
    auth_client, api_client, other_user, user, past_order
):
    cancel_order_by_customer(past_order["order"], user=user, reason="Changed my mind")
    assert _reorder(auth_client, past_order["order"]).status_code == 200
    api_client.force_authenticate(other_user)
    assert _reorder(api_client, past_order["order"]).status_code == 404
    assert not CartItem.objects.filter(cart__user=other_user).exists()
    detail = auth_client.get(f"/api/orders/{past_order['order'].order_number}/").json()
    assert detail["can_reorder"] is True


def test_store_manager_cannot_reorder_a_customers_order(staff_client, staff_user, past_order):
    past_order["store"].managers.add(staff_user)
    assert staff_client.get(f"/api/orders/{past_order['order'].order_number}/").status_code == 200
    assert _reorder(staff_client, past_order["order"]).status_code == 404
