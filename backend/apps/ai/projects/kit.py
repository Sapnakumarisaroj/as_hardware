"""Project kits (Phase 19): template needs → real catalogue lines → one priced, delivery-checked cart.

- **Products** come from the shop's own search (`catalog_match.find_products`, the listing's search
  understanding + the Phase 13 backend), trying the need's search words in order and taking only a match
  on every word. No match = the line says "not found in our catalogue"; nothing is invented.
- **Pack and variant**: the need is in natural units (5.3 litres, 18 plugs); each active variant's pack
  size is read from its name, option values, size specifications or the product name ("4 L", "20 kg",
  "Pack of 100", "20 m"). The variant with the lowest cost for the packs needed (bulk tier prices included,
  stocked variants first) wins; the customer can change it.
- **Price, offers and delivery**: the whole kit goes through `orders.pricing.price_lines` (tier prices,
  automatic offers across the kit, free-delivery rules and the zone fee) and `delivery.plan_fulfillment`
  (stores, stock, split shipments, ETA) — the same engines as the cart and checkout. The cart prices it
  again when the customer adds it.
"""

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from apps.carts import services as carts
from apps.catalog import selectors
from apps.catalog.models import ProductVariant
from apps.core.exceptions import ServiceError
from apps.orders.checkout import quote_from_plan
from apps.orders.pricing import line_from_variant, price_lines

from ..models import Project, ProjectItem
from ..services.catalog_match import find_products, variant_options
from .templates import Need, say

NUMBER = r"(\d+(?:\.\d+)?)"
SIZE_PATTERNS: dict[str, tuple[tuple[str, float], ...]] = {
    "l": ((rf"{NUMBER}\s*(?:l|ltr|litres?|liters?)(?![a-z])", 1), (rf"{NUMBER}\s*ml(?![a-z])", 0.001)),
    "kg": ((rf"{NUMBER}\s*kg(?![a-z])", 1), (rf"{NUMBER}\s*(?:g|gm|grams?)(?![a-z])", 0.001)),
    "m": ((rf"{NUMBER}\s*(?:m|mtr|metres?|meters?)(?![a-z])", 1),),
    "pcs": ((r"pack\s+of\s+(\d+)", 1), (r"set\s+of\s+(\d+)", 1), (r"(\d+)\s*(?:pcs|pieces|nos)(?![a-z])", 1)),
}
SIZE_SPEC_KEYS = {"volume", "weight", "length", "pack-size", "net-quantity", "quantity"}
# A product sold by the litre / kg / metre is its own pack of one unit.
UNIT_OF_PRODUCT = {"l": "l", "kg": "kg", "m": "m"}
ALTERNATIVES = 3
MAX_ITEMS = 40


class KitError(ServiceError):
    default_code = "project_kit_error"


# --- Pack sizes ----------------------------------------------------------------------------------------


def _size_texts(product, variant) -> list[str]:
    texts = [variant.name or ""]
    texts += [o.value.value for o in variant.option_values.all()]
    texts += [f"{s.value} {s.unit}" for s in product.specifications.all() if s.key in SIZE_SPEC_KEYS]
    texts.append(product.name)
    return [text for text in texts if text]


def pack_amount(product, variant, unit: str) -> float | None:
    """How much of `unit` one purchasable unit of this variant holds; None when the listing doesn't say."""
    for text in _size_texts(product, variant):
        for pattern, factor in SIZE_PATTERNS.get(unit, ()):
            if match := re.search(pattern, text, re.IGNORECASE):
                value = float(match.group(1)) * factor
                if value > 0:
                    return value
    if UNIT_OF_PRODUCT.get(product.unit) == unit:
        return 1.0
    if unit == "pcs":
        return 1.0  # one piece, set or bag per need unit
    return None


def packs_for(amount: float, size: float | None) -> int:
    if size is None:
        return 1
    return max(1, math.ceil(round(amount / size, 6)))


# --- Choosing products ---------------------------------------------------------------------------------


@dataclass
class Pick:
    product: object
    variant: object
    packs: int
    size: float | None
    query: str
    alternatives: list[int] = field(default_factory=list)


def _variants(product_id: int) -> list:
    return list(
        ProductVariant.objects.filter(product_id=product_id, is_active=True)
        .select_related("product")
        .prefetch_related("option_values__option_type", "option_values__value", "price_tiers")
        .order_by("pk")
    )


def _hint_matches(variant, hint: str) -> bool:
    words = " ".join([variant.name, *[o.value.value for o in variant.option_values.all()]]).lower()
    return hint.lower() in words.replace(" ", "") or hint.lower() in words


