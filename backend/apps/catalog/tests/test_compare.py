"""GET /api/products/compare/?slugs=… — side-by-side comparison of up to four products."""

from decimal import Decimal

import pytest

from apps.catalog.models import ProductSpecification, ProductVariant
from apps.core.testing import create_category, create_product

pytestmark = pytest.mark.django_db

URL = "/api/products/compare/"


def spec(product, name, value, unit="", order=0):
    return ProductSpecification.objects.create(
        product=product, name=name, key=name.lower().replace(" ", "-"), value=value, unit=unit, sort_order=order
    )


@pytest.fixture
def drills():
    tools = create_category("Tools")
    a, _ = create_product(name="Drill A", price="900.00", mrp="1000.00", category=tools)
    b, _ = create_product(name="Drill B", price="1200.00", mrp="1200.00", category=tools)
    spec(a, "Power", "500", "W", 0)
    spec(b, "Power", "500", "W", 0)
    spec(a, "Chuck size", "10 mm", "", 1)
    spec(b, "Chuck size", "13 mm", "", 1)
    spec(b, "Warranty", "2 years", "", 2)
    return a, b


def test_compare_merges_specifications_with_differs_flag(api_client, drills):
    a, b = drills
    data = api_client.get(URL, {"slugs": f"{a.slug},{b.slug}"}).json()
    assert [p["slug"] for p in data["products"]] == [a.slug, b.slug]
    rows = {row["key"]: row for row in data["specifications"]}
    assert rows["power"]["values"] == ["500 W", "500 W"]
    assert rows["power"]["differs"] is False
    assert rows["chuck-size"]["values"] == ["10 mm", "13 mm"]
    assert rows["chuck-size"]["differs"] is True
    assert rows["warranty"]["values"] == ["—", "2 years"]
    assert rows["warranty"]["differs"] is True
    assert [row["key"] for row in data["specifications"]] == ["power", "chuck-size", "warranty"]
    assert data["mixed_departments"] is False


def test_compare_uses_default_variant_price(api_client, drills):
    a, _ = drills
    ProductVariant.objects.create(product=a, sku="A-CHEAP", mrp=Decimal("600"), price=Decimal("500"))
    product = api_client.get(URL, {"slugs": a.slug}).json()["products"][0]
    assert product["price"] == "900.00"
    assert product["mrp"] == "1000.00"
    assert product["discount_percent"] == "10.00"
    assert product["unit"] == "piece"
    assert product["brand"]["name"] == "Test Brand"


def test_compare_falls_back_to_cheapest_active_variant(api_client, drills):
    a, _ = drills
    a.variants.update(is_active=False)
    ProductVariant.objects.create(product=a, sku="A-2", mrp=Decimal("800"), price=Decimal("700"))
    ProductVariant.objects.create(product=a, sku="A-3", mrp=Decimal("800"), price=Decimal("650"))
    product = api_client.get(URL, {"slugs": a.slug}).json()["products"][0]
    assert product["price"] == "650.00"


def test_unpublished_and_inactive_products_are_excluded(api_client, drills):
    a, _ = drills
    hidden, _ = create_product(name="Hidden", published=False)
    inactive, _ = create_product(name="Inactive", is_active=False)
    data = api_client.get(URL, {"slugs": f"{a.slug},{hidden.slug},{inactive.slug},nope"}).json()
    assert [p["slug"] for p in data["products"]] == [a.slug]
    assert data["missing"] == [hidden.slug, inactive.slug, "nope"]


def test_compare_allows_at_most_four(api_client):
    slugs = [create_product(name=f"P{i}")[0].slug for i in range(5)]
    assert api_client.get(URL, {"slugs": ",".join(slugs[:4])}).status_code == 200
    response = api_client.get(URL, {"slugs": ",".join(slugs)})
    assert response.status_code == 400


def test_compare_requires_slugs(api_client):
    assert api_client.get(URL).status_code == 400


def test_compare_exposes_no_internal_fields(api_client, drills):
    a, _ = drills
    a.variants.update(cost_price=Decimal("400"))
    response = api_client.get(URL, {"slugs": a.slug})
    body = response.content.decode()
    product = response.json()["products"][0]
    for field in ("cost_price", "is_demo", "sku", "hsn_code", "gst_rate", "is_published"):
        assert field not in product
        assert f'"{field}"' not in body
    assert "400.00" not in body


def test_mixed_departments_flagged(api_client):
    tools = create_category("Tools")
    paint = create_category("Paint")
    a, _ = create_product(name="Drill", category=tools)
    b, _ = create_product(name="Primer", category=create_category("Primers", parent=paint))
    data = api_client.get(URL, {"slugs": f"{a.slug},{b.slug}"}).json()
    assert data["mixed_departments"] is True
    assert data["products"][1]["department"]["slug"] == paint.slug


def test_unrated_products_have_null_rating(api_client, drills):
    a, b = drills
    b.rating_avg, b.rating_count = Decimal("4.20"), 5
    b.save()
    products = api_client.get(URL, {"slugs": f"{a.slug},{b.slug}"}).json()["products"]
    assert products[0]["rating_avg"] is None
    assert products[1]["rating_avg"] == "4.20"
    assert products[1]["rating_count"] == 5
