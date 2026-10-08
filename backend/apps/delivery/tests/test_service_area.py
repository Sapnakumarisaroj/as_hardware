"""Bengaluru-wide delivery: the city service area (a PIN/city/map rule, not a PIN list), the gate for
addresses outside it, and fast delivery staying the ETA engine's decision for each address."""

from decimal import Decimal

import pytest

from apps.carts.services import add_item
from apps.core.testing import create_address, create_product
from apps.delivery.models import DeliveryZone, PinCode, ServiceArea
from apps.delivery.pin import pin_context
from apps.stores.models import Store

from .helpers import create_partner

pytestmark = pytest.mark.django_db

OUTSIDE = "Currently we deliver only within Bengaluru."
JAYANAGAR = (Decimal("12.925000"), Decimal("77.593800"))

# Demo-grade centres (the same kind of approximation the PinCode table holds), one per side of the city.
PINS = {
    "north": ("560064", "Yelahanka", "13.100700", "77.596300"),
    "south": ("560078", "JP Nagar", "12.906300", "77.585700"),
    "east": ("560066", "Whitefield", "12.969800", "77.750000"),
    "west": ("560040", "Vijayanagar", "12.971900", "77.537600"),
    "central": ("560001", "MG Road", "12.976600", "77.599300"),
}
NEAR = {"latitude": "12.906300", "longitude": "77.585700", "postal_code": "560078"}  # JP Nagar, ~2 km
FAR = {"latitude": "13.100700", "longitude": "77.596300", "postal_code": "560064"}  # Yelahanka, ~20 km


@pytest.fixture
def bengaluru(settings):
    settings.DELIVERY_RESTRICT_TO_SERVICE_AREAS = True
    area = ServiceArea.objects.get(name="Bengaluru")  # created by migration delivery.0008
    store = Store.objects.create(
        name="Jayanagar Store",
        code="BLR-1",
        kind=Store.Kind.STORE,
        address_line1="1 Test Road",
        area="Jayanagar",
        city="Bengaluru",
        state="Karnataka",
        postal_code="560041",
        latitude=JAYANAGAR[0],
        longitude=JAYANAGAR[1],
        own_riders=2,
    )
    zone = DeliveryZone.objects.create(
        store=store, name="Bengaluru city-wide", radius_km=Decimal("6"), service_area=area
    )
    _, drill = create_product(name="Drill", price="300.00", stock=5, store=store)
    for postal_code, name, lat, lng in PINS.values():
        PinCode.objects.create(postal_code=postal_code, area=name, city="Bengaluru", latitude=lat, longitude=lng)
    return {"area": area, "store": store, "zone": zone, "drill": drill}


def check(api_client, **params):
    res = api_client.get("/api/delivery/check/", params)
    assert res.status_code == 200, res.content
    return res.json()


# --- Every part of the city is deliverable ---------------------------------------------------------


@pytest.mark.parametrize("side", ["north", "south", "east", "west", "central"])
def test_every_side_of_bengaluru_is_deliverable(api_client, bengaluru, side):
    postal_code = PINS[side][0]
    data = check(api_client, postal_code=postal_code)
    assert data["serviceable"] is True and data["service_area"] == "Bengaluru"
    assert data["label"] and data["stores"][0]["name"] == "Jayanagar Store"


def test_a_valid_bengaluru_pin_needs_no_list_entry(api_client, bengaluru):
    """560103 (Bellandur) is in no zone list and has no centre on file: the PIN rule alone covers it."""
    assert not PinCode.objects.filter(postal_code="560103").exists()
    data = check(api_client, postal_code="560103")
    assert data["serviceable"] is True and data["service_area"] == "Bengaluru"
    # The distance is only a guess, so fast delivery is not promised; the real standard time is shown.
    assert data["fast_delivery_available"] is False
    assert "Pin your location on the map" in data["fast_unavailable_reason"]
    assert data["message"].startswith("🚚 Standard delivery · ")


@pytest.mark.parametrize("postal_code", ["411038", "400001", "110001", "562110"])
def test_pins_outside_bengaluru_are_refused_with_the_city_message(api_client, bengaluru, postal_code):
    data = check(api_client, postal_code=postal_code)
    assert data["serviceable"] is False and data["service_area"] is None
    assert data["message"] == OUTSIDE and data["stores"] == []


def test_invalid_pin_is_rejected(api_client, bengaluru):
    assert api_client.get("/api/delivery/check/", {"postal_code": "56004"}).status_code == 400


@pytest.mark.parametrize(
    ("params", "inside"),
    [
        ({"city": "Bangalore"}, True),
        ({"city": "bengaluru urban"}, True),
        ({"city": "Mysuru"}, False),
        ({"latitude": "12.971600", "longitude": "77.594600"}, True),  # map pin in the city, no PIN
        ({"latitude": "12.295800", "longitude": "76.639400"}, False),  # Mysuru
    ],
)
def test_city_name_or_map_pin_decides_without_a_pin(api_client, bengaluru, params, inside):
    data = check(api_client, **params)
    assert data["serviceable"] is inside
    assert data["message"] != OUTSIDE if inside else data["message"] == OUTSIDE


# --- Fast delivery stays the ETA engine's call ---------------------------------------------------------


def test_near_address_gets_fast_delivery(api_client, bengaluru):
    data = api_client.get("/api/delivery/estimate/", {"variant_id": bengaluru["drill"].id, **NEAR}).json()
    assert data["available"] is True and data["delivery_type"] == "fast"
    assert data["eta_minutes"] <= 60 and data["message"].startswith("⚡ Fast delivery · ")


