from decimal import Decimal

import pytest

from apps.carts.models import CartItem
from apps.carts.services import add_item
from apps.core.exceptions import ServiceError
from apps.core.testing import add_stock, create_address, create_coupon, create_product, create_store
from apps.inventory.models import Inventory
from apps.offers.models import CouponRedemption
from apps.orders.models import Order, OrderStatus
from apps.orders.services import cancel_order_by_customer, place_order, transition_order
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db


@pytest.fixture
def stocked(user):
    store = create_store()
    _, drill = create_product(name="Drill", price="3000.00", mrp="3500.00", stock=5, store=store)
    _, tape = create_product(name="PTFE Tape", price="70.00", mrp="100.00", stock=50, store=store, gst_rate="5.00")
    return store, drill, tape


def _fill_cart(user, *pairs):
    for variant, qty in pairs:
        add_item(user, variant.id, qty)


def test_place_cod_order_snapshots_reserves_and_clears_cart(user, stocked):
    store, drill, tape = stocked
    address = create_address(user)
    _fill_cart(user, (drill, 1), (tape, 2))

    order, payment = place_order(user=user, address_id=address.id, payment_method="cod")

    assert order.status == OrderStatus.CONFIRMED  # COD auto-confirms
    assert [h.to_status for h in order.status_history.all()] == ["pending", "confirmed"]
    assert order.store == store
    assert order.subtotal == Decimal("3140.00")
    assert order.mrp_total == Decimal("3700.00")
    assert order.delivery_fee == Decimal("0.00")
    assert order.grand_total == Decimal("3140.00")
    # GST included in price: 3000*18/118 + 140*5/105
    assert order.tax_total == Decimal("457.63") + Decimal("6.67")
    assert order.address_snapshot["postal_code"] == "411001"
    assert {i.sku: (i.quantity, i.unit_price) for i in order.items.all()} == {
        drill.sku: (1, Decimal("3000.00")),
        tape.sku: (2, Decimal("70.00")),
    }
    inv = Inventory.objects.get(store=store, variant=drill)
    assert (inv.available_quantity, inv.reserved_quantity) == (4, 1)
    assert not CartItem.objects.filter(cart__user=user).exists()
    assert payment.provider == "cod" and payment.status == Payment.Status.PENDING


def test_order_items_are_immutable_snapshots(user, stocked):
    _, drill, _ = stocked
    _fill_cart(user, (drill, 1))
    order, _ = place_order(user=user, address_id=create_address(user).id, payment_method="cod")
    drill.product.name = "Renamed"
    drill.product.save()
    drill.price = Decimal("1.00")
    drill.save()
    item = order.items.get()
    assert item.product_name == "Drill" and item.unit_price == Decimal("3000.00")


def test_online_order_stays_pending_with_mock_payment_intent(user, stocked):
    _, _, tape = stocked
    _fill_cart(user, (tape, 1))
    order, payment = place_order(user=user, address_id=create_address(user).id, payment_method="online")
    assert order.status == OrderStatus.PENDING
    assert order.delivery_fee == Decimal("40.00") and order.grand_total == Decimal("110.00")
    assert payment.provider == "mock" and payment.status == Payment.Status.CREATED
    assert payment.metadata["client_payload"]["mock"] is True
    assert payment.provider_order_id.startswith("mock_order_")


def test_insufficient_stock_rolls_back_everything(user, stocked):
    store, drill, _ = stocked
    _fill_cart(user, (drill, 3))
    Inventory.objects.filter(store=store, variant=drill).update(available_quantity=2)  # sold elsewhere meanwhile
    with pytest.raises(ServiceError) as exc:
        place_order(user=user, address_id=create_address(user).id, payment_method="cod")
    assert getattr(exc.value, "error_code", "") == "insufficient_stock"
    assert Order.objects.count() == 0
    assert CartItem.objects.filter(cart__user=user).count() == 1
    assert Inventory.objects.get(store=store, variant=drill).reserved_quantity == 0


def test_items_split_across_stores_or_one_store_when_possible(user, settings):
    """Phase 9: an order ships from several stores when no single store has everything."""
    s1, s2 = create_store(), create_store()
    _, a = create_product(stock=5, store=s1)
    _, b = create_product(stock=5, store=s2)
    _fill_cart(user, (a, 1), (b, 1))
    settings.SPLIT_FULFILLMENT_ENABLED = False
    with pytest.raises(ServiceError) as exc:
        place_order(user=user, address_id=create_address(user).id, payment_method="cod")
    assert getattr(exc.value, "error_code", "") == "insufficient_stock"
    settings.SPLIT_FULFILLMENT_ENABLED = True
    order, _ = place_order(user=user, address_id=create_address(user, name="Asha 1").id, payment_method="cod")
    assert {(s.store_id, i.variant_id) for s in order.shipments.all() for i in s.items.all()} == {
        (s1.pk, a.pk),
        (s2.pk, b.pk),
    }
    add_stock(b, 5, store=s1)
    _fill_cart(user, (a, 1), (b, 1))
    order, _ = place_order(user=user, address_id=create_address(user, name="Asha 2").id, payment_method="cod")
    assert order.store == s1 and order.shipments.count() == 1


