"""Phase 5: checkout preview, order placement safety, mock payments, cancellation, notifications,
and access control for the customer shopping-to-order flow."""

from decimal import Decimal
from unittest import mock

import pytest

from apps.carts.models import CartItem
from apps.core.testing import add_stock, create_address, create_coupon, create_product, create_store
from apps.delivery.models import DeliveryZone
from apps.inventory.models import Inventory
from apps.notifications.models import Notification
from apps.offers.models import CouponRedemption
from apps.orders.models import Order
from apps.payments.models import Payment, Refund

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(user):
    store = create_store()
    DeliveryZone.objects.create(store=store, name="5 km", radius_km=Decimal("5"))
    _, drill = create_product(name="Drill", price="3000.00", mrp="3500.00", stock=5, store=store)
    _, tape = create_product(name="PTFE Tape", price="70.00", mrp="100.00", stock=50, store=store, gst_rate="5.00")
    return {"store": store, "drill": drill, "tape": tape, "address": create_address(user)}


def _add(client, variant, quantity=1):
    res = client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": quantity}, format="json")
    assert res.status_code == 201, res.json()
    return res.json()


def _preview(client, **body):
    res = client.post("/api/checkout/preview/", body, format="json")
    assert res.status_code == 200, res.json()
    return res.json()


def _order(client, address, method="cod", **extra):
    headers = {}
    if key := extra.pop("key", None):
        headers["HTTP_IDEMPOTENCY_KEY"] = key
    return client.post(
        "/api/orders/", {"address_id": address.id, "payment_method": method, **extra}, format="json", **headers
    )


def _pay(client, order_json, outcome):
    payment = next(p for p in order_json["payments"] if p["status"] == "created")
    payload = {"mock_signature": payment["client_payload"]["mock_signature"], "mock_outcome": outcome}
    return client.post(f"/api/payments/{payment['public_id']}/verify/", {"payload": payload}, format="json")


# --- Cart ----------------------------------------------------------------------------------


def test_cart_lines_expose_display_fields_and_server_totals(auth_client, shop):
    cart = _add(auth_client, shop["tape"], 2)
    line = cart["items"][0]
    assert line["brand_name"] == "Test Brand"
    assert line["line_total"] == "140.00" and line["line_mrp_total"] == "200.00"
    assert line["discount_percent"] == "30.00"
    assert line["max_order_quantity"] >= 1 and "attributes" in line and "image" in line
    assert cart["totals"]["delivery_fee"] == "40.00" and cart["totals"]["grand_total"] == "180.00"


def test_cart_update_remove_and_stock_validation(auth_client, shop):
    cart = _add(auth_client, shop["drill"], 1)
    item_id = cart["items"][0]["id"]
    res = auth_client.patch(f"/api/cart/items/{item_id}/", {"quantity": 6}, format="json")
    assert res.status_code == 409 and res.json()["error"]["code"] == "insufficient_stock"
    assert "Only 5" in res.json()["error"]["message"]
    assert (
        auth_client.patch(f"/api/cart/items/{item_id}/", {"quantity": 3}, format="json").json()["items"][0]["quantity"]
        == 3
    )
    assert auth_client.delete(f"/api/cart/items/{item_id}/").json()["items"] == []


# --- Checkout preview --------------------------------------------------------------------


def test_preview_valid_checkout_with_delivery_info(auth_client, shop):
    _add(auth_client, shop["tape"], 2)
    data = _preview(auth_client, address_id=shop["address"].id)
    assert data["can_place_order"] is True and data["blocking_issues"] == []
    assert data["totals"]["grand_total"] == "180.00"
    delivery = data["delivery"]
    assert delivery["available"] is True
    assert delivery["fee"] == "40.00" and delivery["free_delivery_min_order"] == "499.00"
    assert delivery["amount_to_free_delivery"] == "359.00"
    # Phase 9: a real estimate. No rider is on duty at the test store, so it is standard delivery.
    assert delivery["delivery_type"] == "standard" and delivery["fast_delivery_possible"] is False
    assert isinstance(delivery["eta_minutes"], int) and delivery["label"]
    assert "No delivery partner" in delivery["fast_unavailable_reason"]
    assert delivery["store_name"] == shop["store"].name and delivery["shipments"][0]["line_count"] == 1
    assert {m["value"] for m in data["payment_methods"]} == {"online", "cod"}


