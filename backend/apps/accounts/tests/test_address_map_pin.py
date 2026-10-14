"""Every delivery address needs a map pin: required when adding or editing, and checkout refuses an address
without one (old addresses saved before the rule are completed by editing them). Delivery is still priced by
the policy (₹40 up to 5 km, ₹80 beyond, free from ₹2,000) and stays Bengaluru-only where that is switched on."""

from decimal import Decimal

import pytest

from apps.accounts.models import Address
from apps.core.testing import create_address, create_product, create_store
from apps.delivery.models import DeliveryZone, ServiceArea

pytestmark = pytest.mark.django_db
URL = "/api/addresses/"
STORE_LAT, STORE_LNG = Decimal("13.037555"), Decimal("77.674350")  # BLR-01
BODY = {
    "name": "Asha",
    "phone": "9876543210",
    "address_line1": "12 Test Road",
    "city": "Bengaluru",
    "state": "Karnataka",
    "postal_code": "560043",
}


def _pin(km_north: float) -> dict:
    """A synthetic test pin due north of the store (≈ 0.009° of latitude per km, straight line)."""
    return {"latitude": f"{STORE_LAT + Decimal(str(km_north)) * Decimal('0.009'):.6f}", "longitude": f"{STORE_LNG:.6f}"}


# --- Adding and editing ------------------------------------------------------------------------------


def test_adding_an_address_without_a_pin_is_refused(auth_client):
    res = auth_client.post(URL, BODY, format="json")
    assert res.status_code == 400 and "location" in res.json()["error"]["details"]
    assert not Address.objects.exists()


@pytest.mark.parametrize("half", [{"latitude": "13.000000"}, {"longitude": "77.600000"}])
def test_half_a_pin_is_refused(auth_client, half):
    assert auth_client.post(URL, {**BODY, **half}, format="json").status_code == 400


@pytest.mark.parametrize("bad", [{"latitude": "95", "longitude": "77.6"}, {"latitude": "13", "longitude": "190"}])
def test_impossible_coordinates_are_refused(auth_client, bad):
    assert auth_client.post(URL, {**BODY, **bad}, format="json").status_code == 400


def test_adding_with_a_pin_saves_it(auth_client):
    res = auth_client.post(URL, {**BODY, **_pin(2)}, format="json")
    assert res.status_code == 201, res.json()
    saved = Address.objects.get()
    assert saved.has_map_pin and f"{saved.latitude:.6f}" == _pin(2)["latitude"]


def test_editing_keeps_an_existing_pin_and_can_move_it(auth_client, user):
    address = create_address(user, **{k: Decimal(v) for k, v in _pin(1).items()})
    assert auth_client.patch(f"{URL}{address.id}/", {"landmark": "Near the park"}, format="json").status_code == 200
    res = auth_client.patch(f"{URL}{address.id}/", _pin(3), format="json")
    assert res.status_code == 200 and res.json()["latitude"] == _pin(3)["latitude"]
    # The pin can be moved but not removed.
    removed = auth_client.patch(f"{URL}{address.id}/", {"latitude": None, "longitude": None}, format="json")
    assert removed.status_code == 400
    assert Address.objects.get(pk=address.pk).has_map_pin


def test_an_old_address_without_a_pin_must_get_one_when_edited(auth_client, user):
    old = create_address(user, latitude=None, longitude=None)
    res = auth_client.patch(f"{URL}{old.id}/", {"landmark": "Near the park"}, format="json")
    assert res.status_code == 400 and "location" in res.json()["error"]["details"]
    assert (
        auth_client.patch(f"{URL}{old.id}/", {"landmark": "Near the park", **_pin(1)}, format="json").status_code == 200
    )
    assert Address.objects.get(pk=old.pk).has_map_pin


def test_old_addresses_are_listed_with_their_missing_pin(auth_client, user):
    create_address(user, latitude=None, longitude=None)
    row = auth_client.get(URL).json()[0]
    assert row["latitude"] is None and row["longitude"] is None  # the site shows "Map pin missing"