def test_far_address_in_the_city_gets_normal_delivery_and_can_still_order(api_client, auth_client, user, bengaluru):
    data = api_client.get("/api/delivery/estimate/", {"variant_id": bengaluru["drill"].id, **FAR}).json()
    assert data["available"] is True and data["delivery_type"] == "standard"
    assert data["fast_delivery_possible"] is False
    assert data["fast_unavailable_reason"].startswith("Delivery would take about")
    assert data["window_start"] and data["label"]

    add_item(user, bengaluru["drill"].id, 1)
    address = create_address(
        user,
        postal_code="560064",
        city="Bengaluru",
        state="Karnataka",
        latitude=FAR["latitude"],
        longitude=FAR["longitude"],
    )
    preview = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    assert preview["can_place_order"] is True and preview["delivery"]["delivery_type"] == "standard"


def test_no_riders_means_no_fast_delivery_even_nearby(api_client, bengaluru):
    Store.objects.filter(pk=bengaluru["store"].pk).update(own_riders=0)
    data = api_client.get("/api/delivery/estimate/", {"variant_id": bengaluru["drill"].id, **NEAR}).json()
    assert data["available"] is True and data["delivery_type"] == "standard"
    assert data["fast_unavailable_reason"] == "No delivery partner is available right now."


def test_rider_on_duty_counts_for_fast_delivery(api_client, bengaluru):
    Store.objects.filter(pk=bengaluru["store"].pk).update(own_riders=0)
    create_partner(bengaluru["store"])
    data = api_client.get("/api/delivery/estimate/", {"variant_id": bengaluru["drill"].id, **NEAR}).json()
    assert data["delivery_type"] == "fast"


def test_bengaluru_address_with_no_stock_nearby(api_client, bengaluru):
    _, empty = create_product(name="Hinge", price="100.00", stock=0, store=bengaluru["store"])
    data = api_client.get("/api/delivery/estimate/", {"variant_id": empty.id, **NEAR}).json()
    assert data["available"] is False and data["reason_code"] == "insufficient_stock"
    # Still a Bengaluru address: the area itself is deliverable.
    assert check(api_client, **NEAR)["serviceable"] is True


# --- Checkout and listings ------------------------------------------------------------------------


def test_checkout_blocks_addresses_outside_bengaluru(auth_client, user, bengaluru):
    add_item(user, bengaluru["drill"].id, 1)
    address = create_address(user, postal_code="411038", city="Pune", state="Maharashtra")
    data = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    assert data["can_place_order"] is False
    assert data["blocking_issues"] == [{"code": "not_deliverable", "message": OUTSIDE}]
    res = auth_client.post("/api/orders/", {"address_id": address.id, "payment_method": "cod"}, format="json")
    assert res.status_code == 400 and res.json()["error"]["code"] == "not_deliverable"


def test_checkout_accepts_any_bengaluru_address(auth_client, user, bengaluru):
    add_item(user, bengaluru["drill"].id, 1)
    address = create_address(user, postal_code="560103", area="Bellandur", city="Bengaluru", state="Karnataka")
    data = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    assert data["can_place_order"] is True and data["delivery"]["delivery_type"] == "standard"


def test_listing_pin_context_uses_the_city_rule(bengaluru):
    assert pin_context("560078").serviceable is True
    outside = pin_context("411038")
    assert outside.serviceable is False and outside.message == OUTSIDE


def test_in_the_city_but_no_store_open_for_orders(api_client, bengaluru):
    Store.objects.filter(pk=bengaluru["store"].pk).update(accepts_orders=False)
    data = check(api_client, postal_code="560078")
    assert data["serviceable"] is False and data["service_area"] == "Bengaluru"
    assert data["message"].startswith("We deliver across Bengaluru, but no store can take orders right now")


# --- The rule itself and its configuration -------------------------------------------------------------


def test_area_rule_prefix_extra_and_excluded(bengaluru):
    area = bengaluru["area"]
    assert area.covers_postal_code("560041") and not area.covers_postal_code("562110")
    area.extra_postal_codes = "562110, 562149"
    area.excluded_postal_codes = "560300"
    assert area.covers_postal_code("562110") and not area.covers_postal_code("560300")
    assert area.covers_city("Bengaluru") and area.covers_city("BANGALORE.") and not area.covers_city("Pune")


def test_without_the_restriction_zones_alone_decide(api_client, bengaluru, settings):
    settings.DELIVERY_RESTRICT_TO_SERVICE_AREAS = False
    pune = Store.objects.create(
        name="Pune Store", code="PUN-1", kind=Store.Kind.STORE, address_line1="x", city="Pune", state="Maharashtra",
        postal_code="411038", latitude=Decimal("18.5074"), longitude=Decimal("73.8077"),
    )  # fmt: skip
    DeliveryZone.objects.create(store=pune, name="Pune 5 km", radius_km=Decimal("5"), postal_codes="411038")
    assert check(api_client, postal_code="411038")["serviceable"] is True
    settings.DELIVERY_RESTRICT_TO_SERVICE_AREAS = True
    assert check(api_client, postal_code="411038")["message"] == OUTSIDE


def test_admin_sees_service_areas_and_city_wide_zones(admin_client, bengaluru):
    areas = admin_client.get("/api/admin/service-areas/").json()
    assert [a["name"] for a in areas] == ["Bengaluru"] and areas[0]["postal_code_prefixes"] == "560"
    zones = admin_client.get("/api/admin/zones/").json()
    assert zones[0]["service_area"] == bengaluru["area"].pk and zones[0]["service_area_name"] == "Bengaluru"
    res = admin_client.patch(f"/api/admin/zones/{bengaluru['zone'].pk}/", {"service_area": None}, format="json")
    assert res.status_code == 200 and res.json()["service_area"] is None
