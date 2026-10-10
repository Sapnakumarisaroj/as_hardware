"""purge_demo_data: removes demo rows, archives the ones history points at, never touches real rows."""

import io

import pytest
from django.core.management import call_command

from apps.catalog.models import Brand, Product, ProductVariant
from apps.core.testing import create_product, create_store
from apps.inventory.models import Inventory
from apps.orders.tests.helpers import order_with
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def mark_demo(*objects):
    for obj in objects:
        type(obj).all_objects.filter(pk=obj.pk).update(is_demo=True)


def purge(commit=True) -> str:
    out = io.StringIO()
    call_command("purge_demo_data", *(["--commit"] if commit else []), stdout=out)
    return out.getvalue()


@pytest.fixture
def shop(user):
    store = create_store()
    demo_brand = Brand.objects.create(name="Acme (Demo)", slug="acme-demo")
    shared_brand = Brand.objects.create(name="Shared (Demo)", slug="shared-demo")
    real, real_v = create_product(name="Real Drill", stock=5, store=store)
    real_shared, _ = create_product(name="Real Hammer", brand=shared_brand)
    unused, unused_v = create_product(name="Unused Demo", stock=3, store=store, brand=demo_brand)
    ordered, ordered_v = create_product(name="Ordered Demo", stock=3, store=store, brand=demo_brand)
    demo_store = create_store()
    empty_demo_store = create_store(zone=False)
    order, _ = order_with(user, (ordered_v, 1))
    mark_demo(demo_brand, shared_brand, unused, ordered, demo_store, empty_demo_store)
    return {
        "store": store, "real": real, "real_v": real_v, "real_shared": real_shared, "unused": unused,
        "unused_v": unused_v, "ordered": ordered, "ordered_v": ordered_v, "order": order, "demo_brand": demo_brand,
        "shared_brand": shared_brand, "demo_store": demo_store, "empty_demo_store": empty_demo_store,
    }  # fmt: skip


def test_dry_run_changes_nothing(shop):
    output = purge(commit=False)
    assert "Dry run" in output and "Unused Demo" in output
    assert Product.all_objects.filter(pk=shop["unused"].pk, is_deleted=False).exists()
    assert Store.objects.filter(pk=shop["empty_demo_store"].pk).exists()


def test_purge_deletes_unused_demo_rows_and_archives_ordered_ones(shop, auth_client):
    purge()
    assert not Product.all_objects.filter(pk=shop["unused"].pk).exists()
    assert not ProductVariant.objects.filter(pk=shop["unused_v"].pk).exists()
    assert not Inventory.objects.filter(variant_id=shop["unused_v"].pk).exists()

    ordered = Product.all_objects.get(pk=shop["ordered"].pk)
    assert ordered.is_deleted and not ordered.is_active and not ordered.is_published
    assert not ProductVariant.objects.get(pk=shop["ordered_v"].pk).is_active
    detail = auth_client.get(f"/api/orders/{shop['order'].order_number}/")
    assert detail.status_code == 200
    assert detail.json()["items"][0]["sku"] == shop["ordered_v"].sku

    assert not Store.all_objects.filter(pk=shop["empty_demo_store"].pk).exists()
    assert not Store.all_objects.filter(pk=shop["demo_store"].pk).exists()  # no orders, no stock
    brand = Brand.all_objects.get(pk=shop["demo_brand"].pk)  # still on the archived ordered product
    assert brand.is_deleted and not brand.is_active
    assert Brand.objects.filter(pk=shop["shared_brand"].pk).exists()  # a real product uses it


def test_real_rows_are_never_touched(shop):
    purge()
    real = Product.objects.get(pk=shop["real"].pk)
    assert real.is_active and real.is_published and not real.is_deleted
    assert Inventory.objects.get(variant=shop["real_v"]).available_quantity == 5
    assert Store.objects.filter(pk=shop["store"].pk, is_active=True).exists()
    assert Product.objects.filter(pk=shop["real_shared"].pk).exists()


def test_a_demo_store_with_orders_or_real_stock_is_archived(shop):
    mark_demo(shop["store"])  # the store the order shipped from and that holds real stock
    purge()
    store = Store.all_objects.get(pk=shop["store"].pk)
    assert store.is_deleted and not store.is_active and not store.accepts_orders
    assert Inventory.objects.get(variant=shop["real_v"]).available_quantity == 5


def test_running_twice_is_safe(shop):
    purge()
    again = purge()
    assert "0 deleted, 0 archived" in again and "Shared (Demo)" in again


def test_purges_the_real_demo_seed(settings):
    settings.DEBUG = True
    call_command("seed_demo_data", stdout=io.StringIO())
    real, _ = create_product(name="Real Saw")
    assert Product.objects.filter(is_demo=True).exists()
    purge()
    assert not Product.objects.filter(is_demo=True).exists()
    assert not Store.objects.filter(is_demo=True).exists()
    assert not Brand.objects.filter(is_demo=True).exists()
    assert Product.objects.filter(pk=real.pk, is_published=True).exists()
