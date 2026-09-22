"""Role-based access across apps: each role reaches what it should, and nothing it shouldn't."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.carts.services import add_item
from apps.core.testing import add_stock, create_address, create_product, create_store
from apps.delivery.models import DeliveryAssignment, DeliveryPartner
from apps.orders.models import Order
from apps.orders.services import place_order

pytestmark = pytest.mark.django_db

User = get_user_model()

STAFF_ONLY = ["/api/inventory/", "/api/inventory/movements/"]
ADMIN_ONLY = ["/api/admin/users/"]
DELIVERY_ONLY = ["/api/delivery/me/", "/api/delivery/assignments/", "/api/delivery/earnings/"]


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def two_stores(user):
    """Store A and store B, each with stock and one customer order."""
    store_a, store_b = create_store(), create_store()
    _, variant = create_product(name="Hammer", price="250.00", mrp="300.00", stock=10, store=store_a)
    inv_b = add_stock(variant, 8, store=store_b)
    address = create_address(user)
    orders = []
    for _ in range(2):
        add_item(user, variant.id, 1)
        order, _ = place_order(user=user, address_id=address.id, payment_method="cod")
        orders.append(order)
    Order.objects.filter(pk=orders[1].pk).update(store=store_b)
    return {
        "a": store_a,
        "b": store_b,
        "inv_b": inv_b,
        "order_a": orders[0],
        "order_b": Order.objects.get(pk=orders[1].pk),
    }


@pytest.fixture
def other_rider(db):
    rider = User.objects.create_user(
        "rider2@example.com", "S3cure-pass!", role="delivery_partner", full_name="Second Rider", phone="9123456781"
    )
    DeliveryPartner.objects.create(user=rider, phone="9123456781")
    return rider


# --- Admin ----------------------------------------------------------------------------------


def test_admin_lists_filters_and_manages_users(admin_client, admin_user, user, staff_user, two_stores):
    res = admin_client.get("/api/admin/users/")
    assert res.status_code == 200
    emails = {row["email"] for row in res.json()["results"]}
    assert {admin_user.email, user.email, staff_user.email} <= emails
    assert "password" not in res.json()["results"][0]

    managers = admin_client.get("/api/admin/users/", {"role": "store_manager"}).json()["results"]
    assert [row["email"] for row in managers] == [staff_user.email]
    assert admin_client.get(f"/api/admin/users/{user.pk}/").status_code == 200

    # Promote the customer to store manager of store A, then deactivate them.
    res = admin_client.patch(
        f"/api/admin/users/{user.pk}/",
        {"role": "store_manager", "managed_store_ids": [two_stores["a"].pk]},
        format="json",
    )
    assert res.status_code == 200, res.json()
    assert res.json()["role"] == "store_manager"
    assert [s["id"] for s in res.json()["managed_stores"]] == [two_stores["a"].pk]

    res = admin_client.patch(f"/api/admin/users/{user.pk}/", {"is_active": False}, format="json")
    assert res.status_code == 200 and res.json()["is_active"] is False


def test_admin_cannot_change_own_role_or_deactivate_self(admin_client, admin_user):
    url = f"/api/admin/users/{admin_user.pk}/"
    assert admin_client.patch(url, {"role": "customer"}, format="json").status_code == 400
    assert admin_client.patch(url, {"is_active": False}, format="json").status_code == 400
    admin_user.refresh_from_db()
    assert admin_user.role == "admin" and admin_user.is_active


def test_admin_sees_every_store_and_manages_catalog(admin_client, two_stores):
    assert admin_client.get("/api/orders/").json()["count"] == 2
    assert admin_client.get("/api/inventory/").json()["count"] == 2
    res = admin_client.post("/api/brands/", {"name": "Role Test Brand"}, format="json")
    assert res.status_code == 201


def test_admin_sees_all_support_conversations(admin_client, auth_client):
    res = auth_client.post(
        "/api/support/conversations/", {"subject": "Where is my order?", "message": "Hi"}, format="json"
    )
    assert res.status_code == 201, res.json()
    assert admin_client.get("/api/support/conversations/").json()["count"] == 1


# --- Store manager --------------------------------------------------------------------------


def test_manager_reaches_only_assigned_store(staff_client, staff_user, two_stores):
    two_stores["a"].managers.add(staff_user)
    order_a, order_b = two_stores["order_a"], two_stores["order_b"]

    inv = staff_client.get("/api/inventory/").json()["results"]
    assert {row["store_code"] for row in inv} == {two_stores["a"].code}
    assert staff_client.get(f"/api/inventory/{two_stores['inv_b'].pk}/").status_code == 404

    numbers = [row["order_number"] for row in staff_client.get("/api/orders/").json()["results"]]
    assert numbers == [order_a.order_number]
    assert staff_client.get(f"/api/orders/{order_a.order_number}/").status_code == 200
    assert staff_client.get(f"/api/orders/{order_b.order_number}/").status_code == 404
    res = staff_client.post(f"/api/orders/{order_b.order_number}/transition/", {"status": "processing"}, format="json")
    assert res.status_code == 404
    res = staff_client.post(f"/api/orders/{order_a.order_number}/transition/", {"status": "processing"}, format="json")
    assert res.status_code == 200 and res.json()["status"] == "processing"


def test_manager_cannot_use_admin_or_delivery_endpoints(staff_client, staff_user, user):
    for url in ADMIN_ONLY + DELIVERY_ONLY:
        assert staff_client.get(url).status_code == 403, url
    assert staff_client.patch(f"/api/admin/users/{user.pk}/", {"role": "admin"}, format="json").status_code == 403
    assert staff_client.post("/api/brands/", {"name": "Nope"}, format="json").status_code == 403
    user.refresh_from_db()
    assert user.role == "customer"


# --- Delivery partner -----------------------------------------------------------------------


def test_rider_sees_only_own_profile_assignments_and_earnings(delivery_user, other_rider, two_stores):
    mine = DeliveryAssignment.objects.create(
        order=two_stores["order_a"],
        partner=delivery_user.delivery_partner,
        status=DeliveryAssignment.Status.DELIVERED,
        delivered_at=timezone.now(),
        earning_amount=Decimal("40.00"),
    )
    theirs = DeliveryAssignment.objects.create(
        order=two_stores["order_b"],
        partner=other_rider.delivery_partner,
        status=DeliveryAssignment.Status.DELIVERED,
        delivered_at=timezone.now(),
        earning_amount=Decimal("55.00"),
    )
    rider = _client(delivery_user)

    me = rider.get("/api/delivery/me/")
    assert me.status_code == 200
    assert (me.json()["full_name"], me.json()["phone"]) == ("Ravi Rider", "9123456780")

    ids = [row["id"] for row in rider.get("/api/delivery/assignments/").json()["results"]]
    assert ids == [mine.pk]
    assert rider.get(f"/api/delivery/assignments/{mine.pk}/").status_code == 200
    assert rider.get(f"/api/delivery/assignments/{theirs.pk}/").status_code == 404

    earnings = rider.get("/api/delivery/earnings/").json()
    assert earnings["delivered_count"] == 1
    assert Decimal(earnings["total_earnings"]) == Decimal("40.00")


def test_rider_cannot_use_admin_or_staff_endpoints(delivery_user, two_stores):
    rider = _client(delivery_user)
    for url in ADMIN_ONLY + STAFF_ONLY:
        assert rider.get(url).status_code == 403, url
    number = two_stores["order_a"].order_number
    assert rider.post(f"/api/orders/{number}/transition/", {"status": "processing"}, format="json").status_code == 403
    assert rider.get(f"/api/orders/{number}/").status_code == 404  # not their order


# --- Customer and anonymous -----------------------------------------------------------------


def test_customer_cannot_use_staff_admin_or_delivery_endpoints(auth_client, two_stores):
    for url in ADMIN_ONLY + STAFF_ONLY + DELIVERY_ONLY:
        assert auth_client.get(url).status_code == 403, url
    assert auth_client.post("/api/brands/", {"name": "Nope"}, format="json").status_code == 403


def test_anonymous_is_rejected_everywhere(api_client):
    for url in ADMIN_ONLY + STAFF_ONLY + DELIVERY_ONLY + ["/api/orders/", "/api/auth/me/"]:
        assert api_client.get(url).status_code == 401, url
