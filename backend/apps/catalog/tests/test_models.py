from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import Category, Product, ProductSpecification, ProductVariant, SubCategory, TopCategory
from apps.core.testing import create_category, create_product

pytestmark = pytest.mark.django_db


def test_category_subcategory_relationship():
    tools = create_category("Tools")
    drills = create_category("Drills", parent=tools)
    assert drills.is_subcategory and not tools.is_subcategory
    assert list(tools.children.all()) == [drills]
    assert list(SubCategory.objects.all()) == [drills]
    assert list(TopCategory.objects.all()) == [tools]
    assert str(drills) == "Tools › Drills"


def test_category_depth_limited_to_three_levels():
    # Phase 15: department › category › subcategory is allowed; a fourth level is not.
    top = create_category("Plumbing")
    sub = create_category("Pipes", parent=top)
    grandchild = Category(name="CPVC", slug="cpvc", parent=sub)
    grandchild.clean()
    grandchild.save()
    great_grandchild = Category(name="CPVC 1 inch", slug="cpvc-1", parent=grandchild)
    with pytest.raises(ValidationError):
        great_grandchild.clean()


def test_product_subcategory_must_belong_to_category():
    tools, plumbing = create_category("Tools"), create_category("Plumbing")
    pipes = create_category("Pipes", parent=plumbing)
    product = Product(name="X", sku="X-1", slug="x", category=tools, subcategory=pipes)
    with pytest.raises(ValidationError) as exc:
        product.clean()
    assert "subcategory" in exc.value.message_dict


def test_product_creation_with_variant_and_discount():
    product, variant = create_product(price="750.00", mrp="1000.00")
    assert product.is_purchasable
    assert variant.discount_amount == Decimal("250.00")
    assert variant.discount_percent == Decimal("25.00")


def test_price_above_mrp_rejected_by_database():
    product, _ = create_product()
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductVariant.objects.create(product=product, sku="BAD-1", mrp=Decimal("100"), price=Decimal("150"))


def test_specification_key_and_numeric_value():
    product, _ = create_product()
    power = ProductSpecification.objects.create(product=product, name="Chuck Size", value="13", unit="mm")
    colour = ProductSpecification.objects.create(product=product, name="Colour", value="Blue")
    assert power.key == "chuck-size" and power.numeric_value == Decimal("13")
    assert colour.numeric_value is None
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductSpecification.objects.create(product=product, name="Chuck size", value="10")


def test_skus_are_normalised_to_upper_case():
    product, variant = create_product()
    variant.sku = " demo-abc-1 "
    variant.save()
    assert ProductVariant.objects.get(pk=variant.pk).sku == "DEMO-ABC-1"
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductVariant.objects.create(product=product, sku="Demo-Abc-1", mrp=Decimal("10"), price=Decimal("9"))


def test_soft_delete_hides_product_but_keeps_row():
    product, _ = create_product()
    product.delete()
    assert not Product.objects.filter(pk=product.pk).exists()
    assert Product.all_objects.filter(pk=product.pk, is_deleted=True).exists()
