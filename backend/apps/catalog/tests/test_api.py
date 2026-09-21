import pytest

from apps.catalog.models import Product
from apps.core.testing import create_category, create_product

pytestmark = pytest.mark.django_db


def test_product_listing_is_public_and_hides_unpublished(api_client):
    create_product(name="Visible Drill", stock=5)
    create_product(name="Hidden Drill", published=False)
    res = api_client.get("/api/products/")
    assert res.status_code == 200
    names = [p["name"] for p in res.json()["results"]]
    assert names == ["Visible Drill"]
    item = res.json()["results"][0]
    assert item["price"] == "900.00" and item["mrp"] == "1000.00"
    assert item["discount_percent"] == "10.00"
    assert item["stock_status"] == "in_stock" or item["stock_status"] == "low_stock"


def test_listing_filters_category_price_stock(api_client):
    tools = create_category("Tools")
    drills = create_category("Drills", parent=tools)
    create_product(name="Cheap Drill", price="100.00", mrp="120.00", category=tools, subcategory=drills, stock=3)
    create_product(name="Pricey Drill", price="5000.00", mrp="5000.00", category=tools, subcategory=drills)
    create_product(name="Tap", category=create_category("Plumbing"), stock=3)

    by_cat = api_client.get("/api/products/", {"category": tools.slug}).json()["results"]
    assert {p["name"] for p in by_cat} == {"Cheap Drill", "Pricey Drill"}
    by_sub = api_client.get("/api/products/", {"category": drills.slug}).json()["results"]
    assert len(by_sub) == 2
    cheap = api_client.get("/api/products/", {"max_price": "500"}).json()["results"]
    assert [p["name"] for p in cheap] == ["Cheap Drill"]
    in_stock = api_client.get("/api/products/", {"in_stock": "true", "category": tools.slug}).json()["results"]
    assert [p["name"] for p in in_stock] == ["Cheap Drill"]
    ordered = api_client.get("/api/products/", {"ordering": "-price"}).json()["results"]
    assert ordered[0]["name"] == "Pricey Drill"


def test_product_detail_has_variants_specs_and_stock(api_client):
    product, variant = create_product(stock=12)
    product.specifications.create(name="Power", value="650", unit="W")
    res = api_client.get(f"/api/products/{product.slug}/")
    assert res.status_code == 200
    body = res.json()
    assert body["variants"][0]["sku"] == variant.sku
    assert body["variants"][0]["available_quantity"] == 12
    assert body["specifications"] == [{"name": "Power", "key": "power", "value": "650", "unit": "W", "sort_order": 0}]


def test_categories_tree(api_client):
    tools = create_category("Tools")
    create_category("Drills", parent=tools)
    res = api_client.get("/api/categories/")
    assert res.status_code == 200
    assert res.json()[0]["children"][0]["name"] == "Drills"


def test_customer_cannot_create_products(auth_client, api_client):
    payload = {
        "name": "X",
        "sku": "X",
        "category": create_category().id,
        "variants": [{"sku": "X1", "mrp": "10", "price": "9"}],
    }
    assert api_client.post("/api/products/", payload, format="json").status_code == 401
    assert auth_client.post("/api/products/", payload, format="json").status_code == 403


def test_admin_creates_product_with_variants_and_specs(admin_client):
    tools = create_category("Tools")
    drills = create_category("Drills", parent=tools)
    payload = {
        "name": "Impact Drill 650W",
        "sku": "IMP-650",
        "category": tools.id,
        "subcategory": drills.id,
        "gst_rate": "18.00",
        "is_published": True,
        "variants": [{"sku": "IMP-650-STD", "mrp": "4000.00", "price": "3500.00"}],
        "specifications": [
            {"name": "Power", "value": "650", "unit": "W"},
            {"name": "Chuck Size", "value": "13", "unit": "mm"},
        ],
    }
    res = admin_client.post("/api/products/", payload, format="json")
    assert res.status_code == 201, res.json()
    body = res.json()
    assert body["slug"] == "impact-drill-650w"
    assert body["variants"][0]["is_default"] is True
    assert [s["key"] for s in body["specifications"]] == ["power", "chuck-size"]

    bad = dict(payload, sku="IMP-2", variants=[{"sku": "IMP-2-A", "mrp": "100", "price": "200"}])
    assert admin_client.post("/api/products/", bad, format="json").status_code == 400
    dup = dict(payload, sku="IMP-3", name="Another", variants=[{"sku": "IMP-650-STD", "mrp": "10", "price": "9"}])
    assert admin_client.post("/api/products/", dup, format="json").status_code == 409


def test_admin_soft_deletes_product(admin_client):
    product, _ = create_product()
    assert admin_client.delete(f"/api/products/{product.slug}/").status_code == 204
    assert Product.all_objects.get(pk=product.pk).is_deleted
