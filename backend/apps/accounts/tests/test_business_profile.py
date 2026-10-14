"""Professional buyers: self-declared buyer type, business name and GSTIN on the profile and addresses."""

import pytest

from apps.core.validators import gstin_checksum

pytestmark = pytest.mark.django_db


def _gstin(state: str = "29", pan: str = "AAGCB7383J") -> str:
    body = f"{state}{pan}1Z"
    return body + gstin_checksum(body)


def test_profile_defaults_to_individual(auth_client):
    body = auth_client.get("/api/profile/").json()
    assert (body["buyer_type"], body["business_name"], body["gstin"]) == ("individual", "", "")


def test_customer_sets_business_profile(auth_client, user):
    gstin = _gstin()
    res = auth_client.patch(
        "/api/profile/",
        {"buyer_type": "contractor", "business_name": "Asha Interiors", "gstin": f" {gstin.lower()} "},
        format="json",
    )
    assert res.status_code == 200, res.json()
    user.profile.refresh_from_db()
    assert (user.profile.buyer_type, user.profile.business_name, user.profile.gstin) == (
        "contractor",
        "Asha Interiors",
        gstin,
    )
    assert user.profile.is_professional
    assert auth_client.get("/api/auth/me/").json()["buyer_type"] == "contractor"
    # Clearing the GSTIN is allowed.
    assert auth_client.patch("/api/profile/", {"gstin": ""}, format="json").json()["gstin"] == ""


@pytest.mark.parametrize(
    "value,message",
    [
        ("29AAGCB7383J1Z", "15-character"),
        ("00AAGCB7383J1Z4", "state code"),
        ("wrong-check", "check character"),
    ],
)
def test_invalid_gstin_rejected(auth_client, user, value, message):
    if value == "wrong-check":
        valid = _gstin()
        value = valid[:-1] + ("A" if valid[-1] != "A" else "B")
    res = auth_client.patch("/api/profile/", {"gstin": value}, format="json")
    assert res.status_code == 400
    assert message in str(res.json())
    user.profile.refresh_from_db()
    assert user.profile.gstin == ""


def test_unknown_buyer_type_rejected(auth_client):
    assert auth_client.patch("/api/profile/", {"buyer_type": "wholesaler"}, format="json").status_code == 400


def test_business_address_with_gstin(auth_client):
    gstin = _gstin("29", "ABCDE1234F")
    body = {
        "name": "Site office",
        "phone": "9876543210",
        "address_line1": "12 MG Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
        "latitude": "12.975000",  # every address has its map pin
        "longitude": "77.606000",
        "address_type": "work",
        "business_name": "Asha Interiors",
        "gstin": gstin,
    }
    res = auth_client.post("/api/addresses/", body, format="json")
    assert res.status_code == 201, res.json()
    assert (res.json()["business_name"], res.json()["gstin"]) == ("Asha Interiors", gstin)
    wrong = gstin[:-1] + ("A" if gstin[-1] != "A" else "B")
    assert auth_client.post("/api/addresses/", {**body, "gstin": wrong}, format="json").status_code == 400
