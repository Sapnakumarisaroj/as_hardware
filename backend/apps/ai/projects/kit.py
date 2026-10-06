"""Kits: material needs → real catalogue lines → one priced, delivery-checked cart.

Shared by the project builder (Phase 19, saved `ProjectItem`s) and Quantity AI (Phase 20, unsaved rows).

- **Products** come from the shop's own search (`catalog_match.find_products`, the listing's search
  understanding + the Phase 13 backend), trying the need's search words in order and taking only a match
  on every word. No match = the line says "not found in our catalogue"; nothing is invented.
- **Packs**: each active variant's pack size is read from its name, option values, size specifications or
  the product name ("4 L", "20 kg", "Pack of 100", "20 m", "Box (21.5 sq ft)"), and `quantity.packs`
  chooses the combination of packs (e.g. 1 × 4 L + 1 × 1 L) by the configured rule, with the reason.
- **Price, offers and delivery**: the whole kit goes through `orders.pricing.price_lines` (tier prices,
  automatic offers across the kit, coupon, free-delivery rules and the zone fee) and
  `delivery.plan_fulfillment` (stores, stock, split shipments, ETA) — the same engines as the cart and
  checkout. The cart prices it again when the customer adds it.
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
from ..quantity import packs as P
from ..services.catalog_match import find_products, variant_options
from .templates import Need, say

NUMBER = r"(\d+(?:\.\d+)?)"
SIZE_PATTERNS: dict[str, tuple[tuple[str, float], ...]] = {
    "l": ((rf"{NUMBER}\s*(?:l|ltr|litres?|liters?)(?![a-z])", 1), (rf"{NUMBER}\s*ml(?![a-z])", 0.001)),
    "kg": ((rf"{NUMBER}\s*kg(?![a-z])", 1), (rf"{NUMBER}\s*(?:g|gm|grams?)(?![a-z])", 0.001)),
    "m": ((rf"{NUMBER}\s*(?:m|mtr|metres?|meters?)(?![a-z])", 1),),
    "pcs": (
        (r"(?:pack|box|set|bag)\s+of\s+(\d+)", 1),
        (r"(\d+)\s*(?:pcs|pieces|nos)(?![a-z])", 1),
    ),
    "sqft": ((rf"{NUMBER}\s*(?:sq\.?\s*ft|sqft)", 1), (rf"{NUMBER}\s*(?:sq\.?\s*m|sqm)(?![a-z])", 10.7639)),
    "cft": ((rf"{NUMBER}\s*(?:cft|cu\.?\s*ft)", 1),),
}
SIZE_SPEC_KEYS = {
    "volume", "weight", "length", "pack-size", "net-quantity", "quantity", "box-coverage", "coverage-per-box",
}  # fmt: skip
# A product sold by the litre / kg / metre is its own pack of one unit.
UNIT_OF_PRODUCT = {"l": "l", "kg": "kg", "m": "m"}
ALTERNATIVES = 3
MAX_ITEMS = 40
PART = "~"  # material_key of a second pack size of the same material: "primer~2"


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
    parts: list  # quantity.packs.Part
    query: str
    alternatives: list[int] = field(default_factory=list)
    explanation: str = ""
    options: list[dict] = field(default_factory=list)
    covers: float | None = None

    @property
    def size_known(self) -> bool:
        return all(p.size is not None for p in self.parts)


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


def _narrow(variants: list, *, hint: str = "", params: dict | None = None) -> list:
    """Size words the search understood ("25 kg") and the need's hint ("1.5 sq mm") narrow the choice;
    when no variant fits them, all stay."""
    wanted = {k[len("opt_") :]: v for k, v in (params or {}).items() if k.startswith("opt_")}
    if wanted:
        variants = [v for v in variants if all(variant_options(v).get(t) == x for t, x in wanted.items())] or variants
    if hint:
        variants = [v for v in variants if _hint_matches(v, hint)] or variants
    return variants


def choose_packs(product, variants: list, amount: float, unit: str, *, hint: str = "", params: dict | None = None):
    variants = _narrow(variants, hint=hint, params=params)
    if not variants:
        return None
    stock = selectors.variant_stock_map([v.pk for v in variants])
    options = [(v, pack_amount(product, v, unit)) for v in variants]
    return P.optimise(options, amount, unit, stock=stock, limit=product.max_order_quantity)


WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def _words(text: str) -> set[str]:
    out = set()
    for word in WORD.findall((text or "").lower()):
        out.add(word)
        if len(word) > 3 and word.endswith("es"):
            out.add(word[:-2])
        if len(word) > 2 and word.endswith("s"):
            out.add(word[:-1])
    return out


def names_the_need(product, variants: list, term: str, avoid: tuple[str, ...] = ()) -> bool:
    """Every word of the need's search term is a whole word of the product's name, tags, category or
    variants ("sand" is not "sandpaper"), and none of the need's excluded words is ("tiles" ≠ "tile adhesive")."""
    texts = [product.name, " ".join(product.tags or []), product.category.name]
    if product.subcategory_id:
        texts.append(product.subcategory.name)
    for variant in variants:
        texts.append(variant.name or "")
        texts += [o.value.value for o in variant.option_values.all()]
    have = _words(" ".join(texts))
    if any(word in _words(product.name) for word in avoid):
        return False
    return all(word in have for word in _words(term) - {"x", "×"})