def test_preview_requires_address_and_rejects_foreign_address(auth_client, other_user, shop):
    _add(auth_client, shop["tape"])
    data = _preview(auth_client)
    assert data["can_place_order"] is False
    assert [i["code"] for i in data["blocking_issues"]] == ["address_required"]
    foreign = create_address(other_user)
    codes = [i["code"] for i in _preview(auth_client, address_id=foreign.id)["blocking_issues"]]
    assert codes == ["address_not_found"]


def test_preview_empty_cart(auth_client, shop):
    data = _preview(auth_client, address_id=shop["address"].id)
    assert data["can_place_order"] is False and data["blocking_issues"][0]["code"] == "cart_empty"


def test_preview_stock_conflict_blocks_checkout(auth_client, shop):
    _add(auth_client, shop["drill"], 3)
    Inventory.objects.filter(variant=shop["drill"]).update(available_quantity=1)  # sold elsewhere
    data = _preview(auth_client, address_id=shop["address"].id)
    assert data["can_place_order"] is False
    assert data["blocking_issues"][0]["code"] == "cart_item_unavailable"
    assert data["cart"]["items"][0]["in_stock"] is False
    res = _order(auth_client, shop["address"])
    assert res.status_code == 409 and Order.objects.count() == 0


def test_preview_coupon_valid_and_invalid_reasons(auth_client, user, shop):
    create_coupon("TOOLS10", value=Decimal("10"), max_discount_amount=Decimal("200"))
    create_coupon("BIG", value=Decimal("5"), min_order_value=Decimal("5000"))
    _add(auth_client, shop["drill"])
    ok = _preview(auth_client, address_id=shop["address"].id, coupon_code="tools10")
    assert ok["coupon"]["discount"] == "200.00" and ok["totals"]["grand_total"] == "2800.00"
    bad = _preview(auth_client, address_id=shop["address"].id, coupon_code="BIG")
    assert bad["coupon"] is None and bad["coupon_error"]["code"] == "coupon_min_order"
    assert "minimum order" in bad["coupon_error"]["message"]
    assert bad["can_place_order"] is False and bad["totals"]["grand_total"] == "3000.00"
    unknown = _preview(auth_client, address_id=shop["address"].id, coupon_code="NOPE")
    assert unknown["coupon_error"]["code"] == "invalid_coupon"
    res = _order(auth_client, shop["address"], coupon_code="NOPE")
    assert res.status_code == 400 and res.json()["error"]["code"] == "invalid_coupon"


# --- Placing orders ------------------------------------------------------------------------


def test_changed_price_is_caught_before_ordering(auth_client, shop):
    _add(auth_client, shop["tape"], 2)
    shown = _preview(auth_client, address_id=shop["address"].id)["totals"]["grand_total"]
    shop["tape"].price = Decimal("80.00")
    shop["tape"].save()
    res = _order(auth_client, shop["address"], expected_total=shown)
    assert res.status_code == 409 and res.json()["error"]["code"] == "totals_changed"
    assert res.json()["error"]["details"]["grand_total"] == "200.00"
    assert Order.objects.count() == 0 and CartItem.objects.count() == 1
    cart = auth_client.get("/api/cart/").json()
    assert cart["items"][0]["price_changed"] is True
    res = _order(auth_client, shop["address"], expected_total="200.00")
    assert res.status_code == 201 and res.json()["grand_total"] == "200.00"


def test_duplicate_submission_with_same_key_creates_one_order(auth_client, shop):
    _add(auth_client, shop["tape"], 2)
    first = _order(auth_client, shop["address"], key="checkout-1234abcd")
    assert first.status_code == 201
    again = _order(auth_client, shop["address"], key="checkout-1234abcd")
    assert again.status_code == 200 and again["Idempotent-Replayed"] == "true"
    assert again.json()["order_number"] == first.json()["order_number"]
    assert Order.objects.count() == 1
    assert Inventory.objects.get(variant=shop["tape"]).reserved_quantity == 2


