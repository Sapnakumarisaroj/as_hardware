import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.core.exceptions import ServiceError
from apps.core.testing import add_stock, create_product, create_store
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import InsufficientStock, apply_movement, total_available

pytestmark = pytest.mark.django_db
T = StockMovement.Type


@pytest.fixture
def inventory():
    _, variant = create_product()
    return add_stock(variant, 10)


def test_movement_lifecycle_and_ledger(inventory):
    apply_movement(inventory, T.RESERVATION, 4)
    assert (inventory.available_quantity, inventory.reserved_quantity) == (6, 4)
    apply_movement(inventory, T.RELEASE, 1)
    assert (inventory.available_quantity, inventory.reserved_quantity) == (7, 3)
    apply_movement(inventory, T.SALE, 3)
    assert (inventory.available_quantity, inventory.reserved_quantity) == (7, 0)
    apply_movement(inventory, T.RETURN, 1)
    apply_movement(inventory, T.ADJUSTMENT, -2, reason="Damaged in storage")
    inventory.refresh_from_db()
    assert (inventory.available_quantity, inventory.reserved_quantity) == (6, 0)
    ledger = list(inventory.movements.order_by("id").values_list("movement_type", "available_after", "reserved_after"))
    assert ledger[0] == (T.PURCHASE, 10, 0)
    assert ledger[-1] == (T.ADJUSTMENT, 6, 0)


def test_available_stock_can_never_go_negative(inventory):
    with pytest.raises(InsufficientStock):
        apply_movement(inventory, T.RESERVATION, 11)
    with pytest.raises(InsufficientStock):
        apply_movement(inventory, T.ADJUSTMENT, -11, reason="count")
    inventory.refresh_from_db()
    assert inventory.available_quantity == 10
    assert inventory.movements.count() == 1  # failed moves left no ledger rows


def test_database_constraint_backs_up_the_service(inventory):
    with pytest.raises(IntegrityError), transaction.atomic():
        Inventory.objects.filter(pk=inventory.pk).update(available_quantity=-1)


def test_cannot_release_or_sell_more_than_reserved(inventory):
    apply_movement(inventory, T.RESERVATION, 2)
    with pytest.raises(ServiceError):
        apply_movement(inventory, T.SALE, 3)


def test_adjustment_requires_reason_and_positive_quantities(inventory):
    with pytest.raises(ServiceError):
        apply_movement(inventory, T.ADJUSTMENT, 5)
    with pytest.raises(ServiceError):
        apply_movement(inventory, T.PURCHASE, 0)


def test_total_available_ignores_warehouses_and_inactive_stores():
    _, variant = create_product()
    add_stock(variant, 5, store=create_store())
    add_stock(variant, 100, store=create_store(kind="warehouse"))
    add_stock(variant, 7, store=create_store(accepts_orders=False))
    assert total_available(variant.id) == 5


def test_inventory_api_is_staff_only(auth_client, staff_client, staff_user, delivery_user, inventory):
    assert auth_client.get("/api/inventory/").status_code == 403
    rider = APIClient()
    rider.force_authenticate(delivery_user)
    assert rider.get("/api/inventory/").status_code == 403
    # A manager with no assigned store sees nothing.
    assert staff_client.get("/api/inventory/").json()["count"] == 0
    inventory.store.managers.add(staff_user)
    res = staff_client.get("/api/inventory/")
    assert res.status_code == 200 and res.json()["count"] == 1


def test_manager_is_limited_to_assigned_stores(staff_client, staff_user, admin_client, inventory):
    other_store = create_store()
    _, variant = create_product()
    other_inv = add_stock(variant, 4, store=other_store)
    inventory.store.managers.add(staff_user)

    ids = [row["id"] for row in staff_client.get("/api/inventory/").json()["results"]]
    assert ids == [inventory.pk]
    adjust = {"movement_type": "purchase", "quantity": 1, "reason": "x"}
    assert staff_client.post(f"/api/inventory/{other_inv.pk}/adjust/", adjust, format="json").status_code == 404
    create = {"store": other_store.pk, "variant": inventory.variant_id, "opening_quantity": 5}
    assert staff_client.post("/api/inventory/", create, format="json").status_code == 403
    movement_stores = {m["store_code"] for m in staff_client.get("/api/inventory/movements/").json()["results"]}
    assert movement_stores == {inventory.store.code}
    assert admin_client.get("/api/inventory/").json()["count"] == 2  # admins see every store


def test_staff_adjusts_stock_via_api(staff_client, staff_user, inventory):
    inventory.store.managers.add(staff_user)
    res = staff_client.post(
        f"/api/inventory/{inventory.pk}/adjust/",
        {"movement_type": "purchase", "quantity": 5, "reason": "Supplier delivery"},
        format="json",
    )
    assert res.status_code == 201
    assert res.json()["available_after"] == 15
    # Quantities cannot be overwritten directly.
    staff_client.patch(f"/api/inventory/{inventory.pk}/", {"available_quantity": 999}, format="json")
    inventory.refresh_from_db()
    assert inventory.available_quantity == 15
    over = staff_client.post(
        f"/api/inventory/{inventory.pk}/adjust/",
        {"movement_type": "adjustment", "quantity": -50, "reason": "count"},
        format="json",
    )
    assert over.status_code == 409
    assert over.json()["error"]["code"] == "insufficient_stock"
    movements = staff_client.get("/api/inventory/movements/", {"inventory": inventory.pk})
    assert movements.status_code == 200 and movements.json()["count"] == 2
