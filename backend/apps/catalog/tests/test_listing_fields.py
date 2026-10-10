import pytest

from apps.catalog.models import Product, ProductVariant
from apps.core.testing import create_product

pytestmark = pytest.mark.django_db


def _row(api_client, slug):
    res = api_client.get("/api/products/", {"search": "", "page_size": 50})
    assert res.status_code == 200
    return next(p for p in res.json()["results"] if p["slug"] == slug)


def test_listing_names_the_variant_whose_price_is_shown(api_client):
    product, variant = create_product(name="Marine Plywood", price="2400.00", mrp="2600.00")
    variant.name = "18 mm"
    variant.save()
    ProductVariant.objects.create(product=product, sku=f"{product.sku}-12", name="12 mm", mrp="1900.00", price="1700.00")

    row = _row(api_client, product.slug)
    assert row["price"] == "1700.00"  # the cheapest variant's price…
    assert row["variant_label"] == "12 mm"  # …and its name


def test_listing_flags_demo_products(api_client):
    real, _ = create_product(name="Real Hinge")
    demo, _ = create_product(name="Sample Hinge")
    Product.objects.filter(pk=demo.pk).update(is_demo=True)

    assert _row(api_client, real.slug)["is_demo"] is False
    assert _row(api_client, demo.slug)["is_demo"] is True
    assert _row(api_client, real.slug)["variant_label"] == ""
