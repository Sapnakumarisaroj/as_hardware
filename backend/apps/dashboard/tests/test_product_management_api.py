"""Dashboard product management (/api/admin/products/ and /api/inventory/): only admins change the
catalogue, prices/HSN/SKUs are validated, archived products keep their SKU, and stock moves only
through the ledger with a reason, never touching what is reserved for orders."""

import pytest

from apps.catalog.models import Product, ProductVariant
from apps.core.models import AuditLog
from apps.core.testing import create_category, create_product, create_store
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import apply_movement

from .test_management import product_body

pytestmark = pytest.mark.django_db

URL = "/api/admin/products/"


def _detail(product):
    return f"{URL}{product.pk}/"


# --- permissions --------------------------------------------------------------------------------


def test_only_admins_change_products(staff_client, auth_client, api_client):
    category = create_category()
    product, _ = create_product(name="Pipe Wrench")
    for client, read in ((staff_client, 200), (auth_client, 403), (api_client, 401)):
        assert client.get(URL).status_code == read
        attempts = [
            client.post(URL, product_body(category), format="json"),
            client.patch(_detail(product), {"name": "Hacked", "is_published": False}, format="json"),
            client.delete(_detail(product)),
            client.post(f"{_detail(product)}restore/"),
        ]
        expected = 403 if read != 401 else 401
        assert [r.status_code for r in attempts] == [expected] * 4
    product.refresh_from_db()
    assert product.name == "Pipe Wrench" and product.is_published and not product.is_deleted
    assert not Product.all_objects.filter(sku="AG-850").exists()


# --- validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("variant", "field"),
    [
        ({"sku": "X-1", "mrp": "100.00", "price": "120.00"}, "price"),  # above MRP
        ({"sku": "X-1", "mrp": "100.00", "price": "0.00"}, "price"),
        ({"sku": "X-1", "mrp": "-1.00", "price": "1.00"}, "mrp"),
    ],
)
def test_invalid_prices_are_refused(admin_client, variant, field):
    res = admin_client.post(URL, product_body(create_category(), variants=[variant]), format="json")
    assert res.status_code == 400 and field in str(res.json())
    assert not Product.all_objects.filter(sku="AG-850").exists()


@pytest.mark.parametrize("hsn", ["84AB", "123", "12345", "8467290012"])
def test_invalid_hsn_is_refused(admin_client, hsn):
    res = admin_client.post(URL, product_body(create_category(), hsn_code=hsn), format="json")
    assert res.status_code == 400 and "hsn_code" in res.json()["error"]["details"]


def test_valid_gst_and_hsn_are_saved_and_legacy_hsn_does_not_block_edits(admin_client):
    res = admin_client.post(URL, product_body(create_category(), hsn_code="846729", gst_rate="12.00"), format="json")
    assert res.status_code == 201, res.json()
    assert (res.json()["hsn_code"], res.json()["gst_rate"]) == ("846729", "12.00")
    legacy, _ = create_product(hsn_code="84-67")
    res = admin_client.patch(_detail(legacy), {"name": "Renamed", "hsn_code": "84-67"}, format="json")
    assert res.status_code == 200, res.json()
    assert admin_client.patch(_detail(legacy), {"gst_rate": "55"}, format="json").status_code == 400


def test_sku_of_an_archived_product_is_refused_not_a_server_error(admin_client):
    archived, _ = create_product(name="Old Grinder")
    archived.delete()
    for sku in (archived.sku, archived.sku.lower()):
        res = admin_client.post(URL, product_body(create_category(), sku=sku), format="json")
        assert res.status_code == 400, res.status_code
        assert "already used by an archived product" in str(res.json()["error"])
    res = admin_client.post(URL, product_body(create_category(), slug=archived.slug), format="json")
    assert res.status_code == 400 and "archived product" in str(res.json()["error"])


# --- variants and updates -----------------------------------------------------------------------


def test_admin_edits_variants_prices_and_details_with_audit(admin_client, admin_user):
    res = admin_client.post(URL, product_body(create_category()), format="json")
    product = Product.objects.get(pk=res.json()["id"])
    std, kit = product.variants.order_by("sort_order")
    body = {
        "name": "Angle Grinder 900W",
        "description": "Updated.",
        "variants": [
            {"id": std.pk, "sku": std.sku, "mrp": "3300.00", "price": "2899.00"},
            {"id": kit.pk, "sku": kit.sku, "mrp": kit.mrp, "price": kit.price, "is_active": False},
            {"sku": "AG-850-PRO", "name": "Pro", "mrp": "4500.00", "price": "3999.00"},
        ],
    }
    res = admin_client.patch(_detail(product), body, format="json")
    assert res.status_code == 200, res.json()
    std.refresh_from_db()
    kit.refresh_from_db()
    assert (std.mrp, std.price) == (3300, 2899) and not kit.is_active
    assert product.variants.count() == 3  # a variant is switched off, never removed
    log = AuditLog.objects.filter(action="product.update", target_id=str(product.pk)).get()
    assert log.actor == admin_user and "variants" in log.changes["fields"]


