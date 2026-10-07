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

from apps.catalog.models import (
    Brand,
    Category,
    Collection,
    OptionType,
    Product,
    ProductSpecification,
    ProductVariant,
    normalize_sku,
)
from apps.catalog.services import set_accessories, set_price_tiers, set_variant_options
from apps.catalog.taxonomy import apply_taxonomy, approved_slugs
from apps.catalog.tree import breadcrumb
from apps.delivery.models import DeliveryZone, FreeDeliveryRule, PinCode
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import apply_movement
from apps.offers.models import Coupon, Offer
from apps.stores.models import Store

from ..demo_data import (
    ACCESSORIES,
    BRANDS,
    BUNDLES,
    COLLECTIONS,
    COUPONS,
    FREE_DELIVERY_RULES,
    LAUNCHES,
    OFFERS,
    OFFERS_PHASE15,
    OPTION_TYPES,
    PIN_CODES,
    PRICE_TIERS,
    PRODUCT_PAGE_CONTENT,
    PRODUCTS,
    RECOMMENDATION_RULES,
    STORE_DELIVERY,
    STORES,
    VARIANT_OPTIONS,
    ZONES,
)

DEMO_NOTE = "Demo data for development — not a real product listing."


class Command(BaseCommand):
    help = "Seed development/demo data (categories, brands, products, specs, stores, inventory, coupons, offers)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Allow running with DEBUG=False (staging only).")
        parser.add_argument("--no-images", action="store_true", help="Skip generating demo product images.")
        parser.add_argument(
            "--with-rider",
            action="store_true",
            help="Also create a demo delivery partner (demo-rider@example.com) to try the rider app. "
            "Its random password is printed once.",
        )

    def _demo_rider(self) -> None:
        """A verified, offline delivery partner at the first demo store. The password is random
        and shown only now; nothing about it is stored in the code or the repository."""
        import secrets

        from django.contrib.auth import get_user_model

        from apps.delivery.models import DeliveryPartner

        User = get_user_model()
        email = "demo-rider@example.com"
        if User.objects.filter(email=email).exists():
            self.stdout.write(f"Demo rider {email} already exists (password unchanged; use `changepassword`).")
            return
        password = secrets.token_urlsafe(9) + "a1"
        user = User.objects.create_user(
            email, password, role="delivery_partner", full_name="Demo Rider", phone="9000000001"
        )
        DeliveryPartner.objects.create(
            user=user,
            phone="9000000001",
            vehicle_number="DEMO-0001",
            home_store=Store.objects.filter(code="DEMO-PUN-KTH").first(),
            is_verified=True,
        )
        self.stdout.write(self.style.WARNING(f"Demo rider created: {email} / password: {password}  (shown once)"))

    def handle(self, *args, force=False, no_images=False, with_rider=False, **options):
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
            self._commerce(products)
            self._product_pages()
            self._loyalty()
            self._shopping()
            retired = self._retire_old_demo_data(products)
            if with_rider:
                self._demo_rider()
        created_images = 0 if no_images else self._images(products)
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready: {Category.objects.count()} categories, {len(brands)} brands, "
                f"{len(products)} products, {ProductVariant.objects.filter(product__in=products).count()} variants, "
                f"{len(stores)} stores, {created_stock} new stock records, {len(COUPONS)} coupons, "
                f"{len(OFFERS) + len(OFFERS_PHASE15)} offers, {len(COLLECTIONS)} curated lists, "
                f"{len(BUNDLES)} bundles, "
                f"{created_images} new demo images. {retired}"
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
                product, breadcrumb(product.category)[0].slug, variant_names, specs_by_name.get(product.name, [])
            )
        return created

    def _categories(self) -> dict[str, Category]:
        """The approved tree (apps.catalog.taxonomy); categories outside it are archived at the end."""
        apply_taxonomy(archive=False)
        return {c.slug: c for c in Category.objects.filter(slug__in=approved_slugs())}

    def _retire_old_demo_data(self, products) -> str:
        """Earlier demo catalogues (cement, paint, wiring, plumbing …) are archived, never deleted: a
        development database may have orders, carts or reviews that point at them."""
        from apps.catalog.models import Brand
        from apps.shopping.models import Bundle

        now = timezone.now()
        old = Product.all_objects.filter(sku__startswith="DEMO-").exclude(pk__in=[p.pk for p in products])
        old_count = old.filter(is_deleted=False).count()
        old.update(is_active=False, is_published=False, is_deleted=True, deleted_at=now, updated_at=now)
        report = apply_taxonomy()
        Brand.objects.filter(name__endswith="(Demo)").exclude(name__in=BRANDS).update(is_active=False)
        Offer.objects.filter(name__startswith="Demo:").exclude(
            name__in=[o[0] for o in OFFERS] + [o["name"] for o in OFFERS_PHASE15]
        ).update(is_active=False)
        Collection.objects.filter(name__startswith="Demo:").exclude(name__in=[c[0] for c in COLLECTIONS]).update(
            is_active=False
        )
        FreeDeliveryRule.objects.filter(name__startswith="Demo:").exclude(
            name__in=[r[0] for r in FREE_DELIVERY_RULES]
        ).update(is_active=False)
        Bundle.objects.filter(name__startswith="Demo:").exclude(name__in=[b[0] for b in BUNDLES]).update(
            is_active=False
        )
        OptionType.objects.exclude(name__in=[o[0] for o in OPTION_TYPES]).update(is_active=False)
        return (
            f"Archived {old_count} old demo products and {len(report.archived_categories)} categories outside the "
            f"approved list; {len(report.archived_products)} more products archived with them."
        )

    def _products(self, categories, brands) -> list[Product]:
        products = []
        for index, (cat, sub, name, brand, unit, gst, tags, variants, specs) in enumerate(PRODUCTS):
            # Found again by its first variant, so reordering or removing demo products never duplicates one.
            first_variant = normalize_sku(f"DEMO-{variants[0][0]}")
            existing = Product.all_objects.filter(variants__sku=first_variant).first()
            base_sku = existing.sku if existing else normalize_sku(f"DEMO-P-{variants[0][0]}")
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
                    **STORE_DELIVERY.get(code, {}),
                },
            )
            stores.append(store)
        by_code = {store.code: store for store in stores}
        for code, name, radius, pins, fast, fast_max, fee, free_min in ZONES:
            DeliveryZone.objects.update_or_create(
                store=by_code[code],
                name=name,
                defaults={
                    "radius_km": Decimal(radius),
                    "postal_codes": pins,
                    "fast_delivery_enabled": fast,
                    "fast_delivery_max_minutes": fast_max,
                    "delivery_fee_override": Decimal(fee) if fee else None,
                    "free_delivery_min_order": Decimal(free_min) if free_min else None,
                },
            )
        for postal_code, area, lat, lng in PIN_CODES:
            PinCode.objects.update_or_create(
                postal_code=postal_code,
                defaults={
                    "area": area,
                    "city": "Pune",
                    "state": "Maharashtra",
                    "latitude": Decimal(lat),
                    "longitude": Decimal(lng),
                },
            )
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

    def _loyalty(self) -> None:
        """Phase 17 demo: one cashback rule. No balances are seeded — credits only come from orders,
        returns, referrals or a promotional credit given in the dashboard (with a reason)."""
        from apps.loyalty.models import CashbackRule

        CashbackRule.objects.update_or_create(
            name="Demo: 2% cashback on orders from ₹50,000",
            defaults={
                "description": "Demo rule: 2% of what you pay, up to ₹2,000, usable after the return window.",
                "reward_type": "percent",
                "percent": Decimal("2"),
                "max_amount": Decimal("2000"),
                "min_order_value": Decimal("50000"),
                "starts_at": timezone.now() - timedelta(days=1),
                "ends_at": None,
                "is_active": True,
            },
        )

    def _product_pages(self) -> None:
        """Phase 16 demo data: product-page content (uses, steps, FAQ) and linked accessories."""
        variants = {v.sku: v for v in ProductVariant.objects.filter(sku__startswith="DEMO-")}

        def product_id(suffix):
            variant = variants.get(normalize_sku(f"DEMO-{suffix}"))
            return variant.product_id if variant else None

        for suffix, content in PRODUCT_PAGE_CONTENT.items():
            if pk := product_id(suffix):
                Product.objects.filter(pk=pk).update(**content)
        for suffix, rows in ACCESSORIES.items():
            if pk := product_id(suffix):
                links = [{"product": rid, "note": note} for s, note in rows if (rid := product_id(s))]
                set_accessories(Product.objects.get(pk=pk), links)

    def _shopping(self) -> None:
        """Phase 22 demo bundles and "complete the project" rules (idempotent)."""
        from apps.shopping.models import Bundle, RecommendationRule

        variants = {v.sku: v for v in ProductVariant.objects.filter(sku__startswith="DEMO-").select_related("product")}
        for position, (name, kind, description, promo, rows) in enumerate(BUNDLES):
            bundle, _ = Bundle.objects.update_or_create(
                slug=slugify(name),
                defaults={
                    "name": name,
                    "kind": kind,
                    "description": description,
                    "promo_label": promo,
                    "is_active": True,
                    "priority": (position + 1) * 10,
                },
            )
            bundle.items.all().delete()
            for item_pos, (suffix, quantity, optional, note) in enumerate(rows):
                if variant := variants.get(normalize_sku(f"DEMO-{suffix}")):
                    bundle.items.create(
                        product_id=variant.product_id,
                        variant=variant,
                        quantity=quantity,
                        is_optional=optional,
                        note=note,
                        sort_order=item_pos,
                    )
        by_slug = {c.slug: c for c in Category.objects.all()}
        for source, target, label, priority in RECOMMENDATION_RULES:
            if source in by_slug and target in by_slug:
                RecommendationRule.objects.update_or_create(
                    source_category=by_slug[source],
                    target_category=by_slug[target],
                    defaults={"label": label, "priority": priority, "is_active": True},
                )

    def _commerce(self, products) -> None:
        """Phase 15 demo data: options, bulk prices, launches, curated lists, free-delivery rule, offers."""
        now = timezone.now()
        types = {}
        for position, (name, unit, category_slugs, values) in enumerate(OPTION_TYPES):
            option_type, _ = OptionType.objects.update_or_create(
                name=name, defaults={"slug": slugify(name), "unit": unit, "sort_order": position, "is_active": True}
            )
            option_type.categories.set(Category.objects.filter(slug__in=category_slugs))
            for value_pos, value in enumerate(values):
                option_type.values.update_or_create(
                    slug=slugify(value), defaults={"value": value, "sort_order": value_pos}
                )
            types[name] = option_type
        variants = {v.sku: v for v in ProductVariant.objects.filter(sku__startswith="DEMO-").select_related("product")}
        for suffix, options in VARIANT_OPTIONS.items():
            if variant := variants.get(normalize_sku(f"DEMO-{suffix}")):
                set_variant_options(variant, [{"option_type": types[k].pk, "value": v} for k, v in options.items()])
        for suffix, tiers in PRICE_TIERS.items():
            if variant := variants.get(normalize_sku(f"DEMO-{suffix}")):
                set_price_tiers(variant, [{"min_quantity": m, "unit_price": p} for m, p in tiers])
        for suffix, days in LAUNCHES.items():
            if variant := variants.get(normalize_sku(f"DEMO-{suffix}")):
                Product.objects.filter(pk=variant.product_id).update(
                    launch_date=timezone.localdate() - timedelta(days=days)
                )
        for position, (name, rule, description, days, suffixes) in enumerate(COLLECTIONS):
            collection, _ = Collection.objects.update_or_create(
                name=name,
                defaults={
                    "slug": slugify(name),
                    "rule": rule,
                    "description": description,
                    "window_days": 60 if rule == "new_launches" else 30,
                    "starts_at": now - timedelta(hours=1) if days else None,
                    "ends_at": now + timedelta(days=days) if days else None,
                    "is_active": True,
                    "sort_order": position,
                },
            )
            collection.items.all().delete()
            for item_pos, suffix in enumerate(suffixes):
                if variant := variants.get(normalize_sku(f"DEMO-{suffix}")):
                    collection.items.create(product_id=variant.product_id, sort_order=item_pos)
        for name, threshold, category_slugs in FREE_DELIVERY_RULES:
            rule, _ = FreeDeliveryRule.objects.update_or_create(
                name=name,
                defaults={
                    "threshold": Decimal(threshold),
                    "starts_at": now - timedelta(days=1),
                    "ends_at": now + timedelta(days=90),
                    "is_active": True,
                },
            )
            rule.categories.set(Category.objects.filter(slug__in=category_slugs))
        for data in OFFERS_PHASE15:
            data = dict(data)
            category_slugs = data.pop("categories")
            defaults = {
                "discount_type": "percent",
                "value": Decimal("0"),
                "starts_at": now - timedelta(days=1),
                "ends_at": now + timedelta(days=90),
                "is_active": True,
                **{k: Decimal(v) if k in ("value", "max_discount_amount") else v for k, v in data.items()},
            }
            offer, _ = Offer.objects.update_or_create(name=defaults.pop("name"), defaults=defaults)
            offer.categories.set(Category.objects.filter(slug__in=category_slugs))
