"""Approved delivery policy: free from ₹2,000; below it ₹40 up to 5 km and ₹80 beyond 5 km (up to 60 km and past
it); no "first orders free" promotion. Uses the shipped defaults (no conftest override) and BLR-01's coordinates.

Distance is the existing estimate: straight line × ROAD_DISTANCE_FACTOR (1.35) with the haversine provider. These
tests place customer pins at known straight-line distances; they don't claim the result is a measured road distance.
"""

import math
from decimal import Decimal

import pytest
from django.conf import settings

from apps.core.testing import create_address, create_product, create_store
from apps.delivery.fulfillment import distance_fee
from apps.delivery.models import DeliveryCharges, DeliveryZone

pytestmark = [pytest.mark.django_db, pytest.mark.delivery_charges]
STORE_LAT, STORE_LNG = Decimal("13.037555"), Decimal("77.674350")  # BLR-01
KM_PER_DEGREE_LAT = 6371.0088 * math.pi / 180


def _north_of_store(road_km: float) -> Decimal:
    """Latitude due north of the store whose estimated road distance is `road_km`."""
    straight = road_km / settings.ROAD_DISTANCE_FACTOR
    return (STORE_LAT + Decimal(str(straight / KM_PER_DEGREE_LAT))).quantize(Decimal("0.000001"))


@pytest.fixture
def shop(user, settings):
    settings.FREE_DELIVERY_MIN_ORDER = Decimal("2000.00")  # the shop's policy (shared test settings pin ₹499)
    store = create_store(zone=False, latitude=STORE_LAT, longitude=STORE_LNG, city="Bengaluru", postal_code="560113")
    DeliveryZone.objects.create(store=store, name="Bengaluru", radius_km=Decimal("60"))
    _, small = create_product(name="Hinge", price="500.00", mrp="600.00", stock=100, store=store)
    _, big = create_product(name="Plywood sheet", price="2000.00", mrp="2400.00", stock=100, store=store)
    return {"store": store, "small": small, "big": big, "user": user}


def _fee(client, shop, road_km, variant):
    address = create_address(
        shop["user"], city="Bengaluru", state="Karnataka", postal_code="560043",
        latitude=_north_of_store(road_km), longitude=STORE_LNG,
    )  # fmt: skip
    client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": 1}, format="json")
    res = client.post("/api/checkout/preview/", {"address_id": address.id}, format="json")
    assert res.status_code == 200, res.json()
    data = res.json()
    for item in data["cart"]["items"]:
        client.delete(f"/api/cart/items/{item['id']}/")
    return data


def test_policy_bands_are_the_shipped_defaults_and_the_promotion_is_off():
    charges = DeliveryCharges.load()  # a fresh database without the shop-setup file gets the policy, not old values
    assert charges.distance_bands == [{"up_to_km": "5", "fee": "40"}, {"up_to_km": "60", "fee": "80"}]
    assert charges.free_first_orders == 0 and charges.extra_per_km is None


@pytest.mark.parametrize(
    ("road_km", "fee"),
    [(0.5, "40.00"), (4.99, "40.00"), (5, "40.00"), (5.01, "80.00"), (12, "80.00"), (60, "80.00"), (75, "80.00")],
)
def test_band_fee_at_and_around_5_km(road_km, fee):
    assert distance_fee(road_km) == Decimal(fee)


def test_checkout_charges_40_just_inside_5_km(auth_client, shop):
    delivery = _fee(auth_client, shop, 4.9, shop["small"])["delivery"]
    assert delivery["fee"] == "40.00" and 4.8 <= delivery["distance_km"] <= 5.0


def test_checkout_charges_80_just_beyond_5_km(auth_client, shop):
    delivery = _fee(auth_client, shop, 5.2, shop["small"])["delivery"]
    assert delivery["fee"] == "80.00" and delivery["distance_km"] > 5


def test_checkout_charges_80_far_across_bengaluru(auth_client, shop):
    assert _fee(auth_client, shop, 25, shop["small"])["delivery"]["fee"] == "80.00"


@pytest.mark.parametrize("road_km", [2, 25])
def test_orders_of_2000_or_more_ship_free_near_or_far(auth_client, shop, road_km):
    data = _fee(auth_client, shop, road_km, shop["big"])  # exactly ₹2,000
    assert data["totals"]["delivery_fee"] == "0.00" and data["delivery"]["free_delivery_min_order"] == "2000.00"


def test_a_new_customers_first_order_pays_the_fee(auth_client, shop):
    """The removed promotion can't make a first order below ₹2,000 free."""
    data = _fee(auth_client, shop, 2, shop["small"])
    assert data["totals"]["delivery_fee"] == "40.00"
    assert data["totals"]["first_order_free_delivery"] is False
    assert "first" not in (data["totals"]["free_delivery_reason"] or "").lower()
