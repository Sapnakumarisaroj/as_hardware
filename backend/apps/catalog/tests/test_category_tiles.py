import pytest

from apps.catalog.models import Category, ProductImage
from apps.core.testing import create_product

pytestmark = pytest.mark.django_db


def _tree(api_client):
    res = api_client.get("/api/categories/")
    assert res.status_code == 200
    return {c["slug"]: c for c in res.json()}


def test_short_name_uses_compact_label_for_approved_departments(api_client):
    Category.objects.create(name="Plywood, MDF & HDHMR", slug="plywood-mdf-hdhmr")
    Category.objects.create(name="Paints", slug="paints")
    tree = _tree(api_client)
    assert tree["plywood-mdf-hdhmr"]["short_name"] == "Plywood & Boards"
    assert tree["paints"]["short_name"] == "Paints"


def test_cover_image_falls_back_to_a_published_product_photo(api_client):
    tools = Category.objects.create(name="Tools", slug="tools")
    drills = Category.objects.create(name="Drills", slug="drills", parent=tools)
    empty = Category.objects.create(name="Empty", slug="empty")
    product, _ = create_product(name="Impact Drill", category=tools, subcategory=drills)
    ProductImage.objects.create(product=product, image="products/drill.jpg", is_primary=True)
    hidden, _ = create_product(name="Hidden Saw", category=empty, published=False)
    ProductImage.objects.create(product=hidden, image="products/saw.jpg", is_primary=True)

    tree = _tree(api_client)
    assert tree["tools"]["cover_image"].endswith("/products/drill.jpg")
    assert tree["tools"]["children"][0]["cover_image"].endswith("/products/drill.jpg")
    assert tree["empty"]["cover_image"] is None
