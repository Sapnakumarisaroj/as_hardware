"""The shop's approved category tree and the safe way to apply it.

The owner approved exactly ten top-level categories (2026-10-07). Everything else is archived, never
deleted: orders, returns, payments and reviews keep pointing at the same rows, and an administrator
can restore a category or product from the dashboard.

    python manage.py apply_taxonomy --dry-run   # what would change
    python manage.py apply_taxonomy             # create/rename the approved tree, archive the rest

Archiving a category: soft-deleted and inactive (hidden from navigation, filters and search).
Archiving a product: unpublished, inactive and soft-deleted (hidden everywhere customers look; carts
and wishlists already refuse unavailable products). Rules that only make sense for archived
categories or products (offers, coupons, free-delivery rules, curated lists, recommendation rules,
bundles) are switched off; option types lose the archived categories.

Subcategory slugs that already existed (drills, gloves, fasteners …) are kept, so their pages,
offers and links keep working; they are only moved under their new parent.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

# (slug, name) → [(slug, name), …]. Order = order in the menu.
APPROVED_TAXONOMY: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("plywood-mdf-hdhmr", "Plywood, MDF & HDHMR"): [
        ("plywood", "Plywood"),
        ("mdf", "MDF Boards"),
        ("hdhmr", "HDHMR Boards"),
    ],
    # A brand-led category: the products also carry the brand "Fevicol" (no separate sub-brand tree).
    ("fevicol", "Fevicol"): [
        ("fevicol-wood-adhesives", "Wood Adhesives"),
        ("fevicol-contact-adhesives", "Contact Adhesives"),
        ("fevicol-waterproof-adhesives", "Waterproof Adhesives"),
    ],
    ("hinges-channels-handles", "Hinges, Channels & Handles"): [
        ("hinges", "Hinges"),
        ("drawer-channels", "Drawer Channels"),
        ("cabinet-handles", "Handles & Knobs"),
    ],
    ("kitchen-systems", "Kitchen Systems & Accessories"): [
        ("kitchen-baskets", "Kitchen Baskets"),
        ("kitchen-tall-units", "Tall Units & Corner Solutions"),
        ("kitchen-accessories", "Kitchen Accessories"),
    ],
    ("wardrobe-bed-fittings", "Wardrobe & Bed Fittings"): [
        ("wardrobe-fittings", "Wardrobe Fittings"),
        ("bed-fittings", "Bed Fittings"),
    ],
    ("door-locks-hardware", "Door Locks & Hardware"): [
        ("door-locks", "Door Locks"),
        ("door-hardware", "Door Closers, Stoppers & Bolts"),
    ],
    ("power-tools", "Power Tools & Accessories"): [
        ("drills", "Drills"),
        ("drill-bits", "Drill Bits"),
        ("grinders", "Grinders & Cutters"),
    ],
    ("general-hardware", "General Hardware & Tools"): [
        ("screwdrivers", "Screwdrivers"),
        ("hammers", "Hammers"),
        ("spanners", "Spanners & Wrenches"),
        ("measuring-tools", "Measuring Tools"),
        ("cutting-tools", "Cutting Tools"),
        ("fasteners", "Nuts, Bolts & Screws"),
        ("sealants", "Sealants & Abrasives"),
    ],
    ("safety", "Safety Tools & Workwear"): [
        ("gloves", "Gloves"),
        ("helmets", "Helmets"),
        ("masks", "Masks"),
        ("safety-shoes", "Safety Shoes"),
        ("protective-equipment", "Eye & Ear Protection"),
        ("workwear", "Workwear"),
    ],
    ("glass-door-hardware", "Glass Door Hardware"): [
        ("patch-fittings", "Patch Fittings"),
        ("glass-door-handles", "Glass Door Handles"),
        ("floor-springs", "Floor Springs"),
    ],
}


# Compact labels for menus and tiles; pages and dropdowns keep the full name.
SHORT_NAMES = {
    "plywood-mdf-hdhmr": "Plywood & Boards",
    "fevicol": "Fevicol",
    "hinges-channels-handles": "Hinges & Handles",
    "kitchen-systems": "Kitchen Accessories",
    "wardrobe-bed-fittings": "Wardrobe & Bed",
    "door-locks-hardware": "Door Hardware",
    "power-tools": "Power Tools",
    "general-hardware": "Hardware & Tools",
    "safety": "Safety & Workwear",
    "glass-door-hardware": "Glass Hardware",
}


def short_name(slug: str, name: str) -> str:
    return SHORT_NAMES.get(slug, name)


def approved_slugs() -> set[str]:
    slugs = set()
    for (slug, _name), children in APPROVED_TAXONOMY.items():
        slugs.add(slug)
        slugs.update(child for child, _ in children)
    return slugs


def top_level_names() -> list[str]:
    return [name for (_slug, name) in APPROVED_TAXONOMY]


@dataclass
class TaxonomyReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    moved_products: list[str] = field(default_factory=list)
    archived_categories: list[str] = field(default_factory=list)
    archived_products: list[str] = field(default_factory=list)
    switched_off: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{len(self.created)} categories created, {len(self.updated)} updated, "
            f"{len(self.archived_categories)} archived; {len(self.moved_products)} products moved, "
            f"{len(self.archived_products)} archived; "
            f"{len(self.switched_off)} rules/bundles switched off"
        )


def apply_taxonomy(*, dry_run: bool = False, archive: bool = True) -> TaxonomyReport:
    """Create or rename the approved categories, then archive every other category and the products
    outside the approved tree. Idempotent. `dry_run` reports without changing anything."""
    report = TaxonomyReport()
    with transaction.atomic():
        nodes = _ensure_tree(report)
        _move_products(nodes, report)
        if archive:
            _archive_outside(report)
        if dry_run:
            transaction.set_rollback(True)
    return report


def _ensure_tree(report: TaxonomyReport) -> dict:
    from .models import Category

    nodes = {}

    def upsert(slug, name, parent, position):
        row = Category.all_objects.filter(slug=slug).first()
        wanted = {"name": name, "parent": parent, "sort_order": position, "is_active": True, "is_deleted": False}
        if row is None:
            nodes[slug] = Category.all_objects.create(slug=slug, **wanted)
            report.created.append(slug)
            return nodes[slug]
        changed = [k for k, v in wanted.items() if getattr(row, k) != v]
        if changed:
            for key, value in wanted.items():
                setattr(row, key, value)
            row.deleted_at = None
            row.save()
            report.updated.append(slug)
        nodes[slug] = row
        return row

    for position, ((slug, name), children) in enumerate(APPROVED_TAXONOMY.items()):
        parent = upsert(slug, name, None, position)
        for child_pos, (child_slug, child_name) in enumerate(children):
            upsert(child_slug, child_name, parent, child_pos)
    return nodes


def _move_products(nodes: dict, report: TaxonomyReport) -> None:
    """A product whose subcategory (or category) is an approved subcategory is put under that
    subcategory's approved parent, so moving a subcategory never archives its products."""
    from .models import Product

    parent_of = {child: top for (top, _), children in APPROVED_TAXONOMY.items() for child, _ in children}
    for product in Product.all_objects.select_related("category", "subcategory"):
        sub = product.subcategory.slug if product.subcategory_id else None
        cat = product.category.slug
        if sub in parent_of:
            target = (parent_of[sub], sub)
        elif cat in parent_of:
            target = (parent_of[cat], cat)
        else:
            continue
        if (cat, sub) != target:
            Product.all_objects.filter(pk=product.pk).update(
                category=nodes[target[0]], subcategory=nodes[target[1]], updated_at=timezone.now()
            )
            report.moved_products.append(product.sku)


