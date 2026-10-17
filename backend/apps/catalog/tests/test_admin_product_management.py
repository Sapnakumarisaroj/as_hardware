"""Django admin as the product-management panel: who may use it, product/variant edits with price
and HSN validation, stock that catalogue edits never touch, and archiving instead of deleting."""

from decimal import Decimal
from html.parser import HTMLParser

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from apps.catalog.models import OptionType, Product, ProductVariant, VariantOption
from apps.core.models import AuditLog
from apps.core.testing import create_category, create_product, create_store
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import apply_movement

pytestmark = pytest.mark.django_db


# --- helpers ----------------------------------------------------------------------------------------


class _FormFields(HTMLParser):
    """Collects the submit values of every field on an admin change page, like a browser would."""

    def __init__(self):
        super().__init__()
        self.data: dict[str, list[str]] = {}
        self._select = self._textarea = None

    def _add(self, name, value):
        if name and "__prefix__" not in name:
            self.data.setdefault(name, []).append(value)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input":
            kind = a.get("type", "text")
            if kind in ("submit", "button", "file", "image", "reset"):
                return
            if kind in ("checkbox", "radio") and "checked" not in a:
                return
            self._add(a.get("name"), a.get("value", "on" if kind == "checkbox" else ""))
        elif tag == "select":
            self._select, self._selected = a.get("name"), False
        elif tag == "option" and self._select and "selected" in a:
            self._add(self._select, a.get("value", ""))
            self._selected = True
        elif tag == "textarea":
            self._textarea, self._text = a.get("name"), ""

    def handle_data(self, data):
        if self._textarea:
            self._text += data

    def handle_endtag(self, tag):
        if tag == "select":
            if self._select and not self._selected:
                self._add(self._select, "")
            self._select = None
        elif tag == "textarea" and self._textarea:
            self._add(self._textarea, self._text.lstrip("\n"))
            self._textarea = None


def form_data(client, url) -> dict:
    res = client.get(url)
    assert res.status_code == 200, url
    parser = _FormFields()
    parser.feed(res.content.decode())
    return {k: v if len(v) > 1 else v[0] for k, v in parser.data.items()}


