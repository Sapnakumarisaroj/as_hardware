"""Phase 9: orders carry the fulfilment plan — store(s), delivery type, estimate and window — and
stock is reserved, released, sold and restocked at the store each line ships from."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.carts.services import add_item
from apps.core.exceptions import ServiceError
from apps.core.testing import add_stock, create_address, create_product
from apps.delivery.tests.helpers import address_at, store_at, zone_for
from apps.inventory.models import Inventory
from apps.notifications.models import Notification
from apps.orders.delivery_info import delivery_message, describe_delivery
from apps.orders.models import Order, OrderShipment, OrderStatus
from apps.orders.returns import approve_return, receive_return, request_return
from apps.orders.services import cancel_order_by_customer, place_order

from .helpers import deliver, pay
from .test_concurrency import _checkout, _customers, _error_codes, _ok, run_concurrently

pytestmark = pytest.mark.django_db


def _levels(store, variant):
    inv = Inventory.objects.get(store=store, variant=variant)
    return inv.available_quantity, inv.reserved_quantity


def _order(user, address, *pairs, method="cod", **kwargs):
    for variant, quantity in pairs:
        add_item(user, variant.id, quantity)
    return place_order(user=user, address_id=address.id, payment_method=method, **kwargs)


@pytest.fixture
def shop(user):
    store = store_at(0, avg_prep_minutes=10)
    zone = zone_for(store)
    _, drill = create_product(name="Drill", price="300.00", mrp="350.00", stock=5, store=store)
    return {"store": store, "zone": zone, "drill": drill}


# --- The promise stored on the order -------------------------------------------------------------


def test_order_records_store_estimate_and_window(user, shop, django_capture_on_commit_callbacks):
    before = timezone.now()
    with django_capture_on_commit_callbacks(execute=True):
        order, _ = _order(user, address_at(user, 2), (shop["drill"], 1))
    assert order.store == shop["store"] and order.delivery_type == "fast"
    assert order.eta_minutes == 24
    assert before + timedelta(minutes=24) <= order.estimated_delivery_at <= timezone.now() + timedelta(minutes=24)
    assert order.estimated_ready_at == order.estimated_delivery_at - timedelta(minutes=14)
    assert order.delivery_window_start == order.estimated_delivery_at
    assert order.delivery_window_end == order.estimated_delivery_at + timedelta(minutes=15)

    shipment = order.shipments.get()
    assert (shipment.store, shipment.zone, shipment.sequence) == (shop["store"], shop["zone"], 1)
    assert (shipment.prep_minutes, shipment.wait_minutes, shipment.travel_minutes) == (10, 0, 10)
    assert shipment.eta_minutes == 24 and shipment.eta_source == "haversine"
    assert shipment.distance_km == Decimal("2.70")
    assert order.items.get().shipment == shipment

    body = Notification.objects.filter(user=user, event="order.confirmed").first().body
    assert "Estimated delivery: Delivery in 24 minutes." in body


def test_standard_order_has_a_window(user, shop):
    shop["store"].own_riders = 0
    shop["store"].save()
    order, _ = _order(user, address_at(user, 2), (shop["drill"], 1))
    assert order.delivery_type == "standard"
    assert order.delivery_window_end - order.delivery_window_start == timedelta(hours=2)
    assert order.delivery_window_start.minute in (0, 30)
    assert delivery_message(order).startswith("🚚 Standard delivery · ")
    info = describe_delivery(order)
    assert info["fast"] is False and info["type_label"] == "Standard delivery" and " – " in info["label"]


def test_out_of_zone_address_cannot_order(user, shop):
    address = address_at(user, 9, postal_code="411014")
    with pytest.raises(ServiceError) as exc:
        _order(user, address, (shop["drill"], 1))
    assert exc.value.error_code == "not_deliverable" and exc.value.details == {"reason": "out_of_zone"}
    assert not Order.objects.exists() and _levels(shop["store"], shop["drill"]) == (5, 0)


def test_zone_fee_is_charged_and_checked_against_the_preview(user, shop, auth_client):
    zone = shop["zone"]
    zone.delivery_fee_override, zone.free_delivery_min_order = Decimal("25"), Decimal("999")
    zone.save()
    address = address_at(user, 2)
    add_item(user, shop["drill"].id, 2)  # 600: free under the global rule, ₹25 in this zone
    preview = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    assert preview["delivery"]["fee"] == "25.00" and preview["delivery"]["amount_to_free_delivery"] == "399.00"
    assert preview["totals"]["delivery_fee"] == "25.00" and preview["totals"]["grand_total"] == "625.00"
    order, _ = place_order(user=user, address_id=address.id, payment_method="cod", expected_total=Decimal("625.00"))
    assert order.delivery_fee == Decimal("25.00") and order.grand_total == Decimal("625.00")


def test_delivery_message_follows_the_order(user, shop, admin_user):
    order, _ = _order(user, address_at(user, 2), (shop["drill"], 1))
    now = order.created_at
    assert delivery_message(order, now).startswith("⚡ Delivery in 24 minutes (by about ")
    assert describe_delivery(order, now + timedelta(minutes=10))["minutes_left"] == 14
    late = describe_delivery(order, now + timedelta(minutes=40))
    assert late["minutes_left"] == 0 and late["label"] == "Arriving any minute"
    order.status = OrderStatus.OUT_FOR_DELIVERY
    assert delivery_message(order, now + timedelta(minutes=10)).startswith("Out for delivery · Delivery in 14 minutes")
    order.status = OrderStatus.CONFIRMED
    delivered = deliver(order, admin_user)
    assert delivery_message(delivered) == "Delivered"
    assert describe_delivery(delivered)["minutes_left"] is None


def test_online_order_gets_a_fresh_estimate_when_paid(user, shop):
    order, payment = _order(user, address_at(user, 2), (shop["drill"], 1), method="online")
    assert delivery_message(order) == "Complete the payment to confirm your order."
    placed_at = timezone.now() - timedelta(minutes=20)
    Order.objects.filter(pk=order.pk).update(estimated_delivery_at=placed_at + timedelta(minutes=24))
    OrderShipment.objects.filter(order=order).update(estimated_delivery_at=placed_at + timedelta(minutes=24))
    pay(order, payment)
    order.refresh_from_db()
    assert order.status == OrderStatus.CONFIRMED and order.eta_minutes == 24
    assert order.estimated_delivery_at > timezone.now() + timedelta(minutes=23)
    assert order.shipments.get().estimated_delivery_at == order.estimated_delivery_at


# --- What the customer sees ----------------------------------------------------------------------


def test_customer_sees_delivery_information(user, shop, auth_client, other_user, api_client):
    order, _ = _order(user, address_at(user, 2), (shop["drill"], 1))
    detail = auth_client.get(f"/api/orders/{order.order_number}/").json()
    delivery = detail["delivery"]
    assert delivery["type"] == "fast" and delivery["fast"] is True and delivery["eta_minutes"] == 24
    assert delivery["label"].startswith("Delivery in ") and delivery["minutes_left"] in (23, 24)
    assert delivery["estimated_ready_at"] and delivery["window_start"] and delivery["window_end"]
    assert detail["status"] == "confirmed" and detail["delivery_message"].startswith("⚡ Delivery in ")
    (shipment,) = detail["shipments"]
    assert shipment["store_name"] == shop["store"].name and shipment["prep_minutes"] == 10
    assert shipment["item_ids"] == [detail["items"][0]["id"]] and shipment["distance_km"] == "2.70"
    # Internal planning numbers stay internal.
    assert "wait_minutes" not in shipment and "zone" not in shipment

    row = auth_client.get("/api/orders/").json()["results"][0]
    assert row["delivery"]["type"] == "fast" and row["delivery_message"] == detail["delivery_message"]

    api_client.force_authenticate(other_user)
    assert api_client.get(f"/api/orders/{order.order_number}/").status_code == 404


def test_orders_placed_before_phase_9_keep_the_old_wording(user, shop, auth_client):
    order, _ = _order(user, address_at(user, 2), (shop["drill"], 1))
    Order.objects.filter(pk=order.pk).update(
        delivery_type="", eta_minutes=None, estimated_delivery_at=None, estimated_ready_at=None,
        delivery_window_start=None, delivery_window_end=None,
    )  # fmt: skip
    detail = auth_client.get(f"/api/orders/{order.order_number}/").json()
    assert detail["delivery"]["type"] is None and detail["delivery"]["label"] == ""
    assert "confirmed after your order is placed" in detail["delivery_message"]


# --- Several stores: stock follows the shipment --------------------------------------------------


@pytest.fixture
def two_stores(user):
    a, b = store_at(0), store_at(3)
    zone_for(a, radius="10")
    zone_for(b, radius="10")
    _, drill = create_product(name="Drill", price="300.00", stock=5, store=a)
    _, tape = create_product(name="Tape", price="50.00", stock=5, store=b)
    return {"a": a, "b": b, "drill": drill, "tape": tape, "address": address_at(user, 1)}


def test_split_order_reserves_each_line_at_its_own_store(user, two_stores):
    s = two_stores
    order, _ = _order(user, s["address"], (s["drill"], 2), (s["tape"], 3))
    assert order.shipments.count() == 2 and order.store in (s["a"], s["b"])
    assert _levels(s["a"], s["drill"]) == (3, 2) and _levels(s["b"], s["tape"]) == (2, 3)
    assert not Inventory.objects.filter(store=s["a"], variant=s["tape"]).exists()
    by_store = {sh.store_id: [i.sku for i in sh.items.all()] for sh in order.shipments.all()}
    assert by_store == {s["a"].pk: [s["drill"].sku], s["b"].pk: [s["tape"].sku]}
    assert order.estimated_delivery_at == max(sh.estimated_delivery_at for sh in order.shipments.all())


def test_split_order_cancel_deliver_and_return_use_the_right_store(user, two_stores, admin_user):
    s = two_stores
    order, _ = _order(user, s["address"], (s["drill"], 2), (s["tape"], 3))
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    assert _levels(s["a"], s["drill"]) == (5, 0) and _levels(s["b"], s["tape"]) == (5, 0)

    order, _ = _order(user, s["address"], (s["drill"], 2), (s["tape"], 3))
    order = deliver(order, admin_user)
    assert _levels(s["a"], s["drill"]) == (3, 0) and _levels(s["b"], s["tape"]) == (2, 0)

    tape_item = order.items.get(sku=s["tape"].sku)
    ret = request_return(order, user=user, items=[{"order_item_id": tape_item.id, "quantity": 1}], reason="damaged")
    approve_return(ret, actor=admin_user)
    receive_return(ret, actor=admin_user, restock=True)
    assert _levels(s["b"], s["tape"]) == (3, 0)
    assert not Inventory.objects.filter(store=s["a"], variant=s["tape"]).exists()


def test_split_failure_rolls_back_every_store(user, two_stores):
    s = two_stores
    add_item(user, s["drill"].id, 2)
    add_item(user, s["tape"].id, 3)
    # The tape sells out after the customer filled the cart.
    Inventory.objects.filter(store=s["b"], variant=s["tape"]).update(available_quantity=1)
    with pytest.raises(ServiceError) as exc:
        place_order(user=user, address_id=s["address"].id, payment_method="cod")
    assert exc.value.error_code == "insufficient_stock"
    assert not Order.objects.exists() and not OrderShipment.objects.exists()
    assert _levels(s["a"], s["drill"]) == (5, 0) and _levels(s["b"], s["tape"]) == (1, 0)


def test_plan_gone_stale_fails_cleanly(user, shop, monkeypatch):
    """The plan only *reads* stock. If the stock is gone by the time the rows are locked, the
    reservation fails and nothing is written."""
    from apps.orders import services

    real_plan = services._plan

    def plan_then_sell_out(address, requirements):
        plan = real_plan(address, requirements)
        Inventory.objects.filter(store=shop["store"]).update(available_quantity=0)
        return plan

    monkeypatch.setattr(services, "_plan", plan_then_sell_out)
    with pytest.raises(ServiceError) as exc:
        _order(user, address_at(user, 2), (shop["drill"], 1))
    assert exc.value.error_code == "insufficient_stock"
    assert not Order.objects.exists() and not OrderShipment.objects.exists()


# --- Concurrency ---------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_orders_spread_over_stores_without_overselling():
    a, b = store_at(0, zone=True), store_at(1, zone=True)
    _, variant = create_product(stock=1, store=a)
    add_stock(variant, 1, store=b)
    buyers = _customers(4)
    for buyer in buyers:
        add_item(buyer, variant.id, 1)

    results = run_concurrently(*[_checkout(buyer) for buyer in buyers])

    assert len(_ok(results)) == 2 and _error_codes(results) == ["insufficient_stock"] * 2
    assert sorted(o.store_id for o, _ in _ok(results)) == [a.pk, b.pk]
    for store in (a, b):
        assert _levels(store, variant) == (0, 1)
    assert OrderShipment.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_concurrent_split_orders_never_oversell():
    a, b = store_at(0, zone=True), store_at(1, zone=True)
    _, drill = create_product(name="Drill", stock=2, store=a)
    _, tape = create_product(name="Tape", stock=1, store=b)
    buyers = _customers(3)
    for buyer in buyers:
        add_item(buyer, drill.id, 1)
        add_item(buyer, tape.id, 1)

    results = run_concurrently(*[_checkout(buyer) for buyer in buyers])

    assert len(_ok(results)) == 1 and _error_codes(results) == ["insufficient_stock"] * 2
    assert _levels(a, drill) == (1, 1) and _levels(b, tape) == (0, 1)
    assert Order.objects.count() == 1 and OrderShipment.objects.count() == 2


def test_address_without_coordinates_is_served_by_pin_but_cannot_be_ordered_to(user):
    """The engine still plans a pinless location by its PIN (the PIN-only delivery check uses this), but an
    order needs the address's map pin: the delivery charge is measured to it."""
    from apps.delivery.fulfillment import plan_fulfillment
    from apps.delivery.locations import resolve_location

    store = store_at(0, postal_code="411038")
    zone_for(store, postal_codes="411052")
    _, variant = create_product(stock=5, store=store)
    near = create_address(user, postal_code="411052", latitude=None, longitude=None)
    plan = plan_fulfillment({variant.id: 1}, resolve_location(address=near))
    assert plan.deliverable and plan.shipments[0].estimate.eta_source == "zone"
    far = create_address(user, name="Far", postal_code="411014", latitude=None, longitude=None)
    assert not plan_fulfillment({variant.id: 1}, resolve_location(address=far)).deliverable
    with pytest.raises(ServiceError) as exc:
        _order(user, near, (variant, 1))
    assert exc.value.error_code == "address_location_required"
