"""Bulk quote requests (RFQ) → quotation → accept → checkout through the normal order engine."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.carts.models import CartItem
from apps.carts.services import add_item
from apps.core.testing import create_address, create_product, create_store
from apps.offers.models import Offer
from apps.orders.models import Order
from apps.quotes.models import Quote
from apps.quotes.services import expire_due

pytestmark = pytest.mark.django_db


@pytest.fixture
def goods():
    store = create_store()
    _, hinge = create_product(name="Soft-close Hinge", price="120.00", mrp="150.00", stock=500, store=store)
    _, ply = create_product(name="BWP Plywood 18 mm", price="2400.00", mrp="2800.00", stock=80, store=store)
    return {"store": store, "hinge": hinge, "ply": ply}


def _request(client, goods, **extra):
    body = {
        "items": [
            {"variant_id": goods["hinge"].id, "quantity": 200, "note": "for 40 shutters"},
            {"variant_id": goods["ply"].id, "quantity": 60},
        ],
        "note": "Site in Whitefield",
        **extra,
    }
    return client.post("/api/quotes/", body, format="json")


def _quote(admin_client, quote, prices, valid_days=7):
    items = {i["sku"]: i["id"] for i in quote["items"]}
    lines = [{"item_id": items[sku], "unit_price": price} for sku, price in prices.items()]
    return admin_client.post(
        f"/api/admin/quotes/{quote['id']}/quotation/",
        {"lines": lines, "valid_days": valid_days, "shop_note": "Delivery in 2 lots"},
        format="json",
    )


def _quoted(auth_client, admin_client, goods):
    quote = _request(auth_client, goods).json()
    res = _quote(admin_client, quote, {goods["hinge"].sku: "100.00", goods["ply"].sku: "2200.00"})
    assert res.status_code == 200, res.json()
    return res.json()


def test_request_snapshots_list_price_and_business_profile(auth_client, user, goods):
    user.profile.buyer_type = "contractor"
    user.profile.business_name = "Asha Interiors"
    user.profile.gstin = "29AAGCB7383J1Z4"
    user.profile.save()
    res = _request(auth_client, goods)
    assert res.status_code == 201, res.json()
    body = res.json()
    assert body["status"] == "requested"
    assert body["number"].startswith("RFQ")
    assert (body["buyer_type"], body["business_name"], body["gstin"]) == (
        "contractor",
        "Asha Interiors",
        "29AAGCB7383J1Z4",
    )
    lines = {i["sku"]: i for i in body["items"]}
    assert lines[goods["hinge"].sku]["list_unit_price"] == "120.00"
    assert lines[goods["hinge"].sku]["quoted_unit_price"] is None
    assert body["quoted_goods_total"] is None
    assert body["can_accept"] is False


def test_request_from_cart_and_validation(auth_client, user, goods):
    add_item(user, goods["hinge"].id, 10)
    res = auth_client.post("/api/quotes/", {"from_cart": True}, format="json")
    assert res.status_code == 201, res.json()
    assert [i["quantity"] for i in res.json()["items"]] == [10]
    assert CartItem.objects.filter(cart__user=user).count() == 1  # the cart is left alone

    assert auth_client.post("/api/quotes/", {}, format="json").status_code == 400
    bad = auth_client.post("/api/quotes/", {"items": [{"variant_id": 999999, "quantity": 1}]}, format="json")
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "product_unavailable"
    huge = auth_client.post(
        "/api/quotes/", {"items": [{"variant_id": goods["hinge"].id, "quantity": 10**6}]}, format="json"
    )
    assert huge.json()["error"]["code"] == "invalid_quantity"


def test_staff_must_price_every_line_within_mrp(auth_client, admin_client, goods):
    quote = _request(auth_client, goods).json()
    missing = _quote(admin_client, quote, {goods["hinge"].sku: "100.00"})
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "invalid_prices"
    above_mrp = _quote(admin_client, quote, {goods["hinge"].sku: "151.00", goods["ply"].sku: "2200.00"})
    assert above_mrp.status_code == 400
    assert Quote.objects.get(pk=quote["id"]).status == "requested"


def test_customer_and_store_manager_cannot_send_quotations(auth_client, staff_client, goods):
    quote = _request(auth_client, goods).json()
    body = {"lines": [], "valid_days": 7}
    assert auth_client.post(f"/api/admin/quotes/{quote['id']}/quotation/", body, format="json").status_code == 403
    assert staff_client.post(f"/api/admin/quotes/{quote['id']}/quotation/", body, format="json").status_code == 403
    assert staff_client.get("/api/admin/quotes/").status_code == 200  # managers can read
    assert auth_client.get("/api/admin/quotes/").status_code == 403


def test_customers_see_only_their_own_quotes(auth_client, api_client, other_user, goods):
    quote = _request(auth_client, goods).json()
    api_client.force_authenticate(other_user)
    assert api_client.get(f"/api/quotes/{quote['id']}/").status_code == 404
    assert api_client.post(f"/api/quotes/{quote['id']}/accept/").status_code == 404
    assert api_client.get("/api/quotes/").json()["count"] == 0


def test_full_flow_orders_at_quoted_prices_without_offers(auth_client, admin_client, user, goods):
    # An automatic 10 % offer is live: it must not stack on the negotiated price.
    offer = Offer.objects.create(
        name="Monsoon 10%",
        discount_type="percent",
        value=Decimal("10"),
        starts_at=timezone.now() - timedelta(days=1),
        is_active=True,
    )
    offer.products.set([goods["hinge"].product, goods["ply"].product])
    add_item(user, goods["hinge"].id, 1)  # an unrelated cart line stays in the cart
    assert auth_client.get("/api/cart/").json()["totals"]["offer_discount"] == "12.00"  # the offer is live
    quote = _quoted(auth_client, admin_client, goods)
    assert quote["status"] == "quoted"
    assert quote["quoted_goods_total"] == "152000.00"  # 200 × 100 + 60 × 2200
    assert quote["can_accept"] is True

    accepted = auth_client.post(f"/api/quotes/{quote['id']}/accept/")
    assert accepted.status_code == 200 and accepted.json()["can_checkout"] is True

    address = create_address(user)
    preview = auth_client.post(
        "/api/checkout/preview/", {"address_id": address.id, "quote_id": quote["id"]}, format="json"
    ).json()
    assert preview["totals"]["subtotal"] == "152000.00"
    assert preview["totals"]["offer_discount"] == "0.00"
    assert preview["can_place_order"] is True, preview["blocking_issues"]

    res = auth_client.post(
        "/api/orders/",
        {
            "address_id": address.id,
            "payment_method": "cod",
            "quote_id": quote["id"],
            "expected_total": preview["totals"]["grand_total"],
        },
        format="json",
    )
    # COD is capped at ₹10,000 by default: this big order must pay online, which is off → 400.
    assert res.status_code == 400
    assert res.json()["error"]["code"] in {"cod_unavailable", "online_payment_unavailable"}


def test_quoted_order_is_placed_and_quote_marked_ordered(auth_client, admin_client, user, goods, settings):
    quote = _request(auth_client, goods, items=[{"variant_id": goods["hinge"].id, "quantity": 50}]).json()
    items = {i["sku"]: i["id"] for i in quote["items"]}
    admin_client.post(
        f"/api/admin/quotes/{quote['id']}/quotation/",
        {"lines": [{"item_id": items[goods["hinge"].sku], "unit_price": "95.00"}], "valid_days": 3},
        format="json",
    )
    auth_client.post(f"/api/quotes/{quote['id']}/accept/")
    address = create_address(user)
    res = auth_client.post(
        "/api/orders/", {"address_id": address.id, "payment_method": "cod", "quote_id": quote["id"]}, format="json"
    )
    assert res.status_code == 201, res.json()
    order = Order.objects.get(order_number=res.json()["order_number"])
    line = order.items.get()
    assert (line.unit_price, line.quantity, line.quoted, line.base_unit_price) == (
        Decimal("95.00"),
        50,
        True,
        Decimal("120.00"),
    )
    assert order.subtotal == Decimal("4750.00")
    stored = Quote.objects.get(pk=quote["id"])
    assert stored.status == "ordered" and stored.order_id == order.id

    again = auth_client.post(
        "/api/orders/", {"address_id": address.id, "payment_method": "cod", "quote_id": quote["id"]}, format="json"
    )
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "quote_already_ordered"


def test_checkout_needs_acceptance_and_rejects_coupon(auth_client, admin_client, user, goods):
    quote = _quoted(auth_client, admin_client, goods)
    address = create_address(user)
    body = {"address_id": address.id, "payment_method": "cod", "quote_id": quote["id"]}
    res = auth_client.post("/api/orders/", body, format="json")
    assert res.json()["error"]["code"] == "quote_not_accepted"
    auth_client.post(f"/api/quotes/{quote['id']}/accept/")
    res = auth_client.post("/api/orders/", {**body, "coupon_code": "SAVE10"}, format="json")
    assert res.json()["error"]["code"] == "coupon_not_allowed"


def test_expired_quotation_cannot_be_accepted_or_ordered(auth_client, admin_client, user, goods):
    quote = _quoted(auth_client, admin_client, goods)
    Quote.objects.filter(pk=quote["id"]).update(valid_until=timezone.now() - timedelta(minutes=1))
    res = auth_client.post(f"/api/quotes/{quote['id']}/accept/")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "quote_expired"
    assert Quote.objects.get(pk=quote["id"]).status == "expired"


def test_expiry_job(auth_client, admin_client, goods):
    quote = _quoted(auth_client, admin_client, goods)
    auth_client.post(f"/api/quotes/{quote['id']}/accept/")
    Quote.objects.filter(pk=quote["id"]).update(valid_until=timezone.now() - timedelta(minutes=1))
    assert expire_due() == 1
    assert Quote.objects.get(pk=quote["id"]).status == "expired"
    assert expire_due() == 0


def test_staff_can_revise_until_accepted_and_reject(auth_client, admin_client, goods):
    quote = _quoted(auth_client, admin_client, goods)
    revised = _quote(admin_client, quote, {goods["hinge"].sku: "98.00", goods["ply"].sku: "2150.00"})
    assert revised.status_code == 200
    assert revised.json()["quoted_goods_total"] == "148600.00"
    auth_client.post(f"/api/quotes/{quote['id']}/accept/")
    late = _quote(admin_client, quote, {goods["hinge"].sku: "90.00", goods["ply"].sku: "2000.00"})
    assert late.status_code == 409

    other = _request(auth_client, goods).json()
    rejected = admin_client.post(f"/api/admin/quotes/{other['id']}/reject/", {"reason": "Out of range"})
    assert rejected.json()["status"] == "rejected"


def test_customer_cancels_request_or_declines_quotation(auth_client, admin_client, goods):
    request_only = _request(auth_client, goods).json()
    assert auth_client.post(f"/api/quotes/{request_only['id']}/close/").json()["status"] == "cancelled"
    quote = _quoted(auth_client, admin_client, goods)
    assert auth_client.post(f"/api/quotes/{quote['id']}/close/", {"reason": "Too high"}).json()["status"] == "declined"
    assert auth_client.post(f"/api/quotes/{quote['id']}/close/").status_code == 409