def _login(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _grant_catalog_perms(user):
    user.user_permissions.add(
        *Permission.objects.filter(content_type__app_label__in=["catalog", "inventory"]),
    )


@pytest.fixture
def superuser():
    return get_user_model().objects.create_superuser(email="root@example.com", password="Passw0rd!x")


@pytest.fixture
def root(superuser):
    return _login(superuser)


@pytest.fixture
def product_with_order(user):
    """A product sold on an order, with stock at a store and units reserved for that order."""
    from apps.orders.models import Order, OrderItem

    store = create_store()
    product, variant = create_product(name="Hinge", price="90.00", mrp="100.00", stock=20, store=store)
    order = Order.objects.create(
        order_number="ODADMIN1", user=user, address_snapshot={}, payment_method="cod", subtotal=90,
        mrp_total=100, discount_total=10, delivery_fee=0, tax_total=0, grand_total=90,
    )  # fmt: skip
    item = OrderItem.objects.create(
        order=order, variant=variant, product=product, product_name=product.name, sku=variant.sku,
        unit_mrp=variant.mrp, unit_price=variant.price, gst_rate=product.gst_rate, quantity=2, line_total=180,
    )  # fmt: skip
    inventory = Inventory.objects.get(store=store, variant=variant)
    apply_movement(inventory, StockMovement.Type.RESERVATION, 2, reference_type="order", reference_id=order.pk)
    return product, variant, item, inventory


def _change_url(product):
    return reverse("admin:catalog_product_change", args=[product.pk])


def _changelist():
    return reverse("admin:catalog_product_changelist")


# --- permissions ------------------------------------------------------------------------------------


def test_admin_role_with_permissions_can_manage_products():
    admin = get_user_model().objects.create_user("owner@example.com", "S3cure-pass!", role="admin", is_staff=True)
    _grant_catalog_perms(admin)
    product, _ = create_product()
    client = _login(admin)
    for url in (_changelist(), reverse("admin:catalog_product_add"), _change_url(product)):
        assert client.get(url).status_code == 200, url


@pytest.mark.parametrize("role", ["store_manager", "customer", "delivery_partner"])
def test_non_admin_roles_are_refused_even_with_staff_flag_and_permissions(role):
    """Model permissions given by mistake don't open the catalogue: the role is checked on the server."""
    user = get_user_model().objects.create_user(f"{role}@example.com", "S3cure-pass!", role=role, is_staff=True)
    _grant_catalog_perms(user)
    product, variant = create_product(name="Locked Bolt", price="50.00", mrp="60.00", stock=5)
    inventory = Inventory.objects.get(variant=variant)
    client = _login(user)

    for url in (
        _changelist(),
        reverse("admin:catalog_product_add"),
        _change_url(product),
        reverse("admin:catalog_productvariant_change", args=[variant.pk]),
        reverse("admin:inventory_inventory_change", args=[inventory.pk]),
        reverse("admin:inventory_stockmovement_changelist"),
    ):
        assert client.get(url).status_code == 403, url

    # Direct POSTs (form submit and bulk action) are refused too, and nothing changes.
    res = client.post(_change_url(product), {"name": "Hacked", "sku": product.sku})
    assert res.status_code == 403
    res = client.post(_changelist(), {"action": "archive", "_selected_action": [product.pk]})
    assert res.status_code == 403
    res = client.post(
        reverse("admin:inventory_inventory_change", args=[inventory.pk]),
        {"low_stock_threshold": 1, "is_active": "on", "movement_type": "adjustment", "movement_quantity": 500,
         "movement_reason": "x"},
    )  # fmt: skip
    assert res.status_code == 403
    product.refresh_from_db()
    inventory.refresh_from_db()
    assert product.name == "Locked Bolt" and not product.is_deleted
    assert inventory.available_quantity == 5


def test_staff_without_model_permissions_cannot_change_products():
    admin = get_user_model().objects.create_user("viewer@example.com", "S3cure-pass!", role="admin", is_staff=True)
    product, _ = create_product()
    client = _login(admin)
    assert client.get(_change_url(product)).status_code == 403
    assert client.post(_changelist(), {"action": "unpublish", "_selected_action": [product.pk]}).status_code == 403


def test_logged_out_visitor_is_sent_to_login(client):
    product, _ = create_product()
    res = client.post(_change_url(product), {"name": "x"})
    assert res.status_code == 302 and reverse("admin:login") in res["Location"]


# --- product CRUD and validation --------------------------------------------------------------------


def _new_product_data(category, **overrides):
    data = {
        "name": "Door Closer",
        "slug": "door-closer",
        "sku": "dc-100",
        "category": category.pk,
        "unit": "piece",
        "short_description": "Hydraulic closer",
        "description": "For doors up to 60 kg.",
        "tags": "[]",
        "faqs": "[]",
        "gst_rate": "18.00",
        "hsn_code": "83026000",
        "max_order_quantity": 10,
        "is_returnable": "on",
        "is_active": "on",
        "is_published": "on",
        "variants-TOTAL_FORMS": 1,
        "variants-INITIAL_FORMS": 0,
        "variants-0-sku": "dc-100-s",
        "variants-0-name": "Silver",
        "variants-0-attributes": "{}",
        "variants-0-mrp": "1500.00",
        "variants-0-price": "1200.00",
        "variants-0-is_default": "on",
        "variants-0-is_active": "on",
        "variants-0-price_approved": "on",
        "variants-0-sort_order": 0,
    }
    for prefix in ("specifications", "images", "relations"):
        data.update({f"{prefix}-TOTAL_FORMS": 0, f"{prefix}-INITIAL_FORMS": 0})
    data.update(overrides)
    return data


def test_admin_creates_product_with_variant_and_audit_entry(root, superuser):
    category = create_category("Door Hardware")
    res = root.post(reverse("admin:catalog_product_add"), _new_product_data(category))
    assert res.status_code == 302, res.context["adminform"].form.errors if res.context else res

    product = Product.objects.get(sku="DC-100")  # stored upper-case
    variant = product.variants.get()
    assert (variant.sku, variant.mrp, variant.price) == ("DC-100-S", Decimal("1500.00"), Decimal("1200.00"))
    assert product.is_published and product.hsn_code == "83026000"
    assert Inventory.objects.filter(variant=variant).count() == 0  # adding a product never invents stock
    assert AuditLog.objects.filter(action="catalog.product.created", target_id=str(product.pk), actor=superuser)
    assert AuditLog.objects.filter(action="catalog.variant.created", target_id=str(variant.pk)).exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("variants-0-price", "1600.00", "Selling price cannot exceed MRP"),
        ("variants-0-price", "0", "greater than or equal to 0.01"),
        ("variants-0-mrp", "-5", "greater than or equal to 0.01"),
        ("hsn_code", "83AB", "HSN codes are 4, 6 or 8 digits"),
        ("gst_rate", "55", "less than or equal to 40"),
    ],
)
def test_invalid_prices_and_tax_are_refused(root, field, value, message):
    category = create_category("Door Hardware")
    res = root.post(reverse("admin:catalog_product_add"), _new_product_data(category, **{field: value}))
    assert res.status_code == 200 and message in res.content.decode()
    assert not Product.all_objects.filter(sku="DC-100").exists()


