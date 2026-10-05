"""Price preview for one product line (Phase 15): "10 bags → ₹415 per bag".

Runs the shop's single pricing engine (`orders.pricing.price_lines`) on one line, so the product
page, the assistant and future voice/quantity features show exactly what the cart will charge.
It is still a preview: the cart and checkout price again from the database when ordering.
"""

from apps.core.exceptions import ServiceError
from apps.orders.pricing import line_from_variant, price_lines

from . import selectors
from .serializers import _money, tier_rows
from .services import resolve_variant


class QuoteError(ServiceError):
    default_code = "invalid_quote"


def _variant_for(product, params):
    variants = [v for v in product.variants.all() if v.is_active]
    if not variants:
        raise QuoteError("This product isn't available.", code="product_unavailable")
    if raw := (params.get("variant") or "").strip():
        variant = next((v for v in variants if str(v.pk) == raw), None)
        if variant is None:
            raise QuoteError("Choose one of this product's variants.", code="invalid_variant")
        return variant
    wanted = selectors.option_filters(params)
    if wanted:
        chosen = resolve_variant(product, {key: values[0] for key, values in wanted.items()})
        return next(v for v in variants if v.pk == chosen.pk)
    return next((v for v in variants if v.is_default), min(variants, key=lambda v: (v.price, v.pk)))


def quote_product(product, params, *, user=None) -> dict:
    variant = _variant_for(product, params)
    raw_quantity = (params.get("quantity") or "1").strip()
    if not raw_quantity.isdigit() or int(raw_quantity) < 1:
        raise QuoteError("Quantity must be a whole number of at least 1.", code="invalid_quantity")
    quantity = int(raw_quantity)
    if quantity > product.max_order_quantity:
        raise QuoteError(
            f"You can order at most {product.max_order_quantity} of this item.",
            code="max_quantity_exceeded",
            details={"max": product.max_order_quantity},
        )
    line = line_from_variant(variant, quantity)
    pricing = price_lines([line], user=user)
    totals, offers = pricing.totals, pricing.offers
    next_tier = None
    if line.next_tier:
        min_quantity, price = line.next_tier
        next_tier = {
            "min_quantity": min_quantity,
            "unit_price": _money(price),
            "units_more": min_quantity - quantity,
            "reachable": min_quantity <= product.max_order_quantity,
        }
    stock = selectors.variant_stock_map([variant.pk]).get(variant.pk, 0)
    return {
        "product_id": product.pk,
        "variant_id": variant.pk,
        "sku": variant.sku,
        "options": {o.option_type.slug: o.value.slug for o in variant.option_values.all()},
        "quantity": quantity,
        "mrp": _money(variant.mrp),
        "base_unit_price": _money(variant.price),
        "unit_price": _money(line.unit_price),
        "applied_tier": {"min_quantity": line.tier_min_quantity} if line.tier_min_quantity else None,
        "next_tier": next_tier,
        "price_tiers": tier_rows(variant),
        "line_total": _money(line.line_total),
        "bulk_saving": _money(line.bulk_saving),
        "offer_discount": _money(totals.offer_discount),
        "offers": [{"name": a.offer.name, "badge": a.offer.badge} for a in offers.applied],
        "total": _money(totals.subtotal - totals.offer_discount),
        "savings_vs_mrp": _money(totals.savings_vs_mrp),
        "stock_status": selectors.stock_status(stock),
        "within_stock": stock >= quantity,
        "max_order_quantity": product.max_order_quantity,
        "note": "Preview. The cart and checkout confirm the final price, delivery fee and offers.",
    }
