"""Small object builders for tests (no extra factory library needed)."""

import itertools
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.catalog.models import Brand, Category, Product, ProductVariant
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import apply_movement
from apps.stores.models import Store

_seq = itertools.count(1)


def create_category(name: str = "Tools", parent: Category | None = None) -> Category:
    n = next(_seq)
    return Category.objects.create(name=name, slug=f"{name.lower().replace(' ', '-')}-{n}", parent=parent)


def create_store(kind: str = Store.Kind.STORE, **kwargs) -> Store:
    n = next(_seq)
    defaults = {
        "name": f"Store {n}",
        "code": f"ST-{n}",
        "kind": kind,
        "address_line1": "1 Test Road",
        "city": "Pune",
        "state": "Maharashtra",
        "postal_code": "411001",
    }
    defaults.update(kwargs)
    return Store.objects.create(**defaults)


def create_product(
    *,
    name: str = "Test Drill",
    price: str = "900.00",
    mrp: str = "1000.00",
    category: Category | None = None,
    subcategory: Category | None = None,
    stock: int = 0,
    store: Store | None = None,
    published: bool = True,
    gst_rate: str = "18.00",
    **product_kwargs,
) -> tuple[Product, ProductVariant]:
    n = next(_seq)
    category = category or create_category()
    brand, _ = Brand.objects.get_or_create(name="Test Brand", defaults={"slug": "test-brand"})
    product = Product.objects.create(
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{n}",
        sku=f"P-{n}",
        category=category,
        subcategory=subcategory,
        brand=brand,
        is_published=published,
        gst_rate=Decimal(gst_rate),
        **product_kwargs,
    )
    variant = ProductVariant.objects.create(
        product=product, sku=f"V-{n}", mrp=Decimal(mrp), price=Decimal(price), is_default=True
    )
    if stock:
        add_stock(variant, stock, store=store)
    return product, variant


def add_stock(variant: ProductVariant, quantity: int, store: Store | None = None) -> Inventory:
    store = store or Store.objects.filter(kind=Store.Kind.STORE).first() or create_store()
    inventory, _ = Inventory.objects.get_or_create(store=store, variant=variant)
    apply_movement(inventory, StockMovement.Type.PURCHASE, quantity, reason="test stock")
    inventory.refresh_from_db()
    return inventory


def create_coupon(code: str = "SAVE10", **kwargs):
    from apps.offers.models import Coupon

    defaults = {
        "discount_type": "percent",
        "value": Decimal("10"),
        "starts_at": timezone.now() - timedelta(days=1),
        "ends_at": timezone.now() + timedelta(days=1),
    }
    defaults.update(kwargs)
    return Coupon.objects.create(code=code, **defaults)


def create_address(user, **kwargs):
    from apps.accounts.services import create_address as _create

    data = {
        "name": "Asha Kumar",
        "phone": "9876543210",
        "address_line1": "12 MG Road",
        "city": "Pune",
        "state": "Maharashtra",
        "postal_code": "411001",
    }
    data.update(kwargs)
    return _create(user=user, **data)
