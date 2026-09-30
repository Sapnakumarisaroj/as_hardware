"""Who may call what. Every staff API is tried with every role; the backend is the authority."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.core.testing import create_coupon, create_product
from apps.delivery.tests.helpers import assign, create_partner, packed_order, store_at, zone_for
from apps.inventory.models import Inventory
from apps.support.models import SupportConversation

pytestmark = pytest.mark.django_db

# Readable by administrators and store managers.
STAFF_READ = [
    "/api/admin/session/",
    "/api/admin/summary/",
    "/api/admin/analytics/",
    "/api/admin/orders/",
    "/api/admin/products/",
    "/api/admin/variants/?q=drill",
    "/api/admin/categories/",
    "/api/admin/brands/",
    "/api/admin/stores/",
    "/api/admin/zones/",
    "/api/admin/pincodes/",
    "/api/admin/riders/",
    "/api/admin/jobs/",
    "/api/admin/support/",
    "/api/inventory/",
    "/api/inventory/movements/",
    "/api/delivery/shipments/",
    "/api/delivery/partners/",
    "/api/delivery/cod/",
    "/api/payments/refunds/",
]
# Readable by administrators only.
ADMIN_READ = ["/api/admin/offers/", "/api/admin/coupons/", "/api/admin/customers/", "/api/admin/users/"]

# Writes that only an administrator may make (method, url, body).
ADMIN_WRITES = [
    ("post", "/api/admin/products/", {"name": "X"}),
    ("post", "/api/admin/categories/", {"name": "X"}),
    ("post", "/api/admin/brands/", {"name": "X"}),
    ("post", "/api/admin/stores/", {"name": "X"}),
    ("post", "/api/admin/zones/", {"name": "X"}),
    ("post", "/api/admin/pincodes/", {"postal_code": "411001"}),
    ("post", "/api/admin/offers/", {"name": "X"}),
    ("post", "/api/admin/coupons/", {"code": "X"}),
]


def client_for(user) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


@pytest.fixture
def world(user, admin_user, staff_user, other_user):
    """Two stores with an order each; `staff_user` manages the first one only."""
    mine, theirs = store_at(0, name="Kothrud"), store_at(40, name="Hadapsar")
    zone_for(mine)
    zone_for(theirs)
    mine.managers.add(staff_user)
    _, drill = create_product(name="Drill", stock=10, store=mine)
    _, saw = create_product(name="Saw", stock=10, store=theirs)
    my_order = packed_order(user, (drill, 1), km_north=1)
    their_order = packed_order(other_user, (saw, 1), km_north=41)
    return {
        "mine": mine,
        "theirs": theirs,
        "my_order": my_order,
        "their_order": their_order,
        "drill": drill,
        "saw": saw,
    }


@pytest.mark.parametrize("url", STAFF_READ + ADMIN_READ)
def test_anonymous_is_turned_away(url):
    assert client_for(None).get(url).status_code == 401


@pytest.mark.parametrize("url", STAFF_READ + ADMIN_READ)
def test_customer_cannot_read_any_staff_api(url, user):
    assert client_for(user).get(url).status_code == 403


@pytest.mark.parametrize("url", [u for u in STAFF_READ + ADMIN_READ if not u.startswith("/api/delivery/")])
def test_rider_cannot_read_the_dashboard(url, delivery_user):
    assert client_for(delivery_user).get(url).status_code == 403


@pytest.mark.parametrize("url", ["/api/delivery/shipments/", "/api/delivery/partners/", "/api/delivery/cod/"])
def test_rider_cannot_read_staff_delivery_apis(url, delivery_user):
    assert client_for(delivery_user).get(url).status_code == 403


@pytest.mark.parametrize("url", STAFF_READ + ADMIN_READ)
def test_admin_reads_everything(url, admin_client):
    assert admin_client.get(url).status_code == 200


@pytest.mark.parametrize("url", STAFF_READ)
def test_store_manager_reads_the_staff_sections(url, staff_client):
    assert staff_client.get(url).status_code == 200


@pytest.mark.parametrize("url", ADMIN_READ)
def test_store_manager_cannot_read_admin_only_sections(url, staff_client):
    assert staff_client.get(url).status_code == 403


@pytest.mark.parametrize(("method", "url", "body"), ADMIN_WRITES)
@pytest.mark.parametrize("role", ["customer", "rider", "manager"])
def test_only_admin_writes_master_data(method, url, body, role, user, delivery_user, staff_user):
    actor = {"customer": user, "rider": delivery_user, "manager": staff_user}[role]
    response = getattr(client_for(actor), method)(url, body, format="json")
    assert response.status_code == 403


def test_customer_cannot_use_staff_actions(world, auth_client):
    order, shipment = world["my_order"], world["my_order"].shipments.get()
    inventory = Inventory.objects.get(variant=world["drill"])
    before = inventory.available_quantity
    attempts = [
        auth_client.post(f"/api/orders/{order.order_number}/transition/", {"status": "delivered"}, format="json"),
        auth_client.post(
            f"/api/inventory/{inventory.pk}/adjust/",
            {"movement_type": "adjustment", "quantity": 5, "reason": "free stock"},
            format="json",
        ),
        auth_client.post(f"/api/delivery/shipments/{shipment.pk}/assign/", {"partner_id": 1}, format="json"),
        auth_client.post(f"/api/delivery/shipments/{shipment.pk}/unassign/", {}, format="json"),
        auth_client.patch(f"/api/admin/users/{order.user_id}/", {"role": "admin"}, format="json"),
        auth_client.patch(f"/api/admin/stores/{world['mine'].pk}/", {"accepts_orders": False}, format="json"),
        auth_client.post("/api/returns/RET-NOPE/approve/", {}, format="json"),
        auth_client.post("/api/payments/refunds/00000000-0000-0000-0000-000000000000/retry/", {}, format="json"),
    ]
    assert [r.status_code for r in attempts] == [403] * len(attempts)
    inventory.refresh_from_db()
    assert inventory.available_quantity == before


# --- Store managers see and change their own stores only -----------------------------------------


def test_manager_sees_only_orders_of_their_stores(world, staff_client, admin_client):
    numbers = [o["order_number"] for o in staff_client.get("/api/admin/orders/").data["results"]]
    assert numbers == [world["my_order"].order_number]
    assert admin_client.get("/api/admin/orders/").data["count"] == 2

    assert staff_client.get(f"/api/admin/orders/{world['my_order'].order_number}/").status_code == 200
    assert staff_client.get(f"/api/admin/orders/{world['their_order'].order_number}/").status_code == 404


def test_manager_cannot_change_an_order_of_another_store(world, staff_client):
    url = f"/api/orders/{world['their_order'].order_number}/transition/"
    response = staff_client.post(url, {"status": "cancelled", "note": "x"}, format="json")
    assert response.status_code in (403, 404)
    world["their_order"].refresh_from_db()
    assert world["their_order"].status == "packed"


def test_manager_sees_only_their_stores_zones_and_stock(world, staff_client):
    stores = staff_client.get("/api/admin/stores/").data["results"]
    assert [s["name"] for s in stores] == ["Kothrud"]
    assert staff_client.get(f"/api/admin/stores/{world['theirs'].pk}/").status_code == 404

    zones = staff_client.get("/api/admin/zones/").data
    assert {z["store"] for z in zones} == {world["mine"].pk}

    stock = staff_client.get("/api/inventory/").data["results"]
    assert {row["store"] for row in stock} == {world["mine"].pk}

    session = staff_client.get("/api/admin/session/").data
    assert [s["id"] for s in session["stores"]] == [world["mine"].pk]
    assert session["is_admin"] is False
    assert "customers" not in session["sections"]
    assert "offers" not in session["sections"]


def test_manager_asking_for_another_store_gets_nothing(world, staff_client):
    other = world["theirs"].pk
    assert staff_client.get(f"/api/admin/summary/?store={other}").status_code == 404
    assert staff_client.get(f"/api/admin/analytics/?store={other}").status_code == 404
    assert staff_client.get(f"/api/admin/orders/?store={other}").status_code == 404
    assert staff_client.get(f"/api/inventory/?store={other}").data["count"] == 0


def test_manager_summary_counts_only_their_stores(world, staff_client, admin_client):
    mine = staff_client.get("/api/admin/summary/").data
    everything = admin_client.get("/api/admin/summary/").data
    assert mine["orders"]["total"] == 1
    assert everything["orders"]["total"] == 2
    assert mine["customers"] is None  # shop-wide figures are for administrators
    assert mine["products"] is None
    assert everything["customers"] is not None


def test_manager_may_change_how_their_store_runs_but_not_where_it_delivers(world, staff_client):
    url = f"/api/admin/stores/{world['mine'].pk}/"
    response = staff_client.patch(url, {"avg_prep_minutes": 25, "accepts_orders": False}, format="json")
    assert response.status_code == 200, response.data
    world["mine"].refresh_from_db()
    assert (world["mine"].avg_prep_minutes, world["mine"].accepts_orders) == (25, False)

    for body in (
        {"name": "My shop"},
        {"latitude": "18.6", "longitude": "73.9"},
        {"manager_ids": []},
        {"kind": "warehouse"},
    ):
        assert staff_client.patch(url, body, format="json").status_code == 403, body
    world["mine"].refresh_from_db()
    assert world["mine"].name == "Kothrud"

    other = f"/api/admin/stores/{world['theirs'].pk}/"
    assert staff_client.patch(other, {"accepts_orders": False}, format="json").status_code == 404
    assert staff_client.delete(url).status_code == 403

    zone = world["mine"].delivery_zones.first()
    assert staff_client.patch(f"/api/admin/zones/{zone.pk}/", {"radius_km": "50"}, format="json").status_code == 403
    zone.refresh_from_db()
    assert zone.radius_km == Decimal("5.00")


def test_manager_sees_riders_and_jobs_of_their_stores(world, staff_client, admin_client, admin_user):
    mine = create_partner(world["mine"], email="a@example.com")
    theirs = create_partner(world["theirs"], email="b@example.com")
    assign(world["my_order"].shipments.get(), mine, actor=admin_user)
    assign(world["their_order"].shipments.get(), theirs, actor=admin_user)

    riders = staff_client.get("/api/admin/riders/").data["results"]
    assert [r["partner_id"] for r in riders] == [mine.pk]
    assert riders[0]["active_assignments"] == 1
    assert staff_client.get(f"/api/admin/riders/{theirs.pk}/").status_code == 404

    jobs = staff_client.get("/api/admin/jobs/").data["results"]
    assert [j["order_number"] for j in jobs] == [world["my_order"].order_number]
    assert admin_client.get("/api/admin/jobs/").data["count"] == 2

    # Only administrators verify riders or change their capacity.
    body = {"max_active_assignments": 5}
    assert staff_client.patch(f"/api/admin/riders/{mine.pk}/", body, format="json").status_code == 403
    assert admin_client.patch(f"/api/admin/riders/{mine.pk}/", body, format="json").status_code == 200
    mine.refresh_from_db()
    assert mine.max_active_assignments == 5


def test_manager_cannot_assign_a_rider_at_another_store(world, staff_client):
    rider = create_partner(world["theirs"], email="b@example.com")
    shipment = world["their_order"].shipments.get()
    response = staff_client.post(
        f"/api/delivery/shipments/{shipment.pk}/assign/", {"partner_id": rider.pk}, format="json"
    )
    assert response.status_code in (403, 404)
    assert not shipment.assignments.exists()


def test_manager_sees_support_conversations_about_their_orders(world, staff_client, admin_client, user, other_user):
    mine = SupportConversation.objects.create(user=user, subject="Where is it?", order=world["my_order"])
    theirs = SupportConversation.objects.create(user=other_user, subject="Broken", order=world["their_order"])
    general = SupportConversation.objects.create(user=other_user, subject="General question")

    assert [c["id"] for c in staff_client.get("/api/admin/support/").data["results"]] == [mine.pk]
    assert staff_client.get(f"/api/admin/support/{theirs.pk}/").status_code == 404
    assert staff_client.post(f"/api/admin/support/{theirs.pk}/reply/", {"body": "hi"}, format="json").status_code == 404
    assert (
        staff_client.post(f"/api/admin/support/{general.pk}/reply/", {"body": "hi"}, format="json").status_code == 404
    )
    assert admin_client.get("/api/admin/support/").data["count"] == 3


def test_nothing_secret_is_ever_in_a_customer_record(world, admin_client, user):
    create_coupon()
    for url in ("/api/admin/customers/", f"/api/admin/customers/{user.pk}/", f"/api/admin/users/{user.pk}/"):
        response = admin_client.get(url)
        assert response.status_code == 200
        text = response.content.decode().lower()
        for secret in ("password", "pbkdf2", "token", "otp", "secret"):
            assert secret not in text, (url, secret)