def test_double_click_without_key_cannot_order_twice(auth_client, shop):
    _add(auth_client, shop["tape"])
    assert _order(auth_client, shop["address"]).status_code == 201
    res = _order(auth_client, shop["address"])
    assert res.status_code == 400 and res.json()["error"]["code"] == "cart_empty"
    assert Order.objects.count() == 1


def test_idempotency_keys_are_per_customer(auth_client, api_client, other_user, shop):
    _add(auth_client, shop["tape"])
    assert _order(auth_client, shop["address"], key="shared-key-0001").status_code == 201
    api_client.force_authenticate(other_user)
    _add(api_client, shop["tape"])
    res = _order(api_client, create_address(other_user), key="shared-key-0001")
    assert res.status_code == 201 and Order.objects.count() == 2


def test_failure_after_stock_reservation_rolls_everything_back(auth_client, shop):
    coupon = create_coupon("TOOLS10")
    _add(auth_client, shop["drill"])
    with mock.patch("apps.orders.services.create_payment_for_order", side_effect=RuntimeError("gateway down")):
        res = _order(auth_client, shop["address"], method="online", coupon_code="TOOLS10")
    assert res.status_code == 500 and res.json()["error"]["code"] == "server_error"
    assert Order.objects.count() == 0 and Payment.objects.count() == 0
    inv = Inventory.objects.get(variant=shop["drill"])
    assert (inv.available_quantity, inv.reserved_quantity) == (5, 0)
    coupon.refresh_from_db()
    assert coupon.used_count == 0 and not CouponRedemption.objects.exists()
    assert CartItem.objects.count() == 1


def test_order_snapshot_totals_history_and_notifications(auth_client, user, shop, django_capture_on_commit_callbacks):
    _add(auth_client, shop["drill"])
    _add(auth_client, shop["tape"], 2)
    with django_capture_on_commit_callbacks(execute=True):
        res = _order(auth_client, shop["address"], customer_note="Call before delivery")
    data = res.json()
    assert data["status"] == "confirmed" and data["payment_status"] == "pending"
    assert (data["subtotal"], data["delivery_fee"], data["grand_total"]) == ("3140.00", "0.00", "3140.00")
    assert data["tax_total"] == "464.30"
    assert [h["to_status"] for h in data["status_history"]] == ["pending", "confirmed"]
    assert data["address_snapshot"]["city"] == "Pune" and data["can_cancel"] is True
    assert {i["sku"]: i["line_total"] for i in data["items"]} == {
        shop["drill"].sku: "3000.00",
        shop["tape"].sku: "140.00",
    }
    notes = Notification.objects.filter(user=user, event="order.confirmed")
    assert {n.channel for n in notes} == {"in_app", "email"}
    assert all(n.status == "sent" for n in notes)


def test_rolled_back_order_sends_no_notification(auth_client, shop, django_capture_on_commit_callbacks):
    _add(auth_client, shop["drill"], 3)
    Inventory.objects.filter(variant=shop["drill"]).update(available_quantity=1)
    with django_capture_on_commit_callbacks(execute=True):
        assert _order(auth_client, shop["address"]).status_code == 409
    assert not Notification.objects.exists()


# --- Payments --------------------------------------------------------------------------------


def test_mock_payment_success_confirms_order(auth_client, shop):
    _add(auth_client, shop["tape"], 2)
    order = _order(auth_client, shop["address"], method="online").json()
    assert order["status"] == "pending" and order["payments"][0]["client_payload"]["mock"] is True
    res = _pay(auth_client, order, "success")
    assert res.status_code == 200
    paid = res.json()
    assert (paid["status"], paid["payment_status"]) == ("confirmed", "paid")
    assert paid["payments"][0]["status"] == "captured" and paid["payments"][0]["client_payload"] == {}
    # Verifying again is harmless (idempotent) and never captures twice.
    payment = Payment.objects.get()
    payload = {"mock_signature": order["payments"][0]["client_payload"]["mock_signature"], "mock_outcome": "success"}
    res = auth_client.post(f"/api/payments/{payment.public_id}/verify/", {"payload": payload}, format="json")
    assert res.status_code == 200
    assert Payment.objects.filter(status="captured").count() == 1


