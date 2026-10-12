"""Dashboard: delivery charges settings (distance bands, first orders free, unloading fee)."""

import pytest

from apps.delivery.models import DeliveryCharges

pytestmark = [pytest.mark.django_db, pytest.mark.delivery_charges]
URL = "/api/admin/delivery-charges/"


def test_admin_reads_and_changes_the_delivery_charges(admin_client):
    data = admin_client.get(URL).json()
    assert data["distance_bands"][0] == {"up_to_km": "3", "fee": "30"} and data["free_first_orders"] == 3
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