def best_variant(product, variants: list, amount: float, unit: str, *, hint: str = "", params: dict | None = None):
    """(variant, packs, size) costing least for `amount` of `unit`; enough stock and within the order
    limit first. Size words the search understood ("25 kg") and the need's hint narrow the choice."""
    if not variants:
        return None
    wanted = {k[len("opt_") :]: v for k, v in (params or {}).items() if k.startswith("opt_")}
    if wanted:
        variants = [v for v in variants if all(variant_options(v).get(t) == x for t, x in wanted.items())] or variants
    if hint:
        variants = [v for v in variants if _hint_matches(v, hint)] or variants
    stock = selectors.variant_stock_map([v.pk for v in variants])
    best, best_key = None, None
    for variant in variants:
        size = pack_amount(product, variant, unit)
        packs = packs_for(amount, size)
        cost = line_from_variant(variant, packs).line_total
        key = (
            packs > product.max_order_quantity,
            stock.get(variant.pk, 0) < packs,
            cost,
            packs,
            not variant.is_default,
        )
        if best_key is None or key < best_key:
            best, best_key = (variant, packs, size), key
    return best


def pick_for(need: Need) -> Pick | None:
    for term in need.search:
        for query in ([f"{term} {need.hint}"] if need.hint else []) + [term]:
            match = find_products(query, limit=1 + ALTERNATIVES)
            if match.quality != "exact" or not match.products:
                continue
            product = match.products[0]
            chosen = best_variant(
                product, _variants(product.pk), need.amount, need.unit, hint=need.hint, params=match.params
            )
            if chosen is None:
                continue
            variant, packs, size = chosen
            return Pick(product, variant, packs, size, query, [p.pk for p in match.products[1:]])
    return None


# --- Building the kit ----------------------------------------------------------------------------------


def _need_details(need: Need, language: str) -> dict:
    return {
        "need_amount": round(need.amount, 2),
        "need_unit": need.unit,
        "note": say(need.note, language) if need.note else "",
        "search": list(need.search),
        "hint": need.hint,
    }


def build_items(project: Project, needs: list[Need], language: str) -> None:
    """Replace the suggested lines with fresh ones for these needs. Lines the customer changed keep their
    product, quantity and tick (with the new suggestion shown next to them); products the customer added
    stay; suggestions for materials no longer needed go."""
    existing = {item.material_key: item for item in project.items.all()}
    keep = {key for key, item in existing.items() if key.startswith("extra-")}
    for order, need in enumerate(needs[:MAX_ITEMS]):
        item = existing.get(need.key)
        details = _need_details(need, language)
        pick = pick_for(need)
        if pick is not None:
            details.update(
                status="found",
                product_id=pick.product.pk,
                pack_amount=pick.size,
                query=pick.query,
                alternatives=pick.alternatives,
                suggested_variant_id=pick.variant.pk,
                suggested_quantity=pick.packs,
                size_known=pick.size is not None or need.unit == "pcs",
            )
        else:
            details.update(status="not_found")
        fields = {
            "label": say(need.label, language)[:150],
            "rationale": say(need.reason, language)[:300],
            "is_optional": need.optional,
            "is_estimate": need.estimate,
            "sort_order": order,
        }
        if item is not None and item.customer_set:
            for name, value in fields.items():
                setattr(item, name, value)
            item.details = {**item.details, **{k: v for k, v in details.items() if k not in ("product_id",)}}
            item.save()
        else:
            if item is None:
                item = ProjectItem(project=project, material_key=need.key)
            for name, value in fields.items():
                setattr(item, name, value)
            item.variant = pick.variant if pick else None
            item.quantity = Decimal(pick.packs if pick else max(1, math.ceil(need.amount)))
            item.unit = pick.product.unit if pick else need.unit
            item.included = not need.optional and pick is not None
            item.details = details
            item.save()
        keep.add(need.key)
    project.items.exclude(material_key__in=keep).delete()


def add_extra(project: Project, variant_id: int, quantity: int) -> ProjectItem:
    """A product the customer adds to the kit themselves."""
    variant = carts._purchasable_variant(variant_id)
    if project.items.count() >= MAX_ITEMS:
        raise KitError(f"A project can hold at most {MAX_ITEMS} items.", code="too_many_items")
    number = 1 + max([int(k.split("-")[1]) for k in project.items.filter(material_key__startswith="extra-")
                      .values_list("material_key", flat=True) if k.split("-")[1].isdigit()] or [0])  # fmt: skip
    return ProjectItem.objects.create(
        project=project,
        material_key=f"extra-{number}",
        variant=variant,
        label=variant.product.name[:150],
        quantity=Decimal(quantity),
        unit=variant.product.unit,
        is_estimate=False,
        included=True,
        customer_set=True,
        sort_order=1000 + number,
        details={"status": "found", "product_id": variant.product_id, "added_by_customer": True},
    )