def pick_for(need: Need, *, prefer: dict | None = None) -> Pick | None:
    """`prefer`: size words from the customer's own sentence ("50 kg cement for plastering"), as listing
    option filters; they win over the need's hint when the product has such a variant."""
    for term in need.search:
        for query in ([f"{term} {need.hint}"] if need.hint else []) + [term]:
            match = find_products(query, limit=1 + ALTERNATIVES)
            if match.quality != "exact" or not match.products:
                continue
            product = match.products[0]
            variants = _variants(product.pk)
            if not names_the_need(product, variants, term, need.avoid):
                continue
            if prefer:
                variants = _narrow(variants, params=prefer)
            choice = choose_packs(product, variants, need.amount, need.unit, hint=need.hint, params=match.params)
            if choice is None:
                continue
            return Pick(
                product,
                choice.parts,
                query,
                [p.pk for p in match.products[1:]],
                choice.explanation,
                choice.options,
                choice.covers,
            )
    return None


# --- Kit lines (saved or not) ----------------------------------------------------------------------------


def steps_payload(need: Need, language: str) -> list[dict]:
    return [{"label": say(label, language), "value": value} for label, value in need.steps]


def need_lines(needs: list[Need], language: str, *, prefer: dict | None = None) -> list[dict]:
    """One line per pack size chosen for each need (most needs: one), not yet saved anywhere."""
    lines = []
    for order, need in enumerate(needs[:MAX_ITEMS]):
        pick = pick_for(need, prefer=prefer)
        details = {
            "need_amount": round(need.amount, 2),
            "need_unit": need.unit,
            "note": say(need.note, language) if need.note else "",
            "steps": steps_payload(need, language),
            "search": list(need.search),
            "hint": need.hint,
        }
        common = {
            "label": say(need.label, language)[:150],
            "rationale": say(need.reason, language)[:300],
            "is_optional": need.optional,
            "is_estimate": need.estimate,
            "sort_order": order * 10,
        }
        if pick is None:
            details["status"] = "not_found"
            lines.append(
                {
                    **common,
                    "material_key": need.key,
                    "variant": None,
                    "quantity": max(1, math.ceil(round(need.amount, 6))),
                    "unit": need.unit,
                    "included": False,
                    "details": details,
                }
            )
            continue
        details.update(
            status="found",
            product_id=pick.product.pk,
            query=pick.query,
            alternatives=pick.alternatives,
            size_known=pick.size_known or need.unit == "pcs",
            pack_explanation=pick.explanation,
            pack_options=pick.options,
            covers=round(pick.covers, 2) if pick.covers is not None else None,
            suggested=[{"variant_id": p.variant.pk, "quantity": p.count} for p in pick.parts],
        )
        for index, part in enumerate(pick.parts):
            key = need.key if index == 0 else f"{need.key}{PART}{index + 1}"
            part_details = {
                **details,
                "pack_amount": part.size,
                "suggested_variant_id": part.variant.pk,
                "suggested_quantity": part.count,
            }
            lines.append(
                {
                    **common,
                    "material_key": key,
                    "variant": part.variant,
                    "quantity": part.count,
                    "unit": pick.product.unit,
                    "included": not need.optional,
                    "details": part_details,
                    "sort_order": order * 10 + index,
                }
            )
    return lines


def base_key(material_key: str) -> str:
    return material_key.split(PART)[0]


