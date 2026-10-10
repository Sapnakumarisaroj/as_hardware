"""Dashboard catalogue import/export endpoints, demo flag and purchase cost in the admin API."""

import json
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.catalog import importer
from apps.catalog.importer import read_table
from apps.catalog.models import Product, ProductVariant
from apps.catalog.taxonomy import apply_taxonomy
from apps.core.testing import create_product, create_store

pytestmark = pytest.mark.django_db

IMPORT_URL = "/api/admin/catalog/import/"
CSV = (
    b"product_sku,product_name,category,gst_rate,variant_sku,mrp,price,cost_price,stock\n"
    b"GL-1,Nitrile Gloves,safety,18,GL-1-M,250,199,120,BLR-01:30\n"
)


@pytest.fixture(autouse=True)
def setup():
    apply_taxonomy()
    create_store(code="BLR-01")


def upload(client, content=CSV, name="catalogue.csv", **fields):
    return client.post(IMPORT_URL, {"file": SimpleUploadedFile(name, content), **fields}, format="multipart")


def test_dry_run_then_commit(admin_client):
    dry = upload(admin_client)
    assert dry.status_code == 200, dry.content
    body = dry.json()
    assert body["ok"] and body["dry_run"] and not body["committed"]
    assert body["rows"] == [{"row": 2, "product_sku": "GL-1", "variant_sku": "GL-1-M", "action": "create"}]
    assert not Product.all_objects.filter(sku="GL-1").exists()

    done = upload(admin_client, dry_run="false").json()
    assert done["committed"] and done["counts"]["products_created"] == 1
    assert ProductVariant.objects.get(sku="GL-1-M").cost_price == Decimal("120")


def test_row_errors_are_returned_and_nothing_saved(admin_client):
    bad = CSV.replace(b",199,", b",299,")
    body = upload(admin_client, bad, dry_run="false").json()
    assert not body["ok"] and not body["committed"]
    assert [(e["row"], e["column"]) for e in body["errors"]] == [(2, "price")]
    assert not Product.all_objects.filter(sku="GL-1").exists()


def test_file_type_and_size_are_checked(admin_client, monkeypatch):
    response = upload(admin_client, b"hello", name="catalogue.pdf")
    assert response.status_code == 400 and response.json()["error"]["code"] == "unsupported_file_type"
    monkeypatch.setattr(importer, "MAX_FILE_BYTES", 10)
    response = upload(admin_client)
    assert response.status_code == 400 and response.json()["error"]["code"] == "file_too_large"


@pytest.mark.parametrize("who", ["anonymous", "customer", "store_manager"])
def test_only_administrators(who, api_client, auth_client, staff_client):
    client = {"anonymous": api_client, "customer": auth_client, "store_manager": staff_client}[who]
    expected = 401 if who == "anonymous" else 403
    assert upload(client).status_code == expected
    assert client.get("/api/admin/catalog/export/?format=csv").status_code == expected
    assert client.get("/api/admin/catalog/template/?format=xlsx").status_code == expected


def test_export_and_template_downloads(admin_client):
    upload(admin_client, dry_run="false")
    csv_response = admin_client.get("/api/admin/catalog/export/?format=csv")
    assert csv_response.status_code == 200
    assert csv_response["Content-Type"].startswith("text/csv")
    assert 'filename="catalogue.csv"' in csv_response["Content-Disposition"]
    table = read_table(csv_response.content, "catalogue.csv")
    assert [cells["variant_sku"] for _, cells in table.rows] == ["GL-1-M"]
    assert table.rows[0][1]["cost_price"] == "120.00"

    xlsx = admin_client.get("/api/admin/catalog/export/")  # Excel by default
    assert xlsx.status_code == 200 and xlsx.content.startswith(b"PK")
    blank = admin_client.get("/api/admin/catalog/template/?format=csv")
    assert read_table(blank.content, "t.csv").columns == importer.COLUMN_NAMES
    assert admin_client.get("/api/admin/catalog/template/?format=pdf").status_code == 400


# --- Demo flag and purchase cost --------------------------------------------------------------------


def test_admin_list_shows_and_filters_demo_products(admin_client):
    real, _ = create_product(name="Real")
    demo, _ = create_product(name="Demo")
    Product.all_objects.filter(pk=demo.pk).update(is_demo=True)
    rows = admin_client.get("/api/admin/products/").json()["results"]
    assert {r["sku"]: r["is_demo"] for r in rows} == {real.sku: False, demo.sku: True}
    only_demo = admin_client.get("/api/admin/products/?demo=true").json()["results"]
    assert [r["sku"] for r in only_demo] == [demo.sku]
    only_real = admin_client.get("/api/admin/products/?demo=false").json()["results"]
    assert [r["sku"] for r in only_real] == [real.sku]


def test_cost_price_is_admin_only_and_never_public(admin_client, staff_client, api_client):
    product, variant = create_product(name="Hinge")
    patch = admin_client.patch(
        f"/api/admin/products/{product.pk}/",
        {
            "variants": [
                {"id": variant.pk, "sku": variant.sku, "mrp": "1000.00", "price": "900.00", "cost_price": "610"}
            ]
        },
        format="json",
    )
    assert patch.status_code == 200, patch.content
    assert patch.json()["variants"][0]["cost_price"] == "610.00"
    assert "cost_price" not in staff_client.get(f"/api/admin/products/{product.pk}/").json()["variants"][0]

    public_detail = api_client.get(f"/api/products/{product.slug}/")
    public_list = api_client.get("/api/products/")
    assert public_detail.status_code == 200 and public_list.status_code == 200
    for response in (public_detail, public_list):
        text = json.dumps(response.json())
        assert "cost_price" not in text and "610" not in text