def test_variant_of_another_product_cannot_be_edited(admin_client):
    product, _ = create_product()
    _, foreign = create_product(name="Other")
    body = {"variants": [{"id": foreign.pk, "sku": foreign.sku, "mrp": "10.00", "price": "5.00"}]}
    assert admin_client.patch(_detail(product), body, format="json").status_code == 400
    foreign.refresh_from_db()
    assert foreign.price != 5


def test_publishing_needs_an_active_variant(admin_client):
    product, variant = create_product(published=False)
    ProductVariant.objects.filter(pk=variant.pk).update(is_active=False)
    res = admin_client.patch(_detail(product), {"is_published": True}, format="json")
    assert res.status_code == 400
    product.refresh_from_db()
    assert not product.is_published


def test_archive_and_restore_keep_orders_stock_and_reservations(admin_client):
    store = create_store()
    product, variant = create_product(stock=10, store=store)
    inventory = Inventory.objects.get(variant=variant)
    apply_movement(inventory, StockMovement.Type.RESERVATION, 3, reference_type="order", reference_id="OD1")
    movements = StockMovement.objects.count()

    assert admin_client.delete(_detail(product)).status_code == 204
    assert Product.all_objects.get(pk=product.pk).is_deleted
    assert admin_client.patch(_detail(product), {"name": "x"}, format="json").status_code == 409
    assert admin_client.get(f"{URL}?state=deleted").json()["count"] == 1

    res = admin_client.post(f"{_detail(product)}restore/")
    assert res.status_code == 200 and res.json()["is_published"] is False
    inventory.refresh_from_db()
    assert (inventory.available_quantity, inventory.reserved_quantity) == (7, 3)
    assert StockMovement.objects.count() == movements


def test_product_edit_never_touches_stock(admin_client):
    product, variant = create_product(stock=12, store=create_store())
    inventory = Inventory.objects.get(variant=variant)
    movements = StockMovement.objects.count()
    body = {"name": "New", "variants": [{"id": variant.pk, "sku": variant.sku, "mrp": "999.00", "price": "500.00"}]}
    assert admin_client.patch(_detail(product), body, format="json").status_code == 200
    inventory.refresh_from_db()
    assert (inventory.available_quantity, inventory.reserved_quantity) == (12, 0)
    assert StockMovement.objects.count() == movements


# --- stock adjustments --------------------------------------------------------------------------


@pytest.mark.parametrize("movement_type", ["purchase", "return", "adjustment"])
@pytest.mark.parametrize("reason", [None, "", "   "])
def test_every_manual_stock_change_needs_a_reason(admin_client, movement_type, reason):
    _, variant = create_product(stock=5, store=create_store())
    inventory = Inventory.objects.get(variant=variant)
    body = {"movement_type": movement_type, "quantity": 2}
    if reason is not None:
        body["reason"] = reason
    res = admin_client.post(f"/api/inventory/{inventory.pk}/adjust/", body, format="json")
    assert res.status_code == 400 and "reason" in str(res.json())
    inventory.refresh_from_db()
    assert inventory.available_quantity == 5


def test_stock_adjustment_keeps_reservations_and_history(admin_client, admin_user):
    _, variant = create_product(stock=10, store=create_store())
    inventory = Inventory.objects.get(variant=variant)
    apply_movement(inventory, StockMovement.Type.RESERVATION, 4, reference_type="order", reference_id="OD2")
    url = f"/api/inventory/{inventory.pk}/adjust/"

    res = admin_client.post(url, {"movement_type": "purchase", "quantity": 5, "reason": "Bill 7"}, format="json")
    assert res.status_code == 201, res.json()
    res = admin_client.post(url, {"movement_type": "adjustment", "quantity": -2, "reason": "Damaged"}, format="json")
    assert res.status_code == 201
    too_many = admin_client.post(url, {"movement_type": "adjustment", "quantity": -10, "reason": "x"}, format="json")
    assert too_many.status_code == 409  # only 9 available; reserved units can't be adjusted away

    # Neither reserved stock nor the history can be written or removed directly.
    admin_client.patch(f"/api/inventory/{inventory.pk}/", {"reserved_quantity": 0, "available_quantity": 500})
    assert admin_client.delete(f"/api/inventory/{inventory.pk}/").status_code in (403, 405)
    movement = inventory.movements.first()
    assert admin_client.delete(f"/api/inventory/movements/{movement.pk}/").status_code == 405
    inventory.refresh_from_db()
    assert (inventory.available_quantity, inventory.reserved_quantity) == (9, 4)
    kinds = list(inventory.movements.order_by("id").values_list("movement_type", "created_by"))
    assert kinds[-2:] == [("purchase", admin_user.pk), ("adjustment", admin_user.pk)]


def test_inventory_filters_by_product_within_the_managers_stores(admin_client, staff_client, staff_user):
    mine, other = create_store(), create_store()
    mine.managers.add(staff_user)
    product, variant = create_product(stock=3, store=mine)
    Inventory.objects.create(store=other, variant=variant)
    create_product(name="Unrelated", stock=9, store=mine)

    def skus(client):
        rows = client.get("/api/inventory/", {"product": product.pk}).json()["results"]
        return sorted((r["sku"], r["store"]) for r in rows)

    assert skus(admin_client) == sorted([(variant.sku, mine.pk), (variant.sku, other.pk)])
    assert skus(staff_client) == [(variant.sku, mine.pk)]  # managers still see only their stores