def change_item(item: ProjectItem, *, variant_id=None, quantity=None, included=None) -> ProjectItem:
    if variant_id is not None:
        variant = carts._purchasable_variant(variant_id)
        item.variant = variant
        item.unit = variant.product.unit
        item.details = {**item.details, "status": "found", "product_id": variant.product_id}
        if quantity is None and item.details.get("need_amount") and item.details.get("need_unit"):
            # a different pack size: buy enough of it for the same need
            size = pack_amount(variant.product, variant, item.details["need_unit"])
            item.quantity = Decimal(packs_for(float(item.details["need_amount"]), size))
            item.details["pack_amount"] = size
    if quantity is not None:
        item.quantity = Decimal(quantity)
    if included is not None:
        if included and item.variant_id is None:
            raise KitError("Choose a product for this item first.", code="no_product")
        item.included = included
    item.customer_set = True
    item.save()
    return item


# --- Pricing the kit -----------------------------------------------------------------------------------


def _money(value) -> str:
    return f"{Decimal(value):.2f}"


def _location(user, *, postal_code: str = "", address_id: int | None = None):
    from apps.accounts.models import Address
    from apps.delivery.locations import resolve_location

    if address_id:
        address = Address.objects.filter(pk=address_id, user=user).first()
        if address is None:
            raise KitError("Choose one of your saved addresses.", code="address_not_found")
        return resolve_location(address=address), address.postal_code
    if postal_code:
        return resolve_location(postal_code=postal_code), postal_code
    address = Address.objects.filter(user=user).order_by("-is_default", "-updated_at").first()
    if address is not None:
        return resolve_location(address=address), address.postal_code
    return None, ""


def quote_kit(project: Project, *, user, postal_code: str = "", address_id: int | None = None) -> dict:
    """Every line priced as one cart, stock and delivery checked. Read-only."""
    from apps.delivery.fulfillment import plan_fulfillment

    items = list(
        project.items.select_related("variant__product").prefetch_related(
            "variant__option_values__option_type", "variant__option_values__value", "variant__price_tiers"
        )
    )
    variant_ids = [i.variant_id for i in items if i.variant_id]
    live = set(selectors.product_queryset().filter(variants__pk__in=variant_ids).values_list("variants__pk", flat=True))
    stock = selectors.variant_stock_map(variant_ids)
    issues, rows, lines, requirements = [], [], [], {}

    for item in items:
        variant = item.variant
        row = {"id": item.pk, "problem": ""}
        quantity = int(item.quantity)
        if variant is None:
            row["problem"] = "not_found"
        elif not variant.is_active or variant.pk not in live:
            row["problem"] = "unavailable"
        elif quantity > variant.product.max_order_quantity:
            row["problem"] = "too_many"
        elif stock.get(variant.pk, 0) < quantity:
            row["problem"] = "short_stock"
        if variant is not None and not row["problem"]:
            line = line_from_variant(variant, quantity)
            row["line"] = line
            if item.included:
                lines.append(line)
                requirements[variant.pk] = requirements.get(variant.pk, 0) + quantity
        if item.included and row["problem"]:
            name = variant.product.name if variant else item.label
            issues.append(
                {
                    "item_id": item.pk,
                    "code": row["problem"],
                    "message": _problem_text(row["problem"], name, variant, stock),
                }
            )
        row["stock"] = stock.get(variant.pk, 0) if variant else 0
        rows.append((item, row))

    location, used_pin = _location(user, postal_code=postal_code, address_id=address_id)
    plan = plan_fulfillment(requirements, location) if requirements else None
    fee_rule = plan.fee_rule if plan and plan.deliverable and plan.location else None
    pricing = price_lines(lines, fee_rule=fee_rule, user=user)
    totals, offers = pricing.totals, pricing.offers
    delivery = quote_from_plan(plan, totals, fee_rule)
    if plan is not None and not plan.deliverable:
        issues.append({"item_id": None, "code": "not_deliverable", "message": plan.message})

    out_items = []
    for item, row in rows:
        line = row.get("line")
        discount = offers.line_discounts.get(item.variant_id, Decimal("0")) if item.included and line else Decimal("0")
        out_items.append(
            {
                "id": item.pk,
                "material_key": item.material_key,
                "label": item.label,
                "rationale": item.rationale,
                "note": item.details.get("note", ""),
                "status": item.details.get("status", "found"),
                "need": {"amount": item.details.get("need_amount"), "unit": item.details.get("need_unit", "")},
                "pack_amount": item.details.get("pack_amount"),
                "size_known": item.details.get("size_known", True),
                "suggested": {
                    "variant_id": item.details.get("suggested_variant_id"),
                    "quantity": item.details.get("suggested_quantity"),
                },
                "alternatives": item.details.get("alternatives", []),
                "added_by_customer": item.details.get("added_by_customer", False),
                "is_optional": item.is_optional,
                "is_estimate": item.is_estimate,
                "included": item.included,
                "customer_set": item.customer_set,
                "quantity": int(item.quantity),
                "unit": item.unit,
                "product_id": item.variant.product_id if item.variant else None,
                "variant": _variant_data(item.variant) if item.variant else None,
                "problem": row["problem"],
                "stock_available": row["stock"],
                "price": _line_data(line, discount) if line else None,
            }
        )

    included = [r for r in out_items if r["included"]]
    return {
        "items": out_items,
        "postal_code": used_pin,
        "totals": {
            "item_count": len(lines),
            "mrp_total": _money(totals.mrp_total),
            "subtotal": _money(totals.subtotal),
            "bulk_savings": _money(totals.bulk_savings),
            "offer_discount": _money(totals.offer_discount),
            "delivery_fee": _money(totals.delivery_fee),
            "tax_included": _money(totals.tax_total),
            "grand_total": _money(totals.grand_total),
            "savings_vs_mrp": _money(totals.savings_vs_mrp),
        },
        "offers": [{"name": a.offer.name, "discount": _money(a.discount)} for a in offers.applied],
        "offers_in_reach": [
            {
                "name": m.offer.name,
                "description": m.offer.description,
                "min_order_value": _money(m.offer.min_order_value or 0),
            }
            for m in offers.missed
        ],
        "delivery": {
            "checked": location is not None,
            "available": delivery.available,
            "message": delivery.message,
            "label": delivery.label,
            "delivery_type": delivery.delivery_type,
            "eta_minutes": delivery.eta_minutes,
            "fee": _money(delivery.fee),
            "free_delivery_reason": delivery.free_delivery_reason,
            "amount_to_free_delivery": _money(delivery.amount_to_free_delivery),
            "free_delivery_hint": delivery.free_delivery_hint,
            "shipments": delivery.shipments,
        },
        "issues": issues,
        "can_add_to_cart": bool(lines) and not issues,
        "not_found_count": sum(1 for r in out_items if r["status"] == "not_found"),
        "included_count": len(included),
    }