def test_mock_payment_failure_then_retry(auth_client, shop):
    _add(auth_client, shop["tape"], 2)
    order = _order(auth_client, shop["address"], method="online").json()
    failed = _pay(auth_client, order, "failed").json()
    assert (failed["status"], failed["payment_status"]) == ("pending", "failed")
    assert failed["payments"][0]["failure_reason"] and failed["can_retry_payment"] is True
    retried = auth_client.post(f"/api/orders/{order['order_number']}/retry-payment/").json()
    assert retried["payment_status"] == "pending" and retried["can_retry_payment"] is False
    assert _pay(auth_client, retried, "success").json()["status"] == "confirmed"


def test_mock_payment_cancelled_keeps_order_pending(auth_client, shop):
    _add(auth_client, shop["tape"])
    order = _order(auth_client, shop["address"], method="online").json()
    data = _pay(auth_client, order, "cancelled").json()
    assert (data["status"], data["payment_status"]) == ("pending", "pending")
    assert data["payments"][0]["status"] == "cancelled" and data["can_retry_payment"] is True
    # A closed attempt cannot be verified again.
    payment = Payment.objects.get()
    res = auth_client.post(
        f"/api/payments/{payment.public_id}/verify/", {"payload": {"mock_outcome": "success"}}, format="json"
    )
    assert res.status_code == 409


def test_forged_mock_signature_is_rejected(auth_client, shop):
    _add(auth_client, shop["tape"])
    order = _order(auth_client, shop["address"], method="online").json()
    payment = order["payments"][0]
    res = auth_client.post(
        f"/api/payments/{payment['public_id']}/verify/",
        {"payload": {"mock_signature": "forged", "mock_outcome": "success"}},
        format="json",
    )
    assert res.json()["payment_status"] == "failed" and res.json()["status"] == "pending"


def test_cod_order_confirms_without_payment_step(auth_client, shop):
    _add(auth_client, shop["tape"])
    data = _order(auth_client, shop["address"]).json()
    assert (data["status"], data["payment_method"], data["payment_status"]) == ("confirmed", "cod", "pending")
    assert data["payments"][0]["provider"] == "cod" and data["can_retry_payment"] is False


# --- Cancellation ------------------------------------------------------------------------------


def test_cancel_paid_order_creates_pending_refund_and_releases_coupon(auth_client, user, shop):
    coupon = create_coupon("TOOLS10", value=Decimal("10"), max_discount_amount=Decimal("200"), per_customer_limit=1)
    _add(auth_client, shop["drill"])
    order = _order(auth_client, shop["address"], method="online", coupon_code="TOOLS10").json()
    _pay(auth_client, order, "success")
    res = auth_client.post(
        f"/api/orders/{order['order_number']}/cancel/", {"reason": "Found it cheaper"}, format="json"
    )
    data = res.json()
    assert data["status"] == "cancelled" and data["cancellation_reason"] == "Found it cheaper"
    assert data["refunds"][0]["status"] == "pending" and data["refunds"][0]["amount"] == "2800.00"
    assert Refund.objects.get().processed_at is None  # no fake "refunded"
    assert data["status_history"][-1]["to_status"] == "cancelled"
    inv = Inventory.objects.get(variant=shop["drill"])
    assert (inv.available_quantity, inv.reserved_quantity) == (5, 0)
    coupon.refresh_from_db()
    assert coupon.used_count == 0 and not CouponRedemption.objects.exists()
    _add(auth_client, shop["drill"])  # the coupon can be used again
    assert _order(auth_client, shop["address"], coupon_code="TOOLS10").status_code == 201