def test_published_product_needs_an_active_variant(root):
    category = create_category("Door Hardware")
    data = _new_product_data(category)
    del data["variants-0-is_active"]
    res = root.post(reverse("admin:catalog_product_add"), data)
    assert "needs at least one active variant" in res.content.decode()
    assert not Product.all_objects.filter(sku="DC-100").exists()


def test_edit_name_price_gst_hsn_and_brand_with_change_history(root, superuser):
    product, variant = create_product(name="Tower Bolt", price="90.00", mrp="100.00")
    url = _change_url(product)
    data = form_data(root, url)
    data.update(
        {"name": "Tower Bolt 6 inch", "gst_rate": "12.00", "hsn_code": "8302", "variants-0-price": "85.00",
         "variants-0-mrp": "110.00", "description": "Stainless steel."},
    )  # fmt: skip
    res = root.post(url, data)
    assert res.status_code == 302, res.content.decode()[:2000]

    product.refresh_from_db()
    variant.refresh_from_db()
    assert product.name == "Tower Bolt 6 inch" and product.gst_rate == Decimal("12.00") and product.hsn_code == "8302"
    assert (variant.price, variant.mrp) == (Decimal("85.00"), Decimal("110.00"))

    product_log = AuditLog.objects.get(action="catalog.product.updated", target_id=str(product.pk))
    assert product_log.actor == superuser
    assert product_log.changes["name"] == ["Tower Bolt", "Tower Bolt 6 inch"]
    variant_log = AuditLog.objects.get(action="catalog.variant.updated", target_id=str(variant.pk))
    assert variant_log.changes["price"] == ["90.00", "85.00"] and variant_log.changes["mrp"] == ["100.00", "110.00"]
    # Django's own per-object history is kept as well.
    assert root.get(reverse("admin:catalog_product_history", args=[product.pk])).status_code == 200


def test_price_edit_cannot_undercut_existing_bulk_tier(root):
    from apps.catalog.models import VariantPriceTier

    product, variant = create_product(price="100.00", mrp="120.00")
    VariantPriceTier.objects.create(variant=variant, min_quantity=10, unit_price=Decimal("90.00"))
    url = _change_url(product)
    data = form_data(root, url)
    data["variants-0-price"] = "85.00"  # the 10+ tier at ₹90 would now be dearer than the normal price
    res = root.post(url, data)
    assert res.status_code == 200 and "must be lower than" in res.content.decode()
    variant.refresh_from_db()
    assert variant.price == Decimal("100.00")


