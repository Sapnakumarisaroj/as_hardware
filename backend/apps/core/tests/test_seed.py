import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalog.models import Product, ProductVariant
from apps.inventory.models import StockMovement
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def test_seed_refuses_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_demo_data")


def test_seed_is_idempotent_and_clearly_labelled(settings):
    settings.DEBUG = True
    call_command("seed_demo_data")
    counts = (Product.objects.count(), ProductVariant.objects.count(), StockMovement.objects.count())
    call_command("seed_demo_data")
    assert (Product.objects.count(), ProductVariant.objects.count(), StockMovement.objects.count()) == counts

    assert counts[0] > 30
    assert not ProductVariant.objects.exclude(sku__startswith="DEMO-").exists()
    assert not Product.objects.exclude(sku__startswith="DEMO-").exists()
    assert not Store.objects.exclude(code__startswith="DEMO-").exists()
    assert all("(Demo)" in p.brand.name for p in Product.objects.select_related("brand"))
    assert all(p.specifications.exists() for p in Product.objects.all())
