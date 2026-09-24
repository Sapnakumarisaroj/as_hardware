"""Load DEVELOPMENT/DEMO catalog, stores, stock, coupons and automatic offers.

    python manage.py seed_demo_data

Idempotent (safe to re-run). Refuses to run when DEBUG is off unless --force is given,
so demo products can't slip into a production database by accident.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.catalog.models import Brand, Category, Product, ProductSpecification, ProductVariant, normalize_sku
from apps.delivery.models import DeliveryZone
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import apply_movement
from apps.offers.models import Coupon, Offer
from apps.stores.models import Store

from ..demo_data import BRANDS, CATEGORIES, COUPONS, OFFERS, PRODUCTS, STORES

DEMO_NOTE = "Demo data for development — not a real product listing."


class Command(BaseCommand):
    help = "Seed development/demo data (categories, brands, products, specs, stores, inventory, coupons, offers)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Allow running with DEBUG=False (staging only).")
        parser.add_argument("--no-images", action="store_true", help="Skip generating demo product images.")

    def handle(self, *args, force=False, no_images=False, **options):
        if not settings.DEBUG and not force:
            raise CommandError("Refusing to seed demo data with DEBUG=False. Use --force only on a staging site.")
        with transaction.atomic():
            categories = self._categories()
            brands = {
                name: Brand.objects.update_or_create(name=name, defaults={"slug": slugify(name)})[0] for name in BRANDS
            }
            products = self._products(categories, brands)
            stores = self._stores()
            created_stock = self._inventory(stores, products)
            self._coupons()
            self._offers()
        created_images = 0 if no_images else self._images(products)
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready: {Category.objects.count()} categories, {len(brands)} brands, "
                f"{len(products)} products, {ProductVariant.objects.filter(sku__startswith='DEMO-').count()} variants, "
                f"{len(stores)} stores, {created_stock} new stock records, {len(COUPONS)} coupons, "
                f"{len(OFFERS)} offers, {created_images} new demo images."
            )
        )

    def _images(self, products) -> int:
        """Locally drawn, clearly-labelled demo pictures (only for products without images)."""
        from ..demo_images import ensure_demo_images

        specs_by_name = {row[2]: row[8] for row in PRODUCTS}
        created = 0
        for product in products:
            variant_names = list(product.variants.order_by("sort_order").values_list("name", flat=True))
            created += ensure_demo_images(
                product, product.category.slug, variant_names, specs_by_name.get(product.name, [])
            )
        return created

    def _categories(self) -> dict[str, Category]:
        result = {}
        for position, ((slug, name), children) in enumerate(CATEGORIES.items()):
            parent, _ = Category.all_objects.update_or_create(
                slug=slug, defaults={"name": name, "parent": None, "sort_order": position, "is_deleted": False}
            )
            result[slug] = parent
            for child_pos, (child_slug, child_name) in enumerate(children):
                result[child_slug], _ = Category.all_objects.update_or_create(
                    slug=child_slug,
                    defaults={"name": child_name, "parent": parent, "sort_order": child_pos, "is_deleted": False},
                )
        return result

    def _products(self, categories, brands) -> list[Product]:
        products = []
        for index, (cat, sub, name, brand, unit, gst, tags, variants, specs) in enumerate(PRODUCTS):
            base_sku = normalize_sku(f"DEMO-{variants[0][0].split('-')[0]}-{index:03d}")
            product, _ = Product.all_objects.update_or_create(
                sku=base_sku,
                defaults={
                    "name": name,
                    "slug": slugify(name)[:220],
                    "brand": brands[brand],
                    "category": categories[cat],
                    "subcategory": categories[sub],
                    "unit": unit,
                    "gst_rate": Decimal(gst),
                    "tags": tags,
                    "short_description": f"{name}. {DEMO_NOTE}",
                    "description": DEMO_NOTE,
                    "is_active": True,
                    "is_published": True,
                    "is_featured": index % 7 == 0,
                    "is_deleted": False,
                },
            )
            for position, (suffix, vname, mrp, price, weight) in enumerate(variants):
                ProductVariant.objects.update_or_create(
                    sku=normalize_sku(f"DEMO-{suffix}"),
                    defaults={
                        "product": product,
                        "name": vname,
                        "mrp": Decimal(mrp),
                        "price": Decimal(price),
                        "weight_grams": weight,
                        "is_default": position == 0,
                        "sort_order": position,
                        "is_active": True,
                    },
                )
            product.specifications.all().delete()
            for position, (spec_name, value, spec_unit) in enumerate(specs):
                ProductSpecification.objects.create(
                    product=product, name=spec_name, value=value, unit=spec_unit, sort_order=position
                )
            products.append(product)
        return products

    def _stores(self) -> list[Store]:
        stores = []
        for code, name, kind, area, pin, lat, lng in STORES:
            store, _ = Store.all_objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "kind": kind,
                    "address_line1": f"{area} (demo address)",
                    "area": area,
                    "city": "Pune",
                    "state": "Maharashtra",
                    "postal_code": pin,
                    "latitude": Decimal(lat),
                    "longitude": Decimal(lng),
                    "is_active": True,
                    "is_deleted": False,
                },
            )
            if store.can_fulfill_orders:
                DeliveryZone.objects.get_or_create(
                    store=store, name=f"{area} 5 km", defaults={"radius_km": Decimal("5")}
                )
            stores.append(store)
        return stores

    def _inventory(self, stores, products) -> int:
        rng = random.Random(42)  # noqa: S311 - deterministic demo stock levels, not security-related
        created = 0
        for store in stores:
            for product in products:
                for variant in product.variants.all():
                    inventory, is_new = Inventory.objects.get_or_create(store=store, variant=variant)
                    if not is_new:
                        continue
                    created += 1
                    # ~10% of store stock records start at zero to exercise out-of-stock paths.
                    quantity = 0 if (store.kind != "warehouse" and rng.random() < 0.1) else rng.randint(5, 80)
                    if store.kind == "warehouse":
                        quantity *= 5
                    if quantity:
                        apply_movement(
                            inventory,
                            StockMovement.Type.PURCHASE,
                            quantity,
                            reason="Demo opening stock",
                            reference_type="demo_seed",
                        )
        return created

    def _coupons(self) -> None:
        now = timezone.now()
        for code, description, kind, value, max_discount, min_order in COUPONS:
            Coupon.objects.update_or_create(
                code=code,
                defaults={
                    "description": description,
                    "discount_type": kind,
                    "value": Decimal(value),
                    "max_discount_amount": Decimal(max_discount) if max_discount else None,
                    "min_order_value": Decimal(min_order),
                    "starts_at": now - timedelta(days=1),
                    "ends_at": now + timedelta(days=365),
                    "per_customer_limit": 5,
                    "is_active": True,
                    "show_in_checkout": True,
                },
            )

    def _offers(self) -> None:
        now = timezone.now()
        for name, description, kind, value, max_discount, min_order, priority, category_slugs in OFFERS:
            offer, _ = Offer.objects.update_or_create(
                name=name,
                defaults={
                    "description": description,
                    "discount_type": kind,
                    "value": Decimal(value),
                    "max_discount_amount": Decimal(max_discount) if max_discount else None,
                    "min_order_value": Decimal(min_order),
                    "priority": priority,
                    "starts_at": now - timedelta(days=1),
                    "ends_at": now + timedelta(days=90),
                    "is_active": True,
                },
            )
            offer.categories.set(Category.objects.filter(slug__in=category_slugs))