def test_edit_variant_options_in_admin(root):
    category = create_category("Cement")
    grade = OptionType.objects.create(name="Grade")
    grade.categories.add(category)
    value = grade.values.create(value="53 Grade", slug="53-grade")
    product, variant = create_product(category=category)
    url = reverse("admin:catalog_productvariant_change", args=[variant.pk])
    data = form_data(root, url)
    data.update(
        {"option_values-TOTAL_FORMS": 1, "option_values-0-option_type": grade.pk, "option_values-0-value": value.pk}
    )
    res = root.post(url, data)
    assert res.status_code == 302, res.content.decode()[:2000]
    assert VariantOption.objects.get(variant=variant).value == value
    variant.refresh_from_db()
    assert variant.attributes == {"Grade": "53 Grade"}

    # A second active variant can't take the same combination.
    other = ProductVariant.objects.create(product=product, sku="V-OTHER", mrp=100, price=90)
    url = reverse("admin:catalog_productvariant_change", args=[other.pk])
    data = form_data(root, url)
    data.update(
        {"option_values-TOTAL_FORMS": 1, "option_values-0-option_type": grade.pk, "option_values-0-value": value.pk}
    )
    res = root.post(url, data)
    assert res.status_code == 200 and "already has these options" in res.content.decode()


def test_admin_list_search_filters_and_pagination(root):
    for n in range(55):
        create_product(name=f"Screw {n}", hsn_code="7318")
    create_product(name="Paint Roller", hsn_code="9603")
    res = root.get(_changelist())
    assert res.status_code == 200 and res.context["cl"].result_count == 56
    assert len(res.context["cl"].result_list) == 50  # paginated
    res = root.get(_changelist(), {"q": "9603"})
    assert [p.name for p in res.context["cl"].result_list] == ["Paint Roller"]
    res = root.get(_changelist(), {"is_published__exact": "0"})
    assert res.context["cl"].result_count == 0


# --- stock safety -----------------------------------------------------------------------------------


def test_catalogue_edit_never_changes_stock_or_reservations(root, product_with_order):
    product, variant, _item, inventory = product_with_order
    movements = StockMovement.objects.count()
    url = _change_url(product)
    data = form_data(root, url)
    data.update({"name": "Hinge 4 inch", "variants-0-price": "80.00", "variants-0-sku": "HINGE-4"})
    assert root.post(url, data).status_code == 302

    inventory.refresh_from_db()
    assert (inventory.available_quantity, inventory.reserved_quantity) == (18, 2)
    assert StockMovement.objects.count() == movements


def test_inventory_admin_books_stock_only_as_movements(root, superuser, product_with_order):
    _product, variant, _item, inventory = product_with_order
    url = reverse("admin:inventory_inventory_change", args=[inventory.pk])
    other_store = create_store()

    # Saving settings only (and trying to re-point the row) leaves quantities and the store alone.
    data = form_data(root, url)
    data.update({"low_stock_threshold": 3, "store": other_store.pk, "available_quantity": 500})
    assert root.post(url, data).status_code == 302
    inventory.refresh_from_db()
    assert inventory.low_stock_threshold == 3 and inventory.store_id != other_store.pk
    assert (inventory.available_quantity, inventory.reserved_quantity) == (18, 2)

    # A purchase adds to what is there, keeping the order's reservation.
    data = form_data(root, url)
    data.update({"movement_type": "purchase", "movement_quantity": 7, "movement_reason": "Supplier bill 42"})
    assert root.post(url, data).status_code == 302
    inventory.refresh_from_db()
    assert (inventory.available_quantity, inventory.reserved_quantity) == (25, 2)
    movement = inventory.movements.first()
    assert (movement.movement_type, movement.quantity, movement.created_by) == ("purchase", 7, superuser)


