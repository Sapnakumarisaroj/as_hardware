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


def test_demo_rider_is_opt_in_with_a_random_password_shown_once(settings, capsys):
    from django.contrib.auth import get_user_model

    from apps.delivery.models import DeliveryPartner

    settings.DEBUG = True
    call_command("seed_demo_data", "--no-images")
    assert not DeliveryPartner.objects.exists()

    call_command("seed_demo_data", "--no-images", "--with-rider")
    out = capsys.readouterr().out
    partner = DeliveryPartner.objects.select_related("user", "home_store").get()
    assert partner.user.email == "demo-rider@example.com" and partner.user.role == "delivery_partner"
    assert partner.is_verified and partner.status == "offline" and partner.home_store.code == "DEMO-PUN-KTH"
    password = out.split("password: ")[1].split()[0]
    assert len(password) >= 12 and partner.user.check_password(password)

    call_command("seed_demo_data", "--no-images", "--with-rider")
    assert "already exists" in capsys.readouterr().out
    assert get_user_model().objects.get(email="demo-rider@example.com").check_password(password)
    assert DeliveryPartner.objects.count() == 1
