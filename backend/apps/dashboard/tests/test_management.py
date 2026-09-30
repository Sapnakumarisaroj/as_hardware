"""Managing the shop from the dashboard: catalogue, stores, offers, customers, riders, support."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog.models import Brand, Category, Product
from apps.core.models import AuditLog
from apps.core.testing import create_category, create_coupon, create_product, create_store
from apps.delivery.models import DeliveryZone
from apps.delivery.tests.helpers import assign, create_partner, packed_order, photo, store_at, zone_for
from apps.inventory.models import Inventory
from apps.offers.models import Coupon, Offer
from apps.orders.tests.helpers import deliver, order_with
from apps.stores.models import Store
from apps.support.models import SupportConversation, SupportMessage

pytestmark = pytest.mark.django_db


def product_body(category, **extra):
    body = {
        "name": "Angle Grinder 850W",
        "sku": "AG-850",
        "category": category.pk,
        "unit": "piece",
        "gst_rate": "18.00",
        "is_published": True,
        "is_returnable": True,
        "variants": [
            {"sku": "AG-850-STD", "name": "Standard", "mrp": "3200.00", "price": "2799.00", "is_default": True},
            {"sku": "AG-850-KIT", "name": "With 5 discs", "mrp": "3800.00", "price": "3299.00"},
        ],
        "specifications": [{"name": "Power", "value": "850 W"}, {"name": "Disc size", "value": "100 mm"}],
    }
    body.update(extra)
    return body


# --- Products ------------------------------------------------------------------------------------


def test_admin_creates_a_product_with_variants_and_specifications(admin_client):
    category = create_category("Power Tools")
    brand = Brand.objects.create(name="Bosch", slug="bosch")
    response = admin_client.post("/api/admin/products/", product_body(category, brand=brand.pk), format="json")
    assert response.status_code == 201, response.data
    data = response.data
    assert data["state"] == "live"
    assert data["brand"]["name"] == "Bosch"
    assert data["is_returnable"] is True
    assert [(v["sku"], v["mrp"], v["price"]) for v in data["variants"]] == [
        ("AG-850-STD", "3200.00", "2799.00"),
        ("AG-850-KIT", "3800.00", "3299.00"),
    ]
    assert {s["name"] for s in data["specifications"]} == {"Power", "Disc size"}
    assert (data["price_from"], data["price_to"]) == ("2799.00", "3299.00")
    assert AuditLog.objects.filter(action="product.create").exists()


def test_selling_price_above_mrp_is_refused(admin_client):
    body = product_body(create_category())
    body["variants"][0]["price"] = "3500.00"
    response = admin_client.post("/api/admin/products/", body, format="json")
    assert response.status_code == 400
    assert not Product.objects.exists()


def test_duplicate_sku_is_refused(admin_client):
    category = create_category()
    assert admin_client.post("/api/admin/products/", product_body(category), format="json").status_code == 201
    again = admin_client.post("/api/admin/products/", product_body(category, name="Other"), format="json")
    assert again.status_code in (400, 409)
    assert Product.objects.count() == 1


def test_admin_edits_unpublishes_deletes_and_restores_a_product(admin_client, api_client):
    product, _ = create_product(name="Hammer")
    url = f"/api/admin/products/{product.pk}/"

    response = admin_client.patch(url, {"is_published": False, "is_returnable": False}, format="json")
    assert response.status_code == 200, response.data
    assert (response.data["state"], response.data["is_returnable"]) == ("draft", False)
    assert api_client.get(f"/api/products/{product.slug}/").status_code == 404  # hidden from customers

    assert admin_client.delete(url).status_code == 204
    product = Product.all_objects.get(pk=product.pk)
    assert product.is_deleted  # soft: the row is kept for past orders
    assert admin_client.get("/api/admin/products/").data["count"] == 0
    assert admin_client.get("/api/admin/products/?state=deleted").data["count"] == 1
    assert admin_client.patch(url, {"name": "X"}, format="json").status_code == 409

    restored = admin_client.post(f"{url}restore/")
    assert restored.status_code == 200
    assert restored.data["state"] == "draft"  # comes back unpublished


def test_product_list_searches_and_filters(admin_client, staff_client):
    tools, paint = create_category("Tools"), create_category("Paint")
    store = create_store()
    create_product(name="Claw Hammer", category=tools, stock=5, store=store)
    create_product(name="Wall Primer", category=paint)
    create_product(name="Draft Saw", category=tools, published=False)

    def names(query):
        return [p["name"] for p in admin_client.get(f"/api/admin/products/?{query}").data["results"]]

    assert names("q=hammer") == ["Claw Hammer"]
    assert names(f"category={paint.pk}") == ["Wall Primer"]
    assert names("state=draft") == ["Draft Saw"]
    assert names("stock=in") == ["Claw Hammer"]
    assert names("stock=out") == ["Draft Saw", "Wall Primer"]
    assert staff_client.get("/api/admin/products/?q=hammer").data["results"][0]["stock_available"] == 5


def test_product_pictures(admin_client, staff_client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    product, _ = create_product(name="Hammer")
    url = f"/api/admin/products/{product.pk}/images/"

    assert staff_client.post(url, {"image": photo()}, format="multipart").status_code == 403
    first = admin_client.post(url, {"image": photo(), "alt_text": "Front"}, format="multipart")
    assert first.status_code == 201, first.data
    second = admin_client.post(url, {"image": photo("PNG")}, format="multipart")
    images = second.data["images"]
    assert [i["is_primary"] for i in images] == [True, False]

    not_a_picture = admin_client.post(url, {"image": photo(name="x.exe")}, format="multipart")
    assert not_a_picture.status_code == 400

    other = admin_client.patch(f"{url}{images[1]['id']}/", {"is_primary": True}, format="json")
    assert {i["id"]: i["is_primary"] for i in other.data["images"]} == {images[0]["id"]: False, images[1]["id"]: True}

    gone = admin_client.delete(f"{url}{images[1]['id']}/")
    assert [i["id"] for i in gone.data["images"]] == [images[0]["id"]]
    assert gone.data["images"][0]["is_primary"] is True  # the remaining picture takes over


# --- Categories and brands -----------------------------------------------------------------------


def test_categories_subcategories_and_ordering(admin_client, api_client):
    tools = admin_client.post("/api/admin/categories/", {"name": "Tools", "sort_order": 2}, format="json")
    assert tools.status_code == 201, tools.data
    sub = admin_client.post("/api/admin/categories/", {"name": "Hand Tools", "parent": tools.data["id"]}, format="json")
    assert sub.status_code == 201, sub.data
    paint = admin_client.post("/api/admin/categories/", {"name": "Paint", "sort_order": 1}, format="json")

    tree = admin_client.get("/api/admin/categories/").data
    assert [c["name"] for c in tree] == ["Paint", "Tools"]
    assert [c["name"] for c in tree[1]["children"]] == ["Hand Tools"]

    # A subcategory can't get subcategories of its own.
    deeper = admin_client.post("/api/admin/categories/", {"name": "Deep", "parent": sub.data["id"]}, format="json")
    assert deeper.status_code == 400

    off = admin_client.patch(f"/api/admin/categories/{paint.data['id']}/", {"is_active": False}, format="json")
    assert off.status_code == 200
    assert "Paint" not in [c["name"] for c in api_client.get("/api/categories/").data]
    assert "Paint" in [c["name"] for c in admin_client.get("/api/admin/categories/").data]  # still manageable


def test_category_with_products_cannot_be_deleted(admin_client):
    category = create_category("Tools")
    create_product(category=category)
    response = admin_client.delete(f"/api/admin/categories/{category.pk}/")
    assert response.status_code in (400, 409)
    assert Category.objects.filter(pk=category.pk).exists()


def test_brands(admin_client):
    created = admin_client.post("/api/admin/brands/", {"name": "Stanley"}, format="json")
    assert created.status_code == 201, created.data
    brand = Brand.objects.get(pk=created.data["id"])
    create_product(brand=brand)

    rows = admin_client.get("/api/admin/brands/?q=stan").data["results"]
    assert [(b["name"], b["product_count"]) for b in rows] == [("Stanley", 1)]

    refused = admin_client.delete(f"/api/admin/brands/{brand.pk}/")
    assert refused.status_code == 409
    assert refused.data["error"]["code"] == "brand_has_products"
    assert admin_client.patch(f"/api/admin/brands/{brand.pk}/", {"is_active": False}, format="json").status_code == 200


# --- Inventory -----------------------------------------------------------------------------------


def test_stock_is_adjusted_through_the_ledger_and_never_goes_negative(admin_client):
    store = create_store(name="Kothrud")
    _, variant = create_product(name="Hammer", stock=5, store=store)
    inventory = Inventory.objects.get(variant=variant)
    url = f"/api/inventory/{inventory.pk}/adjust/"

    added = admin_client.post(url, {"movement_type": "adjustment", "quantity": 3, "reason": "Recount"}, format="json")
    assert added.status_code == 201, added.data
    too_much = admin_client.post(url, {"movement_type": "adjustment", "quantity": -50, "reason": "Typo"}, format="json")
    assert too_much.status_code in (400, 409)
    inventory.refresh_from_db()
    assert inventory.available_quantity == 8

    # Quantities can't be set directly.
    admin_client.patch(f"/api/inventory/{inventory.pk}/", {"available_quantity": 999}, format="json")
    inventory.refresh_from_db()
    assert inventory.available_quantity == 8

    movements = admin_client.get(f"/api/inventory/movements/?inventory={inventory.pk}").data["results"]
    assert len(movements) == 2  # opening stock + recount; the refused one left no trace


def test_inventory_search_and_stock_filter(admin_client):
    store = create_store(name="Kothrud")
    create_product(name="Hammer", stock=50, store=store)
    _, low = create_product(name="Pliers", stock=2, store=store)
    _, out = create_product(name="Chisel", stock=1, store=store)
    Inventory.objects.filter(variant=out).update(available_quantity=0)

    def skus(query):
        return {r["sku"] for r in admin_client.get(f"/api/inventory/?{query}").data["results"]}

    assert skus("q=pliers") == {low.sku}
    assert skus("stock=out") == {out.sku}
    assert skus("stock=low") == {low.sku}
    assert len(skus("stock=ok")) == 1
    assert len(skus("q=kothrud")) == 3


# --- Stores, warehouses and zones ----------------------------------------------------------------

STORE = {
    "name": "Baner Store",
    "code": "pun-07",
    "kind": "store",
    "phone": "9876543210",
    "address_line1": "4 Baner Road",
    "city": "Pune",
    "state": "Maharashtra",
    "postal_code": "411045",
    "latitude": "18.559000",
    "longitude": "73.786800",
    "opening_hours": {"mon": ["09:00", "21:00"], "sun": None},
    "avg_prep_minutes": 12,
}


def test_admin_creates_a_store_with_hours_zone_and_manager(admin_client, staff_user):
    response = admin_client.post("/api/admin/stores/", {**STORE, "manager_ids": [staff_user.pk]}, format="json")
    assert response.status_code == 201, response.data
    store = Store.objects.get(pk=response.data["id"])
    assert store.code == "PUN-07"
    assert store.opening_hours == {"mon": ["09:00", "21:00"], "sun": None}
    assert list(store.managers.all()) == [staff_user]

    zone = admin_client.post(
        "/api/admin/zones/",
        {
            "store": store.pk,
            "name": "Baner 4 km",
            "radius_km": "4.00",
            "postal_codes": "411045, 411007",
            "fast_delivery_enabled": True,
            "fast_delivery_max_minutes": 45,
            "delivery_fee_override": "25.00",
        },
        format="json",
    )
    assert zone.status_code == 201, zone.data
    assert zone.data["pin_codes"] == ["411007", "411045"]
    assert zone.data["effective_fee"] == "25.00"

    detail = admin_client.get(f"/api/admin/stores/{store.pk}/").data
    assert [z["name"] for z in detail["zones"]] == ["Baner 4 km"]
    assert detail["inventory"] == {
        "stock_records": 0, "units_available": 0, "units_reserved": 0, "low_stock": 0, "out_of_stock": 0,
    }  # fmt: skip
    assert detail["can_edit"] == "all"


@pytest.mark.parametrize(
    "hours",
    [
        {"mon": ["9am", "9pm"]},
        {"monday": ["09:00", "21:00"]},
        {"mon": ["09:00"]},
        {"mon": ["09:00", "09:00"]},
        "always",
    ],
)
def test_opening_hours_are_validated(admin_client, hours):
    store = create_store()
    response = admin_client.patch(f"/api/admin/stores/{store.pk}/", {"opening_hours": hours}, format="json")
    assert response.status_code == 400


def test_zone_input_is_validated(admin_client):
    store, warehouse = create_store(), create_store(kind="warehouse")
    base = {"store": store.pk, "name": "Z", "radius_km": "3"}
    bad = [
        {**base, "store": warehouse.pk},
        {**base, "postal_codes": "4110, abc"},
        {**base, "polygon": [[18.5, 73.8], [18.6, 73.9]]},
        {**base, "polygon": [[118.5, 73.8], [18.6, 73.9], [18.7, 73.7]]},
        {**base, "radius_km": "0"},
    ]
    for body in bad:
        assert admin_client.post("/api/admin/zones/", body, format="json").status_code == 400, body
    assert DeliveryZone.objects.filter(name="Z").count() == 0


def test_warehouses_are_listed_by_kind(admin_client):
    create_store(name="Shop")
    create_store(kind="warehouse", name="Central Warehouse")
    assert [s["name"] for s in admin_client.get("/api/admin/stores/?kind=warehouse").data["results"]] == [
        "Central Warehouse"
    ]
    assert [s["name"] for s in admin_client.get("/api/admin/stores/?kind=fulfilment").data["results"]] == ["Shop"]


def test_store_with_stock_or_open_orders_cannot_be_removed(admin_client, user):
    store = store_at(0)
    zone_for(store)
    _, variant = create_product(stock=4, store=store)
    packed_order(user, (variant, 1), km_north=1)

    refused = admin_client.delete(f"/api/admin/stores/{store.pk}/")
    assert refused.status_code == 409
    assert refused.data["error"]["code"] == "store_has_open_orders"

    empty = create_store(name="Empty")
    assert admin_client.delete(f"/api/admin/stores/{empty.pk}/").status_code == 204
    assert Store.all_objects.get(pk=empty.pk).is_deleted


def test_pin_codes(admin_client):
    body = {"postal_code": "411045", "area": "Baner", "city": "Pune", "latitude": "18.559", "longitude": "73.7868"}
    assert admin_client.post("/api/admin/pincodes/", body, format="json").status_code == 201
    assert admin_client.post("/api/admin/pincodes/", {**body, "postal_code": "41104"}, format="json").status_code == 400
    assert admin_client.get("/api/admin/pincodes/?q=baner").data["count"] == 1


# --- Offers and coupons --------------------------------------------------------------------------


def test_offer_lifecycle_and_checkout_uses_the_pricing_engine(admin_client, user, api_client):
    tools = create_category("Tools")
    store = create_store()
    _, variant = create_product(name="Drill", price="1000.00", mrp="1200.00", category=tools, stock=5, store=store)
    now = timezone.now()
    body = {
        "name": "Tools week",
        "discount_type": "percent",
        "value": "10",
        "max_discount_amount": "500",
        "min_order_value": "0",
        "starts_at": (now - timedelta(hours=1)).isoformat(),
        "ends_at": (now + timedelta(days=7)).isoformat(),
        "categories": [tools.pk],
    }
    created = admin_client.post("/api/admin/offers/", body, format="json")
    assert created.status_code == 201, created.data
    assert created.data["state"] == "live"
    assert created.data["summary"] == "10% off (up to ₹500) on Tools"
    assert [o["name"] for o in api_client.get("/api/offers/").data] == ["Tools week"]

    order, _ = order_with(user, (variant, 1))  # priced by the Phase 6 engine, not by the dashboard
    assert order.offer_discount == Decimal("100.00")

    url = f"/api/admin/offers/{created.data['id']}/"
    off = admin_client.patch(url, {"is_active": False}, format="json")
    assert off.data["state"] == "inactive"
    assert api_client.get("/api/offers/").data == []
    assert admin_client.get("/api/admin/offers/?state=live").data["count"] == 0
    assert admin_client.get("/api/admin/offers/?state=inactive").data["count"] == 1
    assert admin_client.delete(url).status_code == 204
    assert not Offer.objects.exists()


def test_offer_rules_are_validated(admin_client):
    now = timezone.now()
    base = {"name": "X", "discount_type": "percent", "value": "10", "starts_at": now.isoformat()}
    bad = [
        {**base, "value": "120"},
        {**base, "value": "0"},
        {**base, "ends_at": (now - timedelta(days=1)).isoformat()},
        {**base, "discount_type": "fixed", "value": "50", "max_discount_amount": "20"},
        {**base, "products": [999999]},
    ]
    for body in bad:
        assert admin_client.post("/api/admin/offers/", body, format="json").status_code == 400, body
    assert not Offer.objects.exists()


def test_coupon_lifecycle(admin_client, auth_client, user):
    now = timezone.now()
    body = {
        "code": " welcome50 ",
        "discount_type": "fixed",
        "value": "50",
        "min_order_value": "500",
        "starts_at": (now - timedelta(hours=1)).isoformat(),
        "usage_limit": 100,
        "per_customer_limit": 1,
        "show_in_checkout": True,
    }
    created = admin_client.post("/api/admin/coupons/", body, format="json")
    assert created.status_code == 201, created.data
    assert created.data["code"] == "WELCOME50"
    assert created.data["remaining_uses"] == 100
    assert created.data["summary"] == "₹50 off on the whole cart, from ₹500"

    again = admin_client.post("/api/admin/coupons/", {**body, "code": "Welcome50"}, format="json")
    assert again.status_code == 400

    store = create_store()
    _, variant = create_product(price="900.00", stock=5, store=store)
    order, _ = order_with(user, (variant, 1), coupon_code="WELCOME50")
    assert order.coupon_discount == Decimal("50.00")

    url = f"/api/admin/coupons/{created.data['id']}/"
    assert admin_client.get(url).data["used_count"] == 1
    refused = admin_client.delete(url)  # used coupons are kept for the records
    assert refused.status_code == 409
    assert refused.data["error"]["code"] == "coupon_in_use"
    assert admin_client.patch(url, {"usage_limit": 0}, format="json").status_code == 400
    assert admin_client.patch(url, {"used_count": 0}, format="json").data["used_count"] == 1  # read-only
    assert admin_client.patch(url, {"is_active": False}, format="json").data["state"] == "inactive"


def test_coupon_states(admin_client):
    now = timezone.now()
    create_coupon("LIVE")
    create_coupon("SOON", starts_at=now + timedelta(days=2), ends_at=now + timedelta(days=5))
    create_coupon("OLD", starts_at=now - timedelta(days=9), ends_at=now - timedelta(days=2))
    create_coupon("OFF", is_active=False)
    for state, code in (("live", "LIVE"), ("scheduled", "SOON"), ("expired", "OLD"), ("inactive", "OFF")):
        rows = admin_client.get(f"/api/admin/coupons/?state={state}").data["results"]
        assert [(r["code"], r["state"]) for r in rows] == [(code, state)]
    assert Coupon.objects.count() == 4


# --- Customers -----------------------------------------------------------------------------------


def test_customer_list_shows_orders_and_spend(admin_client, admin_user, user, other_user):
    store = create_store()
    _, variant = create_product(price="500.00", stock=20, store=store)
    first, _ = order_with(user, (variant, 2))
    deliver(first, admin_user)  # cash collected: counts as spend
    order_with(user, (variant, 1))  # placed, not paid yet

    rows = {r["email"]: r for r in admin_client.get("/api/admin/customers/").data["results"]}
    assert set(rows) == {user.email, other_user.email}  # staff accounts are not customers
    first.refresh_from_db()
    assert rows[user.email]["order_count"] == 2
    assert rows[user.email]["total_spend"] == str(first.grand_total)
    assert rows[other_user.email]["order_count"] == 0
    assert rows[other_user.email]["total_spend"] == "0.00"

    assert [r["email"] for r in admin_client.get("/api/admin/customers/?q=asha").data["results"]] == [user.email]
    assert admin_client.get("/api/admin/customers/?has_orders=true").data["count"] == 1
    assert admin_client.get("/api/admin/customers/?role=all").data["count"] == 3

    detail = admin_client.get(f"/api/admin/customers/{user.pk}/").data
    assert len(detail["recent_orders"]) == 2
    assert detail["recent_orders"][0]["order_number"]
    assert detail["addresses"][0]["postal_code"] == "411001"


def test_admin_deactivates_a_customer_and_changes_a_role(admin_client, user, admin_user):
    url = f"/api/admin/users/{user.pk}/"
    assert admin_client.patch(url, {"is_active": False}, format="json").status_code == 200
    user.refresh_from_db()
    assert user.is_active is False
    assert admin_client.get("/api/admin/customers/?is_active=false").data["count"] == 1

    assert admin_client.patch(url, {"is_active": True, "role": "store_manager"}, format="json").status_code == 200
    user.refresh_from_db()
    assert (user.is_active, user.role) == (True, "store_manager")

    # An administrator can't lock themselves out.
    own = admin_client.patch(f"/api/admin/users/{admin_user.pk}/", {"is_active": False}, format="json")
    assert own.status_code in (400, 409)


# --- Delivery ------------------------------------------------------------------------------------


def test_rider_list_and_admin_changes(admin_client, admin_user, user):
    store = store_at(0, name="Kothrud")
    zone_for(store)
    _, variant = create_product(stock=5, store=store)
    order = packed_order(user, (variant, 1), km_north=1)
    busy = create_partner(store, email="busy@example.com")
    create_partner(store, email="off@example.com", status="offline")
    new = create_partner(store, email="new@example.com", is_verified=False, status="offline")
    assign(order.shipments.get(), busy, actor=admin_user)

    rows = {r["email"]: r for r in admin_client.get("/api/admin/riders/").data["results"]}
    assert rows["busy@example.com"]["active_assignments"] == 1
    assert rows["busy@example.com"]["home_store_name"] == "Kothrud"
    assert rows["new@example.com"]["can_take_jobs"] is False
    assert admin_client.get("/api/admin/riders/?status=online").data["count"] == 1
    assert admin_client.get("/api/admin/riders/?is_verified=false").data["count"] == 1
    assert admin_client.get("/api/admin/riders/?q=busy").data["count"] == 1

    verified = admin_client.patch(f"/api/admin/riders/{new.pk}/", {"is_verified": True}, format="json")
    assert verified.status_code == 200, verified.data
    assert verified.data["is_verified"] is True

    # A rider with a job in hand can't be switched off.
    refused = admin_client.patch(f"/api/admin/riders/{busy.pk}/", {"is_active": False}, format="json")
    assert refused.status_code == 409
    assert refused.data["error"]["code"] == "active_delivery"
    assert (
        admin_client.patch(f"/api/admin/riders/{busy.pk}/", {"max_active_assignments": 0}, format="json").status_code
        == 400
    )

    jobs = admin_client.get("/api/admin/jobs/?status=active").data["results"]
    assert [(j["order_number"], j["partner_name"], j["store_name"]) for j in jobs] == [
        (order.order_number, busy.user.full_name, "Kothrud")
    ]
    assert admin_client.get("/api/admin/jobs/?status=failed").data["count"] == 0


# --- Support -------------------------------------------------------------------------------------


def test_staff_answers_a_support_conversation(admin_client, admin_user, auth_client, user):
    conversation = SupportConversation.objects.create(user=user, subject="Wrong size delivered")
    SupportMessage.objects.create(
        conversation=conversation, sender=user, sender_type="customer", body="I got the 10 mm, ordered 12 mm."
    )

    row = admin_client.get("/api/admin/support/?status=active").data["results"][0]
    assert row["customer"]["email"] == user.email
    assert row["waiting_for_reply"] is True
    assert row["last_message"].startswith("I got the 10 mm")

    reply = admin_client.post(
        f"/api/admin/support/{conversation.pk}/reply/", {"body": "Sorry! We'll exchange it."}, format="json"
    )
    assert reply.status_code == 201, reply.data
    assert [m["sender_type"] for m in reply.data["messages"]] == ["customer", "agent"]
    assert reply.data["status"] == "waiting_customer"
    assert reply.data["assigned_to"] == admin_user.pk
    assert reply.data["waiting_for_reply"] is False

    # The customer sees the answer in their own conversation.
    theirs = auth_client.get(f"/api/support/conversations/{conversation.pk}/")
    assert "exchange" in theirs.content.decode()

    assert (
        admin_client.post(f"/api/admin/support/{conversation.pk}/reply/", {"body": " "}, format="json").status_code
        == 400
    )
    closed = admin_client.patch(f"/api/admin/support/{conversation.pk}/", {"status": "resolved"}, format="json")
    assert closed.data["status"] == "resolved"
    assert admin_client.get("/api/admin/support/?status=active").data["count"] == 0
    assert admin_client.get("/api/admin/support/?q=wrong+size").data["count"] == 1


def test_two_products_with_the_same_name_get_different_addresses(admin_client):
    category = create_category()
    first = admin_client.post("/api/admin/products/", product_body(category), format="json")
    body = product_body(category, sku="AG-850-B", variants=[{"sku": "AG-850-B-STD", "mrp": "10.00", "price": "9.00"}])
    second = admin_client.post("/api/admin/products/", body, format="json")
    assert (first.status_code, second.status_code) == (201, 201), second.data
    assert first.data["slug"] == "angle-grinder-850w"
    assert second.data["slug"] == "angle-grinder-850w-2"
    third = admin_client.post("/api/admin/categories/", {"name": "Tools"}, format="json")  # same name as the fixture
    assert third.status_code == 201, third.data
    assert third.data["slug"] != category.slug