# --- Checkout ----------------------------------------------------------------------------------------


@pytest.fixture
def shop(settings):
    settings.FREE_DELIVERY_MIN_ORDER = Decimal("2000.00")  # the shop's policy (shared test settings pin ₹499)
    store = create_store(zone=False, latitude=STORE_LAT, longitude=STORE_LNG, city="Bengaluru", postal_code="560113")
    DeliveryZone.objects.create(store=store, name="Bengaluru", radius_km=Decimal("60"))
    _, small = create_product(name="Hinge", price="500.00", mrp="600.00", stock=50, store=store)
    _, big = create_product(name="Plywood", price="2000.00", mrp="2400.00", stock=50, store=store)
    return {"small": small, "big": big}


def _preview(client, address, variant):
    client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": 1}, format="json")
    res = client.post("/api/checkout/preview/", {"address_id": address.id}, format="json")
    assert res.status_code == 200, res.json()
    return res.json()


def test_checkout_is_blocked_for_an_address_without_a_pin(auth_client, user, shop):
    old = create_address(user, city="Bengaluru", state="Karnataka", postal_code="560043", latitude=None, longitude=None)
    data = _preview(auth_client, old, shop["small"])
    assert data["can_place_order"] is False
    issue = next(i for i in data["blocking_issues"] if i["code"] == "address_location_required")
    assert "map" in issue["message"]
    res = auth_client.post("/api/orders/", {"address_id": old.id, "payment_method": "cod"}, format="json")
    assert res.status_code == 400 and res.json()["error"]["code"] == "address_location_required"


def test_once_pinned_the_same_address_checks_out(auth_client, user, shop):
    old = create_address(user, city="Bengaluru", state="Karnataka", postal_code="560043", latitude=None, longitude=None)
    auth_client.patch(f"{URL}{old.id}/", _pin(2), format="json")
    data = _preview(auth_client, old, shop["small"])
    assert data["can_place_order"] is True and data["blocking_issues"] == []
    res = auth_client.post(
        "/api/orders/",
        {"address_id": old.id, "payment_method": "cod", "expected_total": data["totals"]["grand_total"]},
        format="json",
    )
    assert res.status_code == 201, res.json()


@pytest.mark.delivery_charges
@pytest.mark.parametrize(
    ("km_north", "variant", "fee"),
    [
        (2, "small", "40.00"),
        (3.5, "small", "40.00"),
        (4, "small", "80.00"),
        (20, "small", "80.00"),
        (20, "big", "0.00"),
    ],
)
def test_pinned_addresses_are_charged_by_the_delivery_policy(auth_client, user, shop, km_north, variant, fee):
    """Straight line × 1.35 (road estimate): 3.5 km → 4.7 km (₹40); 4 km → 5.4 km (₹80); ₹2,000 → free."""
    address = create_address(user, city="Bengaluru", state="Karnataka", postal_code="560043",
                             **{k: Decimal(v) for k, v in _pin(km_north).items()})  # fmt: skip
    data = _preview(auth_client, address, shop[variant])
    assert data["totals"]["delivery_fee"] == fee and data["can_place_order"] is True


def test_bengaluru_only_still_applies_to_pinned_addresses(auth_client, user, shop, settings):
    settings.DELIVERY_RESTRICT_TO_SERVICE_AREAS = True
    ServiceArea.objects.get_or_create(
        name="Bengaluru", defaults={"postal_code_prefixes": "560", "city_names": "Bengaluru"}
    )
    outside = create_address(user, city="Hosur", state="Tamil Nadu", postal_code="635109",
                             **{k: Decimal(v) for k, v in _pin(1).items()})  # fmt: skip
    data = _preview(auth_client, outside, shop["small"])
    assert data["can_place_order"] is False
    assert any(i["code"] == "not_deliverable" for i in data["blocking_issues"])
