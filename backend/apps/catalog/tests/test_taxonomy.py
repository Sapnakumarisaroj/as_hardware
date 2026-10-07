"""The owner's approved category tree (2026-10-07): exactly ten categories; everything else is
archived, never deleted, so orders, returns, payments and reviews keep working."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.carts.services import add_item
from apps.catalog.models import Category, Product
from apps.catalog.taxonomy import APPROVED_TAXONOMY, apply_taxonomy, approved_slugs
from apps.core.testing import create_address, create_product, create_store
from apps.offers.models import Offer
from apps.orders.models import OrderItem
from apps.orders.services import place_order
from apps.shopping.models import RecommendationRule

pytestmark = pytest.mark.django_db

APPROVED = [
    "Plywood, MDF & HDHMR",
    "Fevicol",
    "Hinges, Channels & Handles",
    "Kitchen Systems & Accessories",
    "Wardrobe & Bed Fittings",
    "Door Locks & Hardware",
    "Power Tools & Accessories",
    "General Hardware & Tools",
    "Safety Tools & Workwear",
    "Glass Door Hardware",
]


def test_the_tree_is_exactly_the_approved_ten():
    assert [name for _slug, name in APPROVED_TAXONOMY] == APPROVED
    apply_taxonomy()
    tops = list(
        Category.objects.filter(parent=None, is_active=True).order_by("sort_order").values_list("name", flat=True)
    )
    assert tops == APPROVED
    assert set(Category.objects.values_list("slug", flat=True)) == approved_slugs()


@pytest.fixture
def old_shop(user):
    """A catalogue from before the decision: Tools › Drills (kept, moved) and Plumbing › Taps (archived)."""
    tools = Category.objects.create(name="Tools", slug="tools")
    drills = Category.objects.create(name="Drills", slug="drills", parent=tools)
    plumbing = Category.objects.create(name="Plumbing", slug="plumbing")
    taps = Category.objects.create(name="Taps", slug="taps", parent=plumbing)
    store = create_store()
    drill, drill_v = create_product(name="Impact Drill", category=tools, subcategory=drills, stock=5, store=store)
    tap, tap_v = create_product(name="Pillar Tap", category=plumbing, subcategory=taps, stock=5, store=store)
    add_item(user, tap_v.id, 1)
    order, _ = place_order(user=user, address_id=create_address(user).id, payment_method="cod")
    offer = Offer.objects.create(
        name="Taps 5%", discount_type="percent", value=5, is_active=True, starts_at=timezone.now(), ends_at=None
    )
    offer.categories.set([taps])
    rule = RecommendationRule.objects.create(source_category=taps, target_category=drills, label="x", is_active=True)
    return {"drill": drill, "tap": tap, "order": order, "offer": offer, "rule": rule, "tap_variant": tap_v}


def test_products_of_moved_subcategories_follow_them_and_the_rest_is_archived(old_shop):
    report = apply_taxonomy()
    drill = Product.objects.get(pk=old_shop["drill"].pk)
    assert (drill.category.slug, drill.subcategory.slug) == ("power-tools", "drills") and drill.is_published

    assert not Product.objects.filter(pk=old_shop["tap"].pk).exists()  # hidden from every customer query
    tap = Product.all_objects.get(pk=old_shop["tap"].pk)
    assert tap.is_deleted and not tap.is_active and not tap.is_published
    assert {"tools", "plumbing", "taps"} <= set(report.archived_categories)
    assert not Category.objects.filter(slug__in=["tools", "plumbing", "taps"]).exists()
    assert Category.all_objects.filter(slug="taps", is_deleted=True, is_active=False).exists()

    # History is untouched: the order still has its line, product and price.
    item = OrderItem.objects.get(order=old_shop["order"])
    assert item.variant_id == old_shop["tap_variant"].pk and item.product_name == "Pillar Tap"
    # Rules that only targeted archived categories are switched off.
    old_shop["offer"].refresh_from_db()
    old_shop["rule"].refresh_from_db()
    assert not old_shop["offer"].is_active and not old_shop["rule"].is_active


def test_storefront_shows_only_the_approved_categories(old_shop, auth_client):
    apply_taxonomy()
    api = APIClient()
    names = [c["name"] for c in api.get("/api/categories/").json()]
    assert set(names) <= set(APPROVED) and "Plumbing" not in names
    products = api.get("/api/products/").json()["results"]
    assert [p["name"] for p in products] == ["Impact Drill"]
    assert api.get("/api/categories/taps/").status_code == 404
    order = auth_client.get(f"/api/orders/{old_shop['order'].order_number}/").json()
    assert order["items"][0]["product_name"] == "Pillar Tap"  # the customer's history still shows it


def test_dry_run_changes_nothing_and_apply_is_idempotent(old_shop):
    out = StringIO()
    call_command("apply_taxonomy", "--dry-run", stdout=out)
    assert "Dry run, nothing saved" in out.getvalue() and "Pillar Tap" not in out.getvalue()
    assert Category.objects.filter(slug="plumbing").exists() and not Category.objects.filter(slug="fevicol").exists()
    assert Product.objects.filter(pk=old_shop["tap"].pk).exists()

    first = apply_taxonomy()
    second = apply_taxonomy()
    assert first.archived_products and not second.archived_products and not second.archived_categories
    assert not second.created and not second.updated and not second.moved_products


def test_approved_categories_hidden_by_hand_are_restored(old_shop):
    apply_taxonomy()
    Category.all_objects.filter(slug="fevicol").update(is_active=False)  # an admin hid an approved one
    apply_taxonomy()
    assert Category.objects.get(slug="fevicol").is_active  # approved categories are always restored