def test_coupon_applied_and_redeemed(user, stocked):
    _, drill, _ = stocked
    coupon = create_coupon("TOOLS10", value=Decimal("10"), max_discount_amount=Decimal("200"))
    _fill_cart(user, (drill, 1))
    order, _ = place_order(user=user, address_id=create_address(user).id, payment_method="cod", coupon_code="tools10")
    assert order.discount_total == Decimal("200.00")  # 10% of 3000 capped at 200
    assert order.grand_total == Decimal("2800.00")
    assert order.coupon_code == "TOOLS10"
    coupon.refresh_from_db()
    assert coupon.used_count == 1
    assert CouponRedemption.objects.filter(order=order, discount_amount=Decimal("200.00")).exists()


def test_valid_and_invalid_transitions(user, staff_user, stocked):
    store, drill, _ = stocked
    _fill_cart(user, (drill, 2))
    order, _ = place_order(user=user, address_id=create_address(user).id, payment_method="cod")

    with pytest.raises(ServiceError) as exc:
        transition_order(order, OrderStatus.DELIVERED, actor=staff_user)
    assert getattr(exc.value, "error_code", "") == "invalid_transition"

    for status in ("processing", "packed", "assigned", "picked_up"):
        order = transition_order(order, status, actor=staff_user)
    inv = Inventory.objects.get(store=store, variant=drill)
    assert (inv.available_quantity, inv.reserved_quantity) == (3, 0)  # reserved stock became a sale

    with pytest.raises(ServiceError):
        transition_order(order, OrderStatus.CANCELLED, actor=staff_user)  # too late to cancel
    for status in ("out_for_delivery", "delivered"):
        order = transition_order(order, status, actor=staff_user)
    assert order.delivered_at is not None
    assert order.status_history.count() == 8


def test_customer_cancel_releases_stock_and_voids_payment(user, stocked):
    store, drill, _ = stocked
    _fill_cart(user, (drill, 2))
    order, payment = place_order(user=user, address_id=create_address(user).id, payment_method="cod")
    order = cancel_order_by_customer(order, user=user, reason="Ordered by mistake")
    assert order.status == OrderStatus.CANCELLED and order.cancellation_reason == "Ordered by mistake"
    inv = Inventory.objects.get(store=store, variant=drill)
    assert (inv.available_quantity, inv.reserved_quantity) == (5, 0)
    payment.refresh_from_db()
    assert payment.status == Payment.Status.CANCELLED


def test_orders_api_flow_and_permissions(auth_client, api_client, staff_client, staff_user, user, other_user, stocked):
    store, _, tape = stocked
    address = create_address(user)
    auth_client.post("/api/cart/items/", {"variant_id": tape.id, "quantity": 2}, format="json")

    assert api_client.post("/api/orders/", {}, format="json").status_code == 401
    other_address = create_address(other_user)
    res = auth_client.post("/api/orders/", {"address_id": other_address.id, "payment_method": "cod"}, format="json")
    assert res.status_code == 404  # cannot ship to someone else's address

    # Client-sent prices are not accepted fields and are ignored.
    res = auth_client.post(
        "/api/orders/", {"address_id": address.id, "payment_method": "cod", "grand_total": "1.00"}, format="json"
    )
    assert res.status_code == 201, res.json()
    number = res.json()["order_number"]
    assert res.json()["grand_total"] == "180.00"

    assert auth_client.get("/api/orders/").json()["count"] == 1
    assert (
        auth_client.post(f"/api/orders/{number}/transition/", {"status": "processing"}, format="json").status_code
        == 403
    )
    url = f"/api/orders/{number}/transition/"
    # A manager of a different store can't even see the order.
    assert staff_client.post(url, {"status": "processing"}, format="json").status_code == 404
    store.managers.add(staff_user)
    assert staff_client.post(url, {"status": "processing"}, format="json").status_code == 200

    other = api_client
    other.force_authenticate(other_user)
    assert other.get(f"/api/orders/{number}/").status_code == 404
    assert staff_client.get("/api/orders/").json()["count"] == 1

    res = auth_client.post(f"/api/orders/{number}/cancel/", {"reason": "Changed my mind"}, format="json")
    assert res.status_code == 200 and res.json()["status"] == "cancelled"
    res = auth_client.post(f"/api/orders/{number}/cancel/", {"reason": "again"}, format="json")
    assert res.status_code == 409


def test_empty_cart_cannot_be_ordered(auth_client, user):
    address = create_address(user)
    res = auth_client.post("/api/orders/", {"address_id": address.id, "payment_method": "cod"}, format="json")
    assert res.status_code == 400 and res.json()["error"]["code"] == "cart_empty"
