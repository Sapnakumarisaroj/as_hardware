"""Bundles (Phase 22): kits of real catalogue products, priced, checked and added to the cart as one.

A bundle stores products and quantities only. Every time it is shown it goes through `ai.projects.kit.price_rows`
— the same engines as the cart: bulk tiers, automatic offers, free-delivery rules, zone fee, stock, order limits,
and the Phase 21 compatibility check between its items. The customer can change an item's variant or quantity or
untick it before adding the bundle; nothing is added until they press the button, and then all or nothing.
"""

from django.db.models import Prefetch, Q
from django.utils import timezone

from apps.ai.projects import kit
from apps.carts import services as carts
from apps.catalog.models import ProductVariant
from apps.core.exceptions import NotFoundError, ServiceError

from ..models import Bundle, BundleItem


class BundleError(ServiceError):
    default_code = "bundle_error"


def live_bundles():
    now = timezone.now()
    items = (
        BundleItem.objects.select_related("product__category", "product__subcategory", "variant__product")
        .prefetch_related(
            # what the pricing engine and the kit read per line, loaded once for every bundle
            "product__variants__option_values__option_type",
            "product__variants__option_values__value",
            "product__variants__price_tiers",
            "variant__option_values__option_type",
            "variant__option_values__value",
            "variant__price_tiers",
        )
        .order_by("sort_order", "id")
    )
    return (
        Bundle.objects.filter(is_active=True)
        .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .prefetch_related(Prefetch("items", queryset=items))
        .order_by("priority", "name")
    )


def get_live(slug: str) -> Bundle:
    bundle = live_bundles().filter(slug=slug).first()
    if bundle is None:
        raise NotFoundError("Bundle not found.")
    return bundle


def _variant_for(item: BundleItem) -> ProductVariant | None:
    if item.variant_id and item.variant and item.variant.is_active:
        return item.variant
    variants = [v for v in item.product.variants.all() if v.is_active]
    return next(
        (v for v in variants if v.is_default), min(variants, key=lambda v: (v.price, v.pk)) if variants else None
    )


def rows(bundle: Bundle, overrides: dict | None = None) -> list[kit.Row]:
    """Kit lines for the bundle, with the customer's edits ({item_id: {variant_id?, quantity?, included?}}).
    A variant must belong to the item's product: a bundle can be adjusted, not turned into another bundle."""
    overrides = {str(k): v for k, v in (overrides or {}).items()}
    out = []
    for item in bundle.items.all():
        change = overrides.get(str(item.pk)) or {}
        variant = _variant_for(item)
        if change.get("variant_id"):
            chosen = (
                ProductVariant.objects.select_related("product")
                .filter(pk=change["variant_id"], product_id=item.product_id, is_active=True)
                .first()
            )
            if chosen is None:
                raise BundleError(
                    "Choose one of this product's variants.", code="invalid_variant", details={"item": item.pk}
                )
            variant = chosen
        quantity = int(change.get("quantity") or item.quantity)
        if not 1 <= quantity <= 9999:
            raise BundleError(
                "Quantity must be between 1 and 9999.", code="invalid_quantity", details={"item": item.pk}
            )
        included = bool(change["included"]) if "included" in change else not item.is_optional
        details = {"status": "found" if variant else "not_found", "product_id": item.product_id, "note": item.note}
        out.append(
            kit.Row(
                item.pk,
                f"item-{item.pk}",
                item.product.name,
                variant,
                quantity,
                included,
                details,
                item.note,
                item.product.unit,
                item.is_optional,
                False,
                bool(change),
            )
        )
    return out


def price(
    bundle: Bundle, *, user=None, postal_code: str = "", address_id: int | None = None, overrides: dict | None = None
) -> dict:
    data = kit.price_rows(rows(bundle, overrides), user=user, postal_code=postal_code, address_id=address_id)
    totals = data["totals"]
    blocking = [p for p in data["compatibility"] if p["verdict"] == "NOT_COMPATIBLE"]
    return {
        "id": bundle.pk,
        "slug": bundle.slug,
        "name": bundle.name,
        "kind": bundle.kind,
        "kind_label": bundle.get_kind_display(),
        "description": bundle.description,
        "promo_label": bundle.promo_label,
        "kit": data,
        "savings": {
            "vs_mrp": totals["savings_vs_mrp"],
            "bulk": totals["bulk_savings"],
            "offers": totals["offer_discount"],
        },
        "valid": data["can_add_to_cart"] and not blocking,
    }


def summary(bundle: Bundle) -> dict:
    """List view: what's inside, and the price of the default selection from the pricing engine."""
    priced = price(bundle)
    return {
        **{
            k: priced[k]
            for k in ("id", "slug", "name", "kind", "kind_label", "description", "promo_label", "savings", "valid")
        },
        "item_count": len([i for i in priced["kit"]["items"] if i["included"]]),
        "total": priced["kit"]["totals"]["grand_total"],
        "subtotal": priced["kit"]["totals"]["subtotal"],
        "product_ids": [i["product_id"] for i in priced["kit"]["items"] if i["product_id"]],
    }


def add_to_cart(bundle: Bundle, *, user, overrides: dict | None = None, only_missing: bool = False) -> dict:
    """The ticked items into the cart through the cart service, all or nothing. `only_missing` (the smart cart's
    "complete with this bundle"): skip products the cart already has."""
    lines = [r for r in rows(bundle, overrides) if r.included]
    if only_missing:
        in_cart = set(carts.get_cart(user).items.values_list("variant__product_id", flat=True))
        lines = [r for r in lines if r.details["product_id"] not in in_cart]
    unavailable = [r.label for r in lines if r.variant is None]
    if unavailable:
        raise BundleError(
            f"Not available now: {', '.join(unavailable)}. Untick it to add the rest.", code="bundle_item_unavailable"
        )
    if not lines:
        raise BundleError("Nothing to add: tick at least one item.", code="bundle_empty")
    return kit.add_lines_to_cart(
        user, [(r.variant.pk, r.quantity) for r in lines], names={r.variant.pk: r.label for r in lines}
    )


def bundles_with(product_ids, *, limit: int = 3) -> list[Bundle]:
    """Live bundles that contain any of these products (for the product page and the smart cart)."""
    ids = list(product_ids)
    if not ids:
        return []
    return list(live_bundles().filter(items__product_id__in=ids).distinct()[:limit])
