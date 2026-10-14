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


def create_store(kind: str = Store.Kind.STORE, *, zone: bool = True, **kwargs) -> Store:
    """A store in PIN 411001. Fulfilment stores get a 5 km delivery zone unless `zone=False`
    (since Phase 9 an order can only ship from a store whose zone covers the address)."""
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
    store = Store.objects.create(**defaults)
    if zone and store.kind in Store.FULFILLMENT_KINDS:
        from apps.delivery.models import DeliveryZone

        DeliveryZone.objects.create(store=store, name="Test zone 5 km", radius_km=Decimal("5"))
    return store


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
    brand: Brand | None = None,
    **product_kwargs,
) -> tuple[Product, ProductVariant]:
    n = next(_seq)
    category = category or create_category()
    if brand is None:
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
        # Every delivery address has a map pin (checkout requires one). Pass latitude=None, longitude=None
        # for an old address saved before pins were required.
        # The delivery tests' reference point (apps/delivery/tests/helpers.py); stores without coordinates
        # still fall back to "same PIN as the store".
        "latitude": Decimal("18.507400"),
        "longitude": Decimal("73.807700"),
    }
    data.update(kwargs)
    return _create(user=user, **data)