def build_items(project: Project, needs: list[Need], language: str) -> None:
    """Replace the suggested lines with fresh ones for these needs. Lines the customer changed keep their
    product, quantity and tick (with the new suggestion shown next to them); products the customer added
    stay; suggestions for materials no longer needed go."""
    existing = list(project.items.all())
    changed = {base_key(i.material_key) for i in existing if i.customer_set and not i.material_key.startswith("extra-")}
    by_key = {i.material_key: i for i in existing}
    keep = {i.material_key for i in existing if i.material_key.startswith("extra-")}
    for line in need_lines(needs, language):
        key = line["material_key"]
        if base_key(key) in changed:
            # the customer's own choice stays; its details (need, steps, suggestion) follow the new answers
            if key != base_key(key):
                continue  # the suggestion's other pack sizes are described by its first line
            for item in existing:
                if base_key(item.material_key) == base_key(key) and item.customer_set:
                    for name in ("label", "rationale", "is_optional", "is_estimate", "sort_order"):
                        setattr(item, name, line[name])
                    own = {k: item.details.get(k) for k in ("pack_amount", "product_id") if k in item.details}
                    item.details = {**line["details"], **own}
                    item.save()
                    keep.add(item.material_key)
            continue
        item = by_key.get(key) or ProjectItem(project=project, material_key=key)
        item.variant = line["variant"]
        item.quantity = Decimal(line["quantity"])
        for name in ("label", "rationale", "is_optional", "is_estimate", "sort_order", "unit", "included", "details"):
            setattr(item, name, line[name])
        item.customer_set = False
        item.save()
        keep.add(key)
    project.items.exclude(material_key__in=keep).delete()


def add_extra(project: Project, variant_id: int, quantity: int) -> ProjectItem:
    """A product the customer adds to the kit themselves."""
    variant = carts._purchasable_variant(variant_id)
    if project.items.count() >= MAX_ITEMS:
        raise KitError(f"A project can hold at most {MAX_ITEMS} items.", code="too_many_items")
    number = 1 + max(
        [
            int(k.split("-")[1])
            for k in project.items.filter(material_key__startswith="extra-").values_list("material_key", flat=True)
            if k.split("-")[1].isdigit()
        ]
        or [0]
    )
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
        sort_order=10_000 + number,
        details={"status": "found", "product_id": variant.product_id, "added_by_customer": True},
    )


def regather(details: dict, variant) -> tuple[int, float | None]:
    """A different product or pack for the same need: enough packs of it to cover the whole need."""
    size = pack_amount(variant.product, variant, details.get("need_unit") or "pcs")
    if details.get("need_amount") and details.get("need_unit"):
        return packs_for(float(details["need_amount"]), size), size
    return 1, size


def change_item(item: ProjectItem, *, variant_id=None, quantity=None, included=None) -> ProjectItem:
    if variant_id is not None:
        variant = carts._purchasable_variant(variant_id)
        item.variant = variant
        item.unit = variant.product.unit
        item.details = {**item.details, "status": "found", "product_id": variant.product_id}
        if quantity is None and item.details.get("need_amount"):
            count, size = regather(item.details, variant)
            item.quantity = Decimal(count)
            item.details["pack_amount"] = size
        if not item.material_key.startswith("extra-"):
            # one product now covers the need: the other suggested pack sizes of it go
            ProjectItem.objects.filter(
                project_id=item.project_id,
                material_key__startswith=f"{base_key(item.material_key)}{PART}",
                customer_set=False,
            ).exclude(pk=item.pk).delete()
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

    signed_in = user is not None and getattr(user, "is_authenticated", False)
    if address_id and signed_in:
        address = Address.objects.filter(pk=address_id, user=user).first()
        if address is None:
            raise KitError("Choose one of your saved addresses.", code="address_not_found")
        return resolve_location(address=address), address.postal_code
    if postal_code:
        return resolve_location(postal_code=postal_code), postal_code
    if signed_in:
        address = Address.objects.filter(user=user).order_by("-is_default", "-updated_at").first()
        if address is not None:
            return resolve_location(address=address), address.postal_code
    return None, ""


def stock_status(stock: int, quantity: int) -> str:
    """What a customer may see: enough, only some (limited), none."""
    if stock <= 0:
        return "unavailable"
    return "available" if stock >= quantity else "limited"


