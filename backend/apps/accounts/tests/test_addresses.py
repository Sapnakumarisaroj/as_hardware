import pytest

from apps.accounts.models import Address, CustomerProfile
from apps.accounts.services import delete_address, set_default_address
from apps.core.testing import create_address

pytestmark = pytest.mark.django_db

PAYLOAD = {
    "name": "Asha Kumar",
    "phone": "+91 98765 43210",
    "address_line1": "Flat 4, Sunrise Apts",
    "area": "Kothrud",
    "city": "Pune",
    "state": "Maharashtra",
    "postal_code": "411038",
    "latitude": "18.507400",
    "longitude": "73.807700",
    "address_type": "home",
}


def test_profile_created_for_new_user(user):
    assert CustomerProfile.objects.filter(user=user).exists()


def test_first_address_becomes_default_and_only_one_default(user):
    a = create_address(user)
    b = create_address(user, name="Office", is_default=True)
    a.refresh_from_db()
    assert b.is_default and not a.is_default
    set_default_address(a)
    assert list(Address.objects.filter(user=user, is_default=True)) == [a]


def test_deleting_default_promotes_another(user):
    a = create_address(user)
    b = create_address(user, name="Office")
    delete_address(a)
    b.refresh_from_db()
    assert b.is_default
    assert Address.all_objects.get(pk=a.pk).is_deleted


def test_address_api_crud_and_validation(auth_client):
    res = auth_client.post("/api/addresses/", PAYLOAD, format="json")
    assert res.status_code == 201, res.json()
    body = res.json()
    assert body["phone"] == "9876543210" and body["is_default"] is True

    bad = auth_client.post("/api/addresses/", dict(PAYLOAD, postal_code="12345", phone="12345"), format="json")
    assert bad.status_code == 400
    assert set(bad.json()["error"]["details"]) >= {"postal_code", "phone"}

    res = auth_client.patch(f"/api/addresses/{body['id']}/", {"landmark": "Near park"}, format="json")
    assert res.status_code == 200 and res.json()["landmark"] == "Near park"
    assert auth_client.delete(f"/api/addresses/{body['id']}/").status_code == 204
    assert auth_client.get("/api/addresses/").json() == []


def test_addresses_are_private(auth_client, other_user):
    theirs = create_address(other_user)
    assert auth_client.get("/api/addresses/").json() == []
    assert auth_client.get(f"/api/addresses/{theirs.id}/").status_code == 404
    assert auth_client.delete(f"/api/addresses/{theirs.id}/").status_code == 404