def _problem_text(code: str, name: str, variant, stock: dict) -> str:
    if code == "not_found":
        return f"{name}: not found in our catalogue. Untick it or choose a product."
    if code == "unavailable":
        return f"{name} is no longer available. Choose another product or untick it."
    if code == "too_many":
        return f"You can order at most {variant.product.max_order_quantity} of {name}."
    available = stock.get(variant.pk, 0)
    return f"Only {available} of {name} in stock." if available else f"{name} is out of stock."


def _variant_data(variant) -> dict:
    return {
        "id": variant.pk,
        "sku": variant.sku,
        "name": variant.name,
        "options": [{"type": o.option_type.name, "value": o.value.value} for o in variant.option_values.all()],
        "price": _money(variant.price),
        "mrp": _money(variant.mrp),
    }


def _line_data(line, offer_discount) -> dict:
    return {
        "unit_price": _money(line.unit_price),
        "base_unit_price": _money(line.base_unit_price or line.unit_price),
        "applied_tier": {"min_quantity": line.tier_min_quantity} if line.tier_min_quantity else None,
        "next_tier": (
            {
                "min_quantity": line.next_tier[0],
                "unit_price": _money(line.next_tier[1]),
                "units_more": line.next_tier[0] - line.quantity,
            }
            if line.next_tier
            else None
        ),
        "line_total": _money(line.line_total),
        "bulk_saving": _money(line.bulk_saving),
        "offer_discount": _money(offer_discount),
    }


# --- Into the cart -------------------------------------------------------------------------------------


@transaction.atomic
def add_to_cart(project: Project, *, user) -> dict:
    """All ticked lines into the customer's cart, or nothing: every line is checked first."""
    project = Project.objects.select_for_update().get(pk=project.pk)
    items = [i for i in project.items.filter(included=True).select_related("variant__product") if i.variant_id]
    if not items:
        raise KitError("Tick at least one item with a product to add.", code="project_empty")
    merged: dict[int, int] = {}
    for item in items:
        merged[item.variant_id] = merged.get(item.variant_id, 0) + int(item.quantity)
    problems = []
    for variant_id, quantity in merged.items():
        try:
            carts.check_item(user, variant_id, quantity)
        except ServiceError as exc:
            name = next(i.variant.product.name for i in items if i.variant_id == variant_id)
            problems.append({"variant_id": variant_id, "code": exc.error_code, "message": f"{name}: {exc.detail}"})
    if problems:
        raise KitError(
            "Some items can't be added. Nothing was added to your cart.",
            code="project_not_addable",
            details={"items": problems},
        )
    for variant_id, quantity in merged.items():
        carts.add_item(user, variant_id, quantity)
    project.status = Project.Status.ORDERED
    project.save(update_fields=["status", "updated_at"])
    return {"added_lines": len(merged), "added_units": sum(merged.values())}