@dataclass
class Row:
    """A kit line to price: a saved ProjectItem or an unsaved Quantity AI line."""

    id: object  # item pk, or the material key for unsaved lines
    material_key: str
    label: str
    variant: object | None
    quantity: int
    included: bool
    details: dict
    rationale: str = ""
    unit: str = ""
    is_optional: bool = False
    is_estimate: bool = True
    customer_set: bool = False


def rows_from_items(items) -> list[Row]:
    return [
        Row(
            i.pk,
            i.material_key,
            i.label,
            i.variant,
            int(i.quantity),
            i.included,
            i.details,
            i.rationale,
            i.unit,
            i.is_optional,
            i.is_estimate,
            i.customer_set,
        )
        for i in items
    ]


def price_rows(
    rows: list[Row], *, user, postal_code: str = "", address_id: int | None = None, coupon_code: str = ""
) -> dict:
    """Every ticked line priced as one cart, stock and delivery checked. Read-only."""
    from apps.delivery.fulfillment import plan_fulfillment
    from apps.offers.services import get_valid_coupon

    variant_ids = [r.variant.pk for r in rows if r.variant is not None]
    live = set(selectors.product_queryset().filter(variants__pk__in=variant_ids).values_list("variants__pk", flat=True))
    stock = selectors.variant_stock_map(variant_ids)
    issues, priced, lines, requirements = [], [], [], {}

    for row in rows:
        variant, quantity = row.variant, row.quantity
        problem = ""
        if variant is None:
            problem = "not_found"
        elif not variant.is_active or variant.pk not in live:
            problem = "unavailable"
        elif quantity > variant.product.max_order_quantity:
            problem = "too_many"
        elif stock.get(variant.pk, 0) < quantity:
            problem = "short_stock"
        line = None
        if variant is not None and problem not in ("not_found", "unavailable"):
            line = line_from_variant(variant, quantity)
            if row.included and not problem:
                lines.append(line)
                requirements[variant.pk] = requirements.get(variant.pk, 0) + quantity
        if row.included and problem:
            name = variant.product.name if variant else row.label
            issues.append({"item_id": row.id, "code": problem, "message": _problem_text(problem, name, variant, stock)})
        priced.append((row, line, problem))

    location, used_pin = _location(user, postal_code=postal_code, address_id=address_id)
    plan = plan_fulfillment(requirements, location) if requirements else None
    fee_rule = plan.fee_rule if plan and plan.deliverable and plan.location else None
    signed_in = user is not None and getattr(user, "is_authenticated", False)
    pricing_user = user if signed_in else None
    pricing = price_lines(lines, fee_rule=fee_rule, user=pricing_user)
    coupon_info = None
    if coupon_code.strip() and lines:
        if not signed_in:
            coupon_info = {"code": coupon_code.strip().upper(), "applied": False, "message": "Sign in to use a coupon."}
        else:
            try:
                coupon = get_valid_coupon(coupon_code, user)
                pricing = price_lines(lines, coupon=coupon, fee_rule=fee_rule, user=user)
                coupon_info = {"code": coupon.code, "applied": True, "message": ""}
            except ServiceError as exc:
                coupon_info = {"code": coupon_code.strip().upper(), "applied": False, "message": str(exc.detail)}
    totals, offers = pricing.totals, pricing.offers
    delivery = quote_from_plan(plan, totals, fee_rule)
    if plan is not None and not plan.deliverable:
        issues.append({"item_id": None, "code": "not_deliverable", "message": plan.message})

    out_items = []
    for row, line, problem in priced:
        details = row.details
        discount = (
            offers.line_discounts.get(row.variant.pk, Decimal("0"))
            if row.variant and row.included and line
            else Decimal("0")
        )
        available = stock.get(row.variant.pk, 0) if row.variant else 0
        out_items.append(
            {
                "id": row.id,
                "material_key": row.material_key,
                "base_key": base_key(row.material_key),
                "label": row.label,
                "rationale": row.rationale,
                "note": details.get("note", ""),
                "status": details.get("status", "found"),
                "need": {"amount": details.get("need_amount"), "unit": details.get("need_unit", "")},
                "steps": details.get("steps", []),
                "pack_amount": details.get("pack_amount"),
                "size_known": details.get("size_known", True),
                "pack_explanation": details.get("pack_explanation", ""),
                "pack_options": details.get("pack_options", []),
                "covers": details.get("covers"),
                "suggested": {
                    "variant_id": details.get("suggested_variant_id"),
                    "quantity": details.get("suggested_quantity"),
                },
                "suggested_parts": details.get("suggested", []),
                "alternatives": details.get("alternatives", []),
                "added_by_customer": details.get("added_by_customer", False),
                "is_optional": row.is_optional,
                "is_estimate": row.is_estimate,
                "included": row.included,
                "customer_set": row.customer_set,
                "quantity": row.quantity,
                "unit": row.unit,
                "product_id": row.variant.product_id if row.variant else None,
                "variant": _variant_data(row.variant) if row.variant else None,
                "problem": problem,
                "stock_status": stock_status(available, row.quantity) if row.variant else "unavailable",
                "stock_available": available if row.variant and available < row.quantity else None,
                "price": _line_data(line, discount, row.variant.product.max_order_quantity) if line else None,
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
            "coupon_discount": _money(totals.coupon_discount),
            "delivery_fee": _money(totals.delivery_fee),
            "tax_included": _money(totals.tax_total),
            "grand_total": _money(totals.grand_total),
            "savings_vs_mrp": _money(totals.savings_vs_mrp),
        },
        "offers": [{"name": a.offer.name, "discount": _money(a.discount)} for a in offers.applied],
        "free_delivery_offer": offers.free_delivery.offer.name if offers.free_delivery else "",
        "offers_in_reach": [
            {
                "name": m.offer.name,
                "description": m.offer.description,
                "min_order_value": _money(m.offer.min_order_value or 0),
            }
            for m in offers.missed
        ],
        "coupon": coupon_info,
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


def quote_kit(project: Project, *, user, postal_code: str = "", address_id: int | None = None) -> dict:
    items = project.items.select_related("variant__product").prefetch_related(
        "variant__option_values__option_type", "variant__option_values__value", "variant__price_tiers"
    )
    return price_rows(rows_from_items(items), user=user, postal_code=postal_code, address_id=address_id)


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


def _line_data(line, offer_discount, max_quantity: int) -> dict:
    return {
        "unit_price": _money(line.unit_price),
        "base_unit_price": _money(line.base_unit_price or line.unit_price),
        "applied_tier": {"min_quantity": line.tier_min_quantity} if line.tier_min_quantity else None,
        "next_tier": (
            {
                "min_quantity": line.next_tier[0],
                "unit_price": _money(line.next_tier[1]),
                "units_more": line.next_tier[0] - line.quantity,
                "reachable": line.next_tier[0] <= max_quantity,
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
def add_lines_to_cart(user, lines: list[tuple[int, int]], *, names: dict | None = None) -> dict:
    """(variant_id, quantity) lines into the customer's cart through the cart service, or nothing: every
    line is checked first (purchasable, order limit, stock including what is already in the cart)."""
    merged: dict[int, int] = {}
    for variant_id, quantity in lines:
        merged[variant_id] = merged.get(variant_id, 0) + int(quantity)
    if not merged:
        raise KitError("Tick at least one item with a product to add.", code="project_empty")
    problems = []
    for variant_id, quantity in merged.items():
        try:
            carts.check_item(user, variant_id, quantity)
        except ServiceError as exc:
            name = (
                (names or {}).get(variant_id)
                or ProductVariant.objects.filter(pk=variant_id).values_list("product__name", flat=True).first()
                or "Item"
            )
            problems.append({"variant_id": variant_id, "code": exc.error_code, "message": f"{name}: {exc.detail}"})
    if problems:
        raise KitError(
            "Some items can't be added. Nothing was added to your cart.",
            code="project_not_addable",
            details={"items": problems},
        )
    for variant_id, quantity in merged.items():
        carts.add_item(user, variant_id, quantity)
    return {"added_lines": len(merged), "added_units": sum(merged.values())}


@transaction.atomic
def add_to_cart(project: Project, *, user) -> dict:
    """All ticked lines of a project into the customer's cart, or nothing."""
    project = Project.objects.select_for_update().get(pk=project.pk)
    items = [i for i in project.items.filter(included=True).select_related("variant__product") if i.variant_id]
    result = add_lines_to_cart(
        user,
        [(i.variant_id, int(i.quantity)) for i in items],
        names={i.variant_id: i.variant.product.name for i in items},
    )
    project.status = Project.Status.ORDERED
    project.save(update_fields=["status", "updated_at"])
    return result
