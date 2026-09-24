"""Django admin catalog management: categories, brands, products with variants/specs/images."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import Brand, RecentSearch
from apps.core.testing import create_category, create_product

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_site_client():
    user = get_user_model().objects.create_superuser(email="root@example.com", password="Passw0rd!x")
    client = Client()
    client.force_login(user)
    return client


def test_catalog_admin_pages_load(admin_site_client, user):
    parent = create_category("Electrical")
    child = create_category("Switches", parent=parent)
    product, _ = create_product(name="Modular Switch", category=parent, subcategory=child)
    RecentSearch.objects.create(user=user, query="switch", normalized="switch", searched_at="2026-09-01T10:00Z")
    brand = Brand.objects.get(slug="test-brand")

    change_url = reverse("admin:catalog_product_change", args=[product.pk])
    pages = [
        reverse("admin:catalog_topcategory_changelist"),
        reverse("admin:catalog_topcategory_change", args=[parent.pk]),
        reverse("admin:catalog_subcategory_changelist"),
        reverse("admin:catalog_subcategory_change", args=[child.pk]),
        reverse("admin:catalog_brand_changelist"),
        reverse("admin:catalog_brand_change", args=[brand.pk]),
        reverse("admin:catalog_product_changelist"),
        reverse("admin:catalog_product_add"),
        change_url,
        reverse("admin:catalog_productvariant_changelist"),
        reverse("admin:catalog_recentsearch_changelist"),
    ]
    for url in pages:
        assert admin_site_client.get(url).status_code == 200, url
    # Product change page carries the variant, specification and image inlines.
    body = admin_site_client.get(change_url).content.decode()
    for prefix in ("variants-TOTAL_FORMS", "specifications-TOTAL_FORMS", "images-TOTAL_FORMS"):
        assert prefix in body


def test_customer_cannot_open_admin(client, user):
    client.force_login(user)
    res = client.get(reverse("admin:catalog_product_changelist"))
    assert res.status_code == 302 and reverse("admin:login") in res["Location"]