@pytest.mark.parametrize(
    ("movement", "message"),
    [
        ({"movement_type": "adjustment", "movement_quantity": -5, "movement_reason": ""}, "Give a reason"),
        (
            {"movement_type": "adjustment", "movement_quantity": -19, "movement_reason": "Count"},
            "can&#x27;t go below 0",
        ),
        ({"movement_type": "purchase", "movement_quantity": -3, "movement_reason": ""}, "Use a positive number"),
        ({"movement_type": "purchase", "movement_quantity": 0, "movement_reason": ""}, "not zero"),
        ({"movement_type": "", "movement_quantity": 4, "movement_reason": ""}, "Choose what kind"),
    ],
)
def test_invalid_stock_movements_are_refused_before_saving(root, product_with_order, movement, message):
    _product, _variant, _item, inventory = product_with_order
    url = reverse("admin:inventory_inventory_change", args=[inventory.pk])
    data = form_data(root, url)
    data.update({"low_stock_threshold": 9, **movement})
    res = root.post(url, data)
    assert res.status_code == 200 and message in res.content.decode()
    inventory.refresh_from_db()
    assert (inventory.available_quantity, inventory.reserved_quantity, inventory.low_stock_threshold) == (18, 2, 5)


def test_stock_rows_cannot_be_deleted(root, product_with_order):
    *_, inventory = product_with_order
    assert root.get(reverse("admin:inventory_inventory_delete", args=[inventory.pk])).status_code == 403
    assert Inventory.objects.filter(pk=inventory.pk).exists()


def test_variant_page_shows_stock_per_store_read_only(root, product_with_order):
    _product, variant, _item, _inventory = product_with_order
    body = root.get(reverse("admin:catalog_productvariant_change", args=[variant.pk])).content.decode()
    assert "stock per store" in body.lower() and "inventory-TOTAL_FORMS" in body


# --- archive instead of delete ----------------------------------------------------------------------


def test_products_cannot_be_deleted_from_admin(root, product_with_order):
    product, *_ = product_with_order
    assert root.get(reverse("admin:catalog_product_delete", args=[product.pk])).status_code == 403
    res = root.post(_changelist(), {"action": "delete_selected", "_selected_action": [product.pk]})
    assert Product.all_objects.filter(pk=product.pk, is_deleted=False).exists()
    assert res.status_code in (200, 302)


def test_archive_keeps_orders_stock_and_reservations_then_restore(root, superuser, product_with_order):
    product, variant, item, inventory = product_with_order
    res = root.post(_changelist(), {"action": "archive", "_selected_action": [product.pk]})
    assert res.status_code == 302

    archived = Product.all_objects.get(pk=product.pk)
    assert archived.is_deleted and not archived.is_published and not archived.is_purchasable
    item.refresh_from_db()
    inventory.refresh_from_db()
    assert item.product_id == product.pk and item.variant_id == variant.pk
    assert (inventory.available_quantity, inventory.reserved_quantity) == (18, 2)
    assert AuditLog.objects.filter(action="catalog.product.archived", target_id=str(product.pk), actor=superuser)

    # Hidden from the default list and from customers, but listed under the archive filter.
    assert product.pk not in [p.pk for p in root.get(_changelist()).context["cl"].result_list]
    archived_list = root.get(_changelist(), {"archived": "yes"}).context["cl"].result_list
    assert [p.pk for p in archived_list] == [product.pk]
    assert not Product.objects.filter(pk=product.pk).exists()
    assert root.get(_change_url(product)).status_code == 200  # still editable

    # Can't be published while archived.
    root.post(_changelist() + "?archived=yes", {"action": "publish", "_selected_action": [product.pk]})
    assert not Product.all_objects.get(pk=product.pk).is_published

    res = root.post(_changelist() + "?archived=yes", {"action": "restore", "_selected_action": [product.pk]})
    assert res.status_code == 302
    restored = Product.objects.get(pk=product.pk)
    assert not restored.is_deleted and not restored.is_published  # back as a draft
    assert AuditLog.objects.filter(action="catalog.product.restored", target_id=str(product.pk)).exists()