def _archive_outside(report: TaxonomyReport) -> None:
    from apps.offers.models import Coupon, Offer

    from .models import Category, Collection, OptionType, Product

    now = timezone.now()
    keep = approved_slugs()
    outside = Category.all_objects.exclude(slug__in=keep)
    archived_ids = list(outside.values_list("pk", flat=True))
    for slug in outside.filter(Q(is_deleted=False) | Q(is_active=True)).values_list("slug", flat=True):
        report.archived_categories.append(slug)
    outside.update(is_active=False, is_deleted=True, deleted_at=now, updated_at=now)

    products = Product.all_objects.filter(Q(category_id__in=archived_ids) | Q(subcategory_id__in=archived_ids))
    visible = products.filter(Q(is_deleted=False) | Q(is_active=True) | Q(is_published=True))
    report.archived_products.extend(visible.values_list("sku", flat=True))
    visible.update(is_active=False, is_published=False, is_deleted=True, deleted_at=now, updated_at=now)

    # Rules aimed only at archived categories would never apply again: switch them off.
    for model in (Offer, Coupon, Collection, _free_delivery_rule()):
        targeted = model.objects.filter(is_active=True, categories__isnull=False).distinct()
        for row in targeted.prefetch_related("categories"):
            if all(c.pk in archived_ids for c in row.categories.all()):
                model.objects.filter(pk=row.pk).update(is_active=False)
                report.switched_off.append(f"{model.__name__}: {row}")
    for option_type in OptionType.objects.filter(categories__in=archived_ids).distinct():
        option_type.categories.remove(*archived_ids)
        if not option_type.categories.exists():
            OptionType.objects.filter(pk=option_type.pk).update(is_active=False)
            report.switched_off.append(f"OptionType: {option_type}")

    from apps.shopping.models import Bundle, RecommendationRule

    rules = RecommendationRule.objects.filter(is_active=True).filter(
        Q(source_category_id__in=archived_ids) | Q(target_category_id__in=archived_ids)
    )
    report.switched_off.extend(f"RecommendationRule: {r}" for r in rules)
    rules.update(is_active=False)
    archived_products = Product.all_objects.filter(is_deleted=True).values("pk")
    bundles = Bundle.objects.filter(is_active=True, items__product_id__in=archived_products).distinct()
    report.switched_off.extend(f"Bundle: {b.name}" for b in bundles)
    Bundle.objects.filter(pk__in=[b.pk for b in bundles]).update(is_active=False)


def _free_delivery_rule():
    from apps.delivery.models import FreeDeliveryRule

    return FreeDeliveryRule
