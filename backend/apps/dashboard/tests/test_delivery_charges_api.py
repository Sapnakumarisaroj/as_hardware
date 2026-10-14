"""Dashboard: delivery charges settings (distance bands, first orders free, unloading fee)."""

import pytest

from apps.delivery.models import DeliveryCharges

pytestmark = [pytest.mark.django_db, pytest.mark.delivery_charges]
URL = "/api/admin/delivery-charges/"


def test_admin_reads_and_changes_the_delivery_charges(admin_client):
    data = admin_client.get(URL).json()
    # Shop policy defaults: ₹40 up to 5 km, ₹80 beyond; no "first orders free" promotion.
    assert data["distance_bands"] == [{"up_to_km": "5", "fee": "40"}, {"up_to_km": "60", "fee": "80"}]
    assert data["free_first_orders"] == 0
    assert data["unloading_fee"] == "199.00" and data["extra_per_km"] is None and "stores" in data
    bands = [{"up_to_km": 10, "fee": 100}, {"up_to_km": "4", "fee": "40.5"}]
    res = admin_client.patch(
        URL, {"distance_bands": bands, "extra_per_km": "12", "free_first_orders": 2}, format="json"
    )
    assert res.status_code == 200, res.json()
    saved = DeliveryCharges.load()
    assert saved.distance_bands == [{"up_to_km": "4", "fee": "40.50"}, {"up_to_km": "10", "fee": "100.00"}]
    assert str(saved.extra_per_km) == "12.00" and saved.free_first_orders == 2


def test_invalid_bands_are_refused(admin_client):
    res = admin_client.patch(URL, {"distance_bands": [{"up_to_km": "3", "fee": "-5"}]}, format="json")
    assert res.status_code == 400


def test_staff_may_read_but_not_change(staff_client, auth_client):
    assert staff_client.get(URL).status_code == 200
    assert staff_client.patch(URL, {"free_first_orders": 9}, format="json").status_code == 403
    assert auth_client.get(URL).status_code == 403


def test_zone_fixed_fee_is_sent_as_a_money_string(admin_client):
    """Regression: a zone's fixed fee went out as a JSON number (raw Decimal) and crashed the dashboard page."""
    from decimal import Decimal

    from apps.core.testing import create_store
    from apps.delivery.models import DeliveryZone

    store = create_store(zone=False)
    DeliveryZone.objects.create(
        store=store, name="Fixed fee", radius_km=Decimal("5"), delivery_fee_override=Decimal("30")
    )
    data = admin_client.get(URL).json()
    zones = [z for s in data["stores"] for z in s["zones"] if z["name"] == "Fixed fee"]
    assert zones and zones[0]["fee_override"] == "30.00"
