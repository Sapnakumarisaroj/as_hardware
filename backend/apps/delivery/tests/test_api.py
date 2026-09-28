"""Phase 9 HTTP APIs: serviceability, estimates, zones, store availability, shipments (staff),
and the Django admin pages used to configure delivery."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.carts.services import add_item
from apps.core.testing import add_stock, create_product
from apps.delivery.models import DeliveryAssignment, DeliveryZone, PinCode
from apps.orders.services import place_order
from apps.stores.models import Store

from .helpers import address_at, create_partner, store_at, zone_for

pytestmark = pytest.mark.django_db

NEAR = {"latitude": "18.525400", "longitude": "73.807700"}  # 2 km north of the store
FAR = {"latitude": "18.597400", "longitude": "73.807700", "postal_code": "411014"}  # 10 km


@pytest.fixture
def shop():
    store = store_at(0, name="Kothrud Store", area="Kothrud", postal_code="411038")
    zone = zone_for(store, postal_codes="411052", delivery_fee_override=Decimal("30"))
    _, drill = create_product(name="Drill", price="300.00", stock=5, store=store)
    PinCode.objects.create(postal_code="411038", area="Kothrud", latitude=store.latitude, longitude=store.longitude)
    return {"store": store, "zone": zone, "drill": drill}


# --- Serviceability ------------------------------------------------------------------------------


def test_check_eligible_location(api_client, shop):
    data = api_client.get("/api/delivery/check/", NEAR).json()
    assert data["serviceable"] is True and data["fast_delivery_available"] is True
    assert data["label"] == "Delivery in 24 minutes"
    assert data["message"] == "⚡ Fast delivery available · Delivery in 24 minutes"
    assert data["location_precision"] == "exact" and data["fast_unavailable_reason"] == ""
    assert data["stores"] == [
        {
            "name": "Kothrud Store",
            "area": "Kothrud",
            "distance_km": 2.7,
            "fast_available": True,
            "eta_minutes": 24,
            "label": "Delivery in 24 minutes",
        }
    ]


def test_check_by_pin_code(api_client, shop):
    known = api_client.get("/api/delivery/check/", {"postal_code": "411038"}).json()
    assert known["serviceable"] and known["location_precision"] == "pin" and known["postal_code"] == "411038"
    listed = api_client.get("/api/delivery/check/", {"postal_code": "411052"}).json()
    assert listed["serviceable"] and listed["location_precision"] == "unknown"  # served by the zone's PIN list
    outside = api_client.get("/api/delivery/check/", {"postal_code": "411014"}).json()
    assert outside["serviceable"] is False and outside["stores"] == [] and outside["label"] == ""
    assert outside["message"] == "We don't deliver to PIN 411014 yet."


def test_check_non_eligible_location_and_standard_delivery(api_client, shop):
    assert api_client.get("/api/delivery/check/", FAR).json()["serviceable"] is False
    Store.objects.filter(pk=shop["store"].pk).update(own_riders=0)
    data = api_client.get("/api/delivery/check/", NEAR).json()
    assert data["serviceable"] is True and data["fast_delivery_available"] is False
    assert data["message"].startswith("🚚 Standard delivery · ")
    assert data["fast_unavailable_reason"] == "No delivery partner is available right now."


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"postal_code": "4110"},
        {"postal_code": "abcdef"},
        {"latitude": "18.5"},
        {"latitude": "95", "longitude": "73"},
    ],
)
def test_check_validates_the_location(api_client, shop, params):
    assert api_client.get("/api/delivery/check/", params).status_code == 400


def test_saved_address_needs_its_owner(api_client, auth_client, user, other_user, shop):
    mine = address_at(user, 2)
    theirs = address_at(other_user, 2)
    assert api_client.get("/api/delivery/check/", {"address_id": mine.id}).status_code == 401
    assert auth_client.get("/api/delivery/check/", {"address_id": theirs.id}).status_code == 404
    assert auth_client.get("/api/delivery/check/", {"address_id": mine.id}).json()["serviceable"] is True


# --- Estimates -----------------------------------------------------------------------------------


def test_product_estimate(api_client, shop):
    params = {"variant_id": shop["drill"].id, **NEAR}
    data = api_client.get("/api/delivery/estimate/", params).json()
    assert data["available"] is True and data["delivery_type"] == "fast" and data["eta_minutes"] == 24
    assert data["label"] == "Delivery in 24 minutes" and data["message"] == "⚡ Fast delivery · Delivery in 24 minutes"
    assert data["store_name"] == "Kothrud Store" and data["prep_minutes"] == 10 and data["distance_km"] == 2.7
    assert data["fee"] == "30.00" and data["estimated_delivery_at"] and data["window_end"]
    assert len(data["shipments"]) == 1 and data["reason_code"] == ""

    too_many = api_client.get("/api/delivery/estimate/", {**params, "quantity": 6}).json()
    assert too_many["available"] is False and too_many["reason_code"] == "insufficient_stock"
    assert too_many["eta_minutes"] is None and too_many["delivery_type"] is None

    outside = api_client.get("/api/delivery/estimate/", {"variant_id": shop["drill"].id, **FAR}).json()
    assert outside["available"] is False and outside["reason_code"] == "out_of_zone"
    assert outside["message"] == "We don't deliver to PIN 411014 yet."


def test_product_estimate_shows_the_next_option_when_fast_is_unavailable(api_client, shop):
    Store.objects.filter(pk=shop["store"].pk).update(own_riders=0)
    data = api_client.get("/api/delivery/estimate/", {"variant_id": shop["drill"].id, **NEAR}).json()
    assert data["available"] is True and data["delivery_type"] == "standard"
    assert data["fast_delivery_possible"] is False
    assert data["fast_unavailable_reason"] == "No delivery partner is available right now."
    assert data["window_start"] and " – " in data["label"]
    assert data["message"].startswith("Standard delivery · ") and "fast delivery unavailable" in data["message"]


def test_product_estimate_rejects_unknown_products(api_client, shop):
    assert api_client.get("/api/delivery/estimate/", {"variant_id": 999999, **NEAR}).status_code == 404
    assert api_client.get("/api/delivery/estimate/", NEAR).status_code == 400
    hidden, variant = create_product(name="Hidden", stock=1, store=shop["store"], published=False)
    assert api_client.get("/api/delivery/estimate/", {"variant_id": variant.id, **NEAR}).status_code == 404


def test_cart_estimate(api_client, auth_client, user, shop):
    assert api_client.get("/api/delivery/cart-estimate/", NEAR).status_code == 401
    empty = auth_client.get("/api/delivery/cart-estimate/", NEAR).json()
    assert empty["available"] is False and empty["reason_code"] == "cart_empty"
    other = store_at(3, name="Second Store")
    zone_for(other, radius="10")
    _, tape = create_product(name="Tape", price="50.00", stock=5, store=other)
    add_item(user, shop["drill"].id, 1)
    add_item(user, tape.id, 1)
    data = auth_client.get("/api/delivery/cart-estimate/", NEAR).json()
    assert data["available"] is True and len(data["shipments"]) == 2
    assert {s["store_name"] for s in data["shipments"]} == {"Kothrud Store", "Second Store"}
    assert data["eta_minutes"] == max(s["eta_minutes"] for s in data["shipments"])
    # One fee per order: the rule of the primary shipment's zone (here the nearer Second Store,
    # which has no override → global ₹40, free from ₹499).
    assert data["store_name"] == "Second Store"
    assert data["fee"] == "40.00" and data["amount_to_free_delivery"] == "149.00"


def test_checkout_preview_without_address_promises_nothing(auth_client, user, shop):
    add_item(user, shop["drill"].id, 1)
    data = auth_client.post("/api/checkout/preview/", {}, format="json").json()
    delivery = data["delivery"]
    assert delivery["eta_minutes"] is None and delivery["delivery_type"] is None and delivery["label"] == ""
    assert delivery["message"] == "Choose a delivery address to see when your order can arrive."
    assert delivery["fee"] == "40.00"  # global rule until the zone is known


def test_checkout_preview_blocks_out_of_zone_addresses(auth_client, user, shop):
    add_item(user, shop["drill"].id, 1)
    address = address_at(user, 10, postal_code="411014")
    data = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    assert data["can_place_order"] is False
    assert data["blocking_issues"] == [{"code": "not_deliverable", "message": "We don't deliver to PIN 411014 yet."}]
    assert data["delivery"]["reason_code"] == "out_of_zone"
    res = auth_client.post("/api/orders/", {"address_id": address.id, "payment_method": "cod"}, format="json")
    assert res.status_code == 400 and res.json()["error"]["code"] == "not_deliverable"


# --- Zones and stores ----------------------------------------------------------------------------


def test_zones_are_public_and_show_effective_rules(api_client, shop, settings):
    settings.FAST_DELIVERY_MAX_MINUTES = 60
    zone_for(shop["store"], name="hidden", is_active=False)
    zone_for(store_at(5, kind=Store.Kind.WAREHOUSE), name="warehouse zone")
    (zone,) = api_client.get("/api/delivery/zones/").json()
    assert zone == {
        "id": shop["zone"].id,
        "name": "5 km",
        "store_name": "Kothrud Store",
        "store_area": "Kothrud",
        "city": "Pune",
        "radius_km": "5.00",
        "postal_codes": ["411052"],
        "fast_delivery_enabled": True,
        "fast_delivery_max_minutes": 60,
        "delivery_fee": "30.00",
        "free_delivery_min_order": "499.00",
    }


def test_store_availability_shows_status_not_quantities(api_client, shop):
    second = store_at(3, name="Second Store")
    zone_for(second, radius="1")
    add_stock(shop["drill"], 50, store=second)
    store_at(1, name="Depot", kind=Store.Kind.WAREHOUSE)
    rows = api_client.get("/api/stores/availability/", {"variant_id": shop["drill"].id}).json()
    assert [(r["store_name"], r["stock_status"], r["delivers_to_location"]) for r in rows] == [
        ("Kothrud Store", "low_stock", None),
        ("Second Store", "in_stock", None),
    ]
    assert all("quantity" not in key for row in rows for key in row)

    rows = api_client.get("/api/stores/availability/", {"variant_id": shop["drill"].id, **NEAR}).json()
    assert [(r["store_name"], r["delivers_to_location"], r["distance_km"]) for r in rows] == [
        ("Kothrud Store", True, 2.0),
        ("Second Store", False, 1.0),
    ]
    assert api_client.get("/api/stores/availability/", {"variant_id": "x"}).status_code == 404


# --- Staff: shipments and assignment -------------------------------------------------------------


@pytest.fixture
def shipment(user, shop):
    add_item(user, shop["drill"].id, 1)
    order, _ = place_order(user=user, address_id=address_at(user, 2).id, payment_method="cod")
    return order.shipments.get()


def test_shipment_endpoints_are_staff_only(api_client, auth_client, delivery_user, shipment):
    rider = Client()
    from rest_framework.test import APIClient

    rider = APIClient()
    rider.force_authenticate(delivery_user)
    urls = [
        ("get", "/api/delivery/shipments/"),
        ("get", f"/api/delivery/shipments/{shipment.id}/eligible-partners/"),
        ("post", f"/api/delivery/shipments/{shipment.id}/assign/"),
    ]
    for method, url in urls:
        assert getattr(api_client, method)(url).status_code == 401, url
        assert getattr(auth_client, method)(url).status_code == 403, url
        assert getattr(rider, method)(url).status_code == 403, url
    assert not DeliveryAssignment.objects.exists()


def test_store_managers_see_only_their_stores(staff_client, staff_user, admin_client, shipment):
    assert staff_client.get("/api/delivery/shipments/").json()["results"] == []
    assert staff_client.get(f"/api/delivery/shipments/{shipment.id}/eligible-partners/").status_code == 404
    res = staff_client.post(f"/api/delivery/shipments/{shipment.id}/assign/", {"partner_id": 1}, format="json")
    assert res.status_code == 404
    shipment.store.managers.add(staff_user)
    (row,) = staff_client.get("/api/delivery/shipments/").json()["results"]
    assert row["order_number"] == shipment.order.order_number and row["assigned_partner"] is None
    assert row["delivery_type"] == "fast" and row["store_name"] == "Kothrud Store"
    assert len(admin_client.get("/api/delivery/shipments/").json()["results"]) == 1


def test_staff_assigns_a_rider(admin_client, shipment):
    partner = create_partner(shipment.store)
    (candidate,) = admin_client.get(f"/api/delivery/shipments/{shipment.id}/eligible-partners/").json()
    assert candidate == {
        "partner_id": partner.pk,
        "full_name": "Rider rider1",
        "vehicle_type": "scooter",
        "same_store": True,
        "active_assignments": 0,
        "capacity": 1,
        "distance_km": None,
    }
    url = f"/api/delivery/shipments/{shipment.id}/assign/"
    res = admin_client.post(url, {"partner_id": partner.pk}, format="json")
    assert res.status_code == 201 and res.json()["partner_id"] == partner.pk

    again = admin_client.post(url, {"partner_id": partner.pk}, format="json")
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_assigned"
    assert admin_client.post(url, {"partner_id": 999999}, format="json").status_code == 404
    assert admin_client.post(url, {}, format="json").status_code == 400

    assert admin_client.get("/api/delivery/shipments/").json()["results"] == []  # no longer waiting
    (row,) = admin_client.get("/api/delivery/shipments/", {"scope": "all"}).json()["results"]
    assert row["assigned_partner"] == "Rider rider1"


def test_rider_sees_the_pickup_store_of_their_shipment(admin_user, shipment):
    from rest_framework.test import APIClient

    from apps.delivery.assignment import assign_shipment

    partner = create_partner(shipment.store)
    assign_shipment(shipment, partner, actor=admin_user)
    client = APIClient()
    client.force_authenticate(partner.user)
    (row,) = client.get("/api/delivery/assignments/").json()["results"]
    assert row["pickup"]["name"] == "Kothrud Store" and row["status"] == "assigned"


# --- Django admin --------------------------------------------------------------------------------


@pytest.fixture
def admin_site():
    client = Client()
    client.force_login(get_user_model().objects.create_superuser(email="root@example.com", password="Passw0rd!x"))
    return client


def test_admin_pages_for_delivery_configuration(admin_site, shipment, shop):
    pin = PinCode.objects.get()
    pages = [
        reverse("admin:stores_store_changelist"),
        reverse("admin:stores_store_change", args=[shop["store"].pk]),
        reverse("admin:stores_store_add"),
        reverse("admin:stores_warehouse_changelist"),
        reverse("admin:stores_warehouse_add"),
        reverse("admin:delivery_deliveryzone_changelist"),
        reverse("admin:delivery_deliveryzone_change", args=[shop["zone"].pk]),
        reverse("admin:delivery_deliveryzone_add"),
        reverse("admin:delivery_pincode_changelist"),
        reverse("admin:delivery_pincode_change", args=[pin.pk]),
        reverse("admin:delivery_geocodecache_changelist"),
        reverse("admin:delivery_deliverypartner_changelist"),
        reverse("admin:delivery_deliveryassignment_changelist"),
        reverse("admin:orders_order_change", args=[shipment.order_id]),
    ]
    for url in pages:
        assert admin_site.get(url).status_code == 200, url
    body = admin_site.get(reverse("admin:orders_order_change", args=[shipment.order_id])).content.decode()
    assert "Kothrud Store" in body and "haversine" in body  # shipment inline
    assert admin_site.get(reverse("admin:delivery_deliveryassignment_add")).status_code == 403
    assert admin_site.get(reverse("admin:delivery_geocodecache_add")).status_code == 403


def test_admin_can_configure_a_zone(admin_site, shop):
    form = {
        "store": shop["store"].pk,
        "name": "Extended",
        "radius_km": "12.5",
        "postal_codes": "411001, 411004",
        "polygon": "null",
        "delivery_fee_override": "60.00",
        "free_delivery_min_order": "",
        "fast_delivery_max_minutes": "45",
        "is_active": "on",
    }
    res = admin_site.post(reverse("admin:delivery_deliveryzone_add"), form)
    assert res.status_code == 302, res.content.decode()[:2000]
    zone = DeliveryZone.objects.get(name="Extended")
    assert zone.fast_delivery_enabled is False and zone.fast_delivery_max_minutes == 45
    assert zone.delivery_fee_override == Decimal("60.00") and zone.postal_code_set == {"411001", "411004"}


@pytest.mark.parametrize("role", ["customer", "store_manager", "delivery_partner"])
def test_only_admins_reach_the_django_admin(role, shop):
    client = Client()
    client.force_login(get_user_model().objects.create_user(f"{role}@example.com", "S3cure-pass!", role=role))
    for name in ("stores_store_changelist", "delivery_deliveryzone_changelist", "delivery_pincode_changelist"):
        res = client.get(reverse(f"admin:{name}"))
        assert res.status_code == 302 and "/login/" in res["Location"], name