def test_cancellation_only_while_state_allows(auth_client, admin_user, shop):
    from apps.orders.services import transition_order

    _add(auth_client, shop["tape"])
    number = _order(auth_client, shop["address"]).json()["order_number"]
    order = Order.objects.get(order_number=number)
    for status in ("processing", "packed"):
        order = transition_order(order, status, actor=admin_user)
    detail = auth_client.get(f"/api/orders/{number}/").json()
    assert detail["can_cancel"] is False
    res = auth_client.post(f"/api/orders/{number}/cancel/", {"reason": "Too slow"}, format="json")
    assert res.status_code == 409 and res.json()["error"]["code"] == "invalid_transition"
    assert auth_client.post(f"/api/orders/{number}/cancel/", {}, format="json").status_code == 400


# --- Security ----------------------------------------------------------------------------------


def test_customer_cannot_change_status_totals_or_payment(auth_client, shop):
    _add(auth_client, shop["tape"])
    order = _order(auth_client, shop["address"], method="online").json()
    number = order["order_number"]
    url = f"/api/orders/{number}/"
    assert auth_client.patch(url, {"status": "delivered"}, format="json").status_code == 405
    assert auth_client.put(url, {"grand_total": "1.00"}, format="json").status_code == 405
    assert auth_client.delete(url).status_code == 405
    res = auth_client.post(f"{url}transition/", {"status": "delivered"}, format="json")
    assert res.status_code == 403
    res = auth_client.post(f"{url}cancel/", {"reason": "x", "status": "delivered"}, format="json")
    assert res.json()["status"] == "cancelled"  # extra fields ignored; only the allowed action happens
    fresh = Order.objects.get(order_number=number)
    assert fresh.grand_total == Decimal("110.00") and fresh.payment_status == "pending"


def test_orders_and_payments_are_private(auth_client, api_client, other_user, shop):
    _add(auth_client, shop["tape"])
    order = _order(auth_client, shop["address"], method="online").json()
    number = order["order_number"]
    api_client.force_authenticate(other_user)
    assert api_client.get("/api/orders/").json()["count"] == 0
    assert api_client.get(f"/api/orders/{number}/").status_code == 404
    assert api_client.post(f"/api/orders/{number}/cancel/", {"reason": "x"}, format="json").status_code == 404
    assert api_client.post(f"/api/orders/{number}/retry-payment/").status_code == 404
    assert _pay(api_client, order, "success").status_code == 404
    assert Order.objects.get(order_number=number).status == "pending"


def test_anonymous_users_cannot_checkout(api_client, shop):
    assert api_client.post("/api/checkout/preview/", {}, format="json").status_code == 401
    assert api_client.post("/api/orders/", {}, format="json").status_code == 401
    assert api_client.get("/api/cart/").status_code == 401


def test_order_history_is_newest_first_with_summary_fields(auth_client, shop):
    for _ in range(2):
        _add(auth_client, shop["tape"], 2)
        _order(auth_client, shop["address"])
    page = auth_client.get("/api/orders/").json()
    assert page["count"] == 2
    first, second = page["results"]
    assert first["created_at"] >= second["created_at"]
    assert first["item_count"] == 2 and first["item_names"] == ["PTFE Tape"]
    assert "confirmed" in first["delivery_message"] or first["delivery_message"]


def test_quote_splits_across_stores_only_when_allowed(auth_client, user, settings):
    """Phase 9: no single store has both items → two shipments (or blocked when splitting is off)."""
    s1, s2 = create_store(), create_store()
    _, a = create_product(stock=5, store=s1)
    _, b = create_product(stock=5, store=s2)
    _add(auth_client, a)
    _add(auth_client, b)
    data = _preview(auth_client, address_id=create_address(user).id)
    assert data["can_place_order"] is True
    assert sorted(s["store_name"] for s in data["delivery"]["shipments"]) == sorted([s1.name, s2.name])
    settings.SPLIT_FULFILLMENT_ENABLED = False
    data = _preview(auth_client, address_id=create_address(user, name="B").id)
    assert data["delivery"]["available"] is False
    assert data["blocking_issues"][0]["code"] == "not_deliverable"
    add_stock(b, 5, store=s1)
    data = _preview(auth_client, address_id=create_address(user, name="C").id)
    assert data["can_place_order"] is True and len(data["delivery"]["shipments"]) == 1