def test_archived_product_change_form_refuses_publishing(root, product_with_order):
    product, *_ = product_with_order
    product.delete()  # soft delete = archived
    url = _change_url(product)
    data = form_data(root, url)
    data["is_published"] = "on"
    res = root.post(url, data)
    assert res.status_code == 200 and "Restore it before publishing" in res.content.decode()


def test_archived_product_keeps_its_sku(root):
    product, _ = create_product()
    product.delete()
    data = _new_product_data(create_category("Door Hardware"), sku=product.sku.lower(), slug=product.slug)
    res = root.post(reverse("admin:catalog_product_add"), data)
    assert res.status_code == 200 and "belongs to an archived product" in res.content.decode()


def test_publish_and_unpublish_actions(root, superuser):
    ready, _ = create_product(name="Ready", published=False)
    no_variant, variant = create_product(name="No Variant", published=False)
    variant.is_active = False
    variant.save()
    res = root.post(_changelist(), {"action": "publish", "_selected_action": [ready.pk, no_variant.pk]}, follow=True)
    assert "1 product(s) published" in res.content.decode() and "no active variant" in res.content.decode()
    ready.refresh_from_db()
    no_variant.refresh_from_db()
    assert ready.is_published and not no_variant.is_published

    root.post(_changelist(), {"action": "unpublish", "_selected_action": [ready.pk]})
    ready.refresh_from_db()
    assert not ready.is_published
    actions = set(AuditLog.objects.filter(target_id=str(ready.pk)).values_list("action", flat=True))
    assert {"catalog.product.published", "catalog.product.unpublished"} <= actions


def test_list_page_publish_tick_needs_an_active_variant(root):
    product, variant = create_product(name="Quick Tick", published=False)
    variant.is_active = False
    variant.save()
    res = root.post(
        _changelist(),
        {"form-TOTAL_FORMS": 1, "form-INITIAL_FORMS": 1, "form-0-id": product.pk, "form-0-is_published": "on",
         "_save": "Save"},
    )  # fmt: skip
    assert res.status_code == 200
    product.refresh_from_db()
    assert not product.is_published


def test_variants_on_orders_cannot_be_deleted(root, product_with_order):
    """Order lines only hold a nullable link to the variant, so deleting it would silently cut old
    sales off their product. A variant with stock is protected by the stock row as well."""
    product, variant, item, _inventory = product_with_order
    sold = ProductVariant.objects.create(product=product, sku="HINGE-SOLD", mrp=100, price=95)  # no stock row
    item.variant = sold
    item.save(update_fields=["variant"])
    url = _change_url(product)
    data = form_data(root, url)
    key = next(k for k, v in data.items() if k.startswith("variants-") and k.endswith("-id") and v == str(sold.pk))
    data[key.replace("-id", "-DELETE")] = "on"
    res = root.post(url, data)
    assert res.status_code == 200
    assert "HINGE-SOLD can&#x27;t be deleted because it appears on customer orders" in res.content.decode()
    item.refresh_from_db()
    assert item.variant_id == sold.pk

    for blocked in (sold, variant):  # on an order / has stock
        assert root.get(reverse("admin:catalog_productvariant_delete", args=[blocked.pk])).status_code == 403
    # No bulk "delete selected" either (it would skip the per-variant check).
    assert root.get(reverse("admin:catalog_productvariant_changelist")).context["action_form"] is None


def test_unused_variant_can_still_be_removed(root):
    product, _ = create_product()
    spare = ProductVariant.objects.create(product=product, sku="SPARE-1", mrp=100, price=90)
    url = _change_url(product)
    data = form_data(root, url)
    key = next(k for k, v in data.items() if k.startswith("variants-") and k.endswith("-id") and v == str(spare.pk))
    data[key.replace("-id", "-DELETE")] = "on"
    assert root.post(url, data).status_code == 302
    assert not ProductVariant.objects.filter(pk=spare.pk).exists()
