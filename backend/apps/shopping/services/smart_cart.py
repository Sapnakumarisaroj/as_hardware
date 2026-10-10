# ruff: noqa: E501 — messages read better on one line
"""SmartCartService (Phase 22): what's worth telling the customer about their cart, highest value first.

Read-only. It never changes the cart: each suggestion carries an action (add, replace, remove, set the quantity,
apply a bundle, add a kit's missing lines) that the customer confirms on the page, and the cart API then checks it
again.

Sources (no second pricing, stock, offer, delivery or compatibility logic):
- `ai.projects.kit.price_rows` over the cart lines → the pricing engine (tiers, offers, coupon rules, free-delivery
  rules, zone fee), stock, order limits, delivery plan and the Phase 21 compatibility problems;
- `orders.pricing.line_from_variant` (tiers) for every saving shown, `ai.quantity.packs.optimise` for pack sizes;
- `catalog.compatibility` for needed accessories and compatible replacements;
- `RecommendationService` / `co_purchased` (recent orders: support, confidence, lift) for add-ons and cheaper
  equivalents; the shop's links; `cart_rules` (whole-word "needed with" rules, defining specifications, project
  kits); `offers.services.available_coupons`; bundles.

Sections, in this order (each capped, each hidden when empty; a product appears in one section at most, and every
suggestion has a short `reason` from the data): cart warnings, needed with it, cheaper pack size, save with bulk
pricing, better alternatives, complete the set, customers also bought, free delivery opportunity, works with it,
offers and coupons, budget. Demo and real catalogue rows are never mixed.
"""

import math
from decimal import Decimal

from apps.ai.projects import kit
from apps.ai.quantity import packs as pack_optimiser
from apps.carts.models import CartItem
from apps.catalog import selectors
from apps.catalog.compatibility import profiles, rules
from apps.catalog.compatibility.rules import ORDER
from apps.catalog.compatibility.service import CompatibilityService
from apps.catalog.models import Category, ProductRelation, ProductVariant
from apps.orders.pricing import line_from_variant

from . import bundles as bundle_service
from . import cart_rules
from .recommendations import RecommendationService, co_purchased, live

SECTION_LIMIT = 3
ALTERNATIVE_LINES = 10  # cheaper equivalents are looked for on the first 10 lines
CONTEXT_LINES = 5  # accessories, co-purchases and "needed with" rules on the first 5 lines
FREE_DELIVERY_MAX_QUANTITY = 3  # "add 2 of these": more than 3 of one add-on is not a sensible suggestion
# A cart with a product of the first kind usually needs one of the second ("your drill needs bits"); the
# compatibility engine picks one that fits. Other departments: `cart_rules.NEED_RULES`.
NEEDS = {"drill": "drill_bit", "wall_plug": "screw", "screw": "wall_plug"}
TITLES = {
    "warnings": "Cart warnings",
    "needed_with": "Needed with it",
    "packs": "Cheaper pack size",
    "bulk": "Save with bulk pricing",
    "alternatives": "Better alternatives",
    "bundles": "Complete the set",
    "also_bought": "Customers also bought",
    "free_delivery": "Free delivery opportunity",
    "works_with": "Works with it",
    "offers": "Offers and coupons",
    "budget": "Budget",
}
VARIANT_PREFETCH = ("option_values__option_type", "option_values__value", "price_tiers")


def _money(value) -> str:
    return f"{Decimal(value):.2f}"


def _offer_line(variant, quantity: int) -> dict:
    line = line_from_variant(variant, quantity)
    return {"unit_price": _money(line.unit_price), "line_total": _money(line.line_total)}


def _products_of(item) -> set[int]:
    """Products a suggestion puts in front of the customer (for de-duplication across sections)."""
    if item.get("lines"):
        return {line["product_id"] for line in item["lines"]}
    if item.get("bundle"):
        return set(item["bundle"]["missing"])
    return {item["product_id"]} if item.get("product_id") else set()


class SmartCartService:
    def __init__(self):
        self.compat = CompatibilityService()
        self.recs = RecommendationService()
        self._accessory_groups: dict = {}  # (product, variant) → accessory groups, reused within one analysis
        self._verdicts: dict = {}  # (product, variant, other product, other variant) → verdict
        self._checkable: dict = {}  # product id → product loaded for compatibility checks (None: off sale)

    def _accessories(self, item) -> dict:
        key = (item.variant.product_id, item.variant_id)
        if key not in self._accessory_groups:
            self._accessory_groups[key] = self.compat.accessories(*key)["groups"]
        return self._accessory_groups[key]

    def analyze(
        self, user, *, postal_code: str = "", address_id: int | None = None, budget: Decimal | None = None
    ) -> dict:
        items = list(
            CartItem.objects.filter(cart__user=user)
            .select_related("variant__product__category", "variant__product__subcategory")
            .prefetch_related(*(f"variant__{p}" for p in VARIANT_PREFETCH), "variant__product__specifications")
            .order_by("created_at", "id")
        )
        if not items:
            return {"empty": True, "sections": [], "top_actions": [], "titles": TITLES, "summary": None}
        rows = [
            kit.Row(
                item.pk,
                f"cart-{item.pk}",
                item.variant.product.name,
                item.variant,
                item.quantity,
                True,
                {"status": "found", "product_id": item.variant.product_id},
                "",
                item.variant.product.unit,
                False,
                False,
            )  # fmt: skip
            for item in items
        ]
        priced = kit.price_rows(rows, user=user, postal_code=postal_code, address_id=address_id)
        in_cart = {item.variant.product_id for item in items}
        stock = selectors.variant_stock_map([item.variant_id for item in items])
        context = {
            "items": items,
            "priced": priced,
            "in_cart": in_cart,
            "stock": stock,
            "used": set(),  # products already suggested by an earlier section
            # demo/sample rows only for an all-demo cart (development data); a real cart gets real products only
            "demo": all(item.variant.product.is_demo for item in items),
        }

        sections = []
        for key, builder in (
            ("warnings", self._warnings),
            ("needed_with", self._needed_with),
            ("packs", self._packs),
            ("bulk", self._bulk),
            ("alternatives", self._alternatives),
            ("bundles", lambda ctx: self._bundles(ctx) + self._project_kits(ctx)),
            ("also_bought", self._also_bought),
            ("free_delivery", self._free_delivery),
            ("works_with", self._works_with),
            ("offers", lambda ctx: self._offers(ctx, user)),
        ):
            found = builder(context)
            if key not in ("warnings", "offers"):
                found = self._dedupe(found, context)
            if key == "free_delivery" and len(found) < 2:
                found = []  # the gap alone, with nothing relevant that closes it, isn't worth a section
            if found:
                limit = 10 if key == "warnings" else SECTION_LIMIT + (1 if key == "free_delivery" else 0)
                kept = found[:limit]
                if key not in ("warnings", "offers"):
                    for item in kept:
                        context["used"] |= _products_of(item)
                sections.append({"key": key, "title": TITLES[key], "items": kept})
        if budget is not None:
            sections.append({"key": "budget", "title": TITLES["budget"], "items": [self._budget(context, budget)]})
        top = [s for section in sections for s in section["items"] if s.get("action") and s.get("priority", 0) >= 50]
        top.sort(key=lambda s: -s.get("priority", 0))
        totals = priced["totals"]
        return {
            "empty": False,
            "summary": {
                "subtotal": totals["subtotal"],
                "grand_total": totals["grand_total"],
                "bulk_savings": totals["bulk_savings"],
                "offer_discount": totals["offer_discount"],
                "delivery": priced["delivery"],
            },
            "sections": sections,
            "top_actions": top[:3],
            "titles": TITLES,
        }

    @staticmethod
    def _dedupe(found: list[dict], ctx) -> list[dict]:
        """Drop suggestions of a product an earlier section (or an earlier row) already shows. Pack and bulk rows
        of one cart line: the first wins (packs are evaluated first and save more when they apply)."""
        out, seen = [], set(ctx["used"])
        lines_seen = {i.get("cart_item_id") for i in ctx.get("_line_suggestions", [])}
        for item in found:
            products = _products_of(item)
            if item.get("action") in ("set_quantity",) or item.get("type") == "pack_size":
                if item.get("cart_item_id") in lines_seen:
                    continue
                lines_seen.add(item.get("cart_item_id"))
                ctx.setdefault("_line_suggestions", []).append(item)
                out.append(item)
                continue
            if products and products & seen:
                continue
            seen |= products
            out.append(item)
        return out

    # --- Sections -----------------------------------------------------------------------------------------

    def _warnings(self, ctx) -> list[dict]:
        out = []
        for problem in ctx["priced"]["compatibility"]:
            option = (problem.get("options") or [None])[0]
            out.append({
                "type": "incompatible",
                "verdict": problem["verdict"],
                "message": problem["message"],
                "reason": "The compatibility check of the lines in your cart.",
                "cart_item_id": problem["keys"][1],
                "product_id": option["product_id"] if option else None,
                "variant_id": option["variant_id"] if option else None,
                "options": problem.get("options", []),
                "action": "replace" if option else "view",
                "priority": 100 if problem["verdict"] == "NOT_COMPATIBLE" else 70,
            })  # fmt: skip
        by_product: dict[int, list] = {}
        for item in ctx["items"]:
            by_product.setdefault(item.variant.product_id, []).append(item)
        for product_id, same in by_product.items():
            if len(same) > 1:
                names = " and ".join(i.variant.name or i.variant.sku for i in same)
                out.append({"type": "duplicate", "message": f"You have {same[0].variant.product.name} twice ({names}). Remove one if you need only one size.",
                            "reason": "Two lines of the same product.", "cart_item_id": same[-1].pk, "product_id": product_id, "action": "remove", "priority": 40})  # fmt: skip
        kinds: dict[str, list] = {}
        for item in ctx["items"]:
            kinds.setdefault(profiles.kind_of(item.variant.product) or "", []).append(item)
        for kind in ("drill", "drill_bit"):
            group = {i.variant.product_id: i for i in kinds.get(kind, [])}
            if len(group) > 1:
                names = ", ".join(i.variant.product.name for i in group.values())
                out.append(
                    {
                        "type": "redundant",
                        "message": f"Several products of the same type: {names}. Check you need all of them.",
                        "reason": f"All are a {kind.replace('_', ' ')}.",
                        "action": None,
                        "priority": 20,
                    }
                )
        out += self._quantity_mismatch(kinds)
        for issue in ctx["priced"]["issues"]:
            if issue["code"] in ("short_stock", "unavailable", "too_many"):
                out.append(
                    {
                        "type": issue["code"],
                        "message": issue["message"],
                        "reason": "Stock and order limits right now.",
                        "cart_item_id": issue["item_id"],
                        "action": "remove" if issue["code"] == "unavailable" else "set_quantity",
                        "priority": 90,
                    }
                )
        return sorted(out, key=lambda s: -s["priority"])

    @staticmethod
    def _quantity_mismatch(kinds) -> list[dict]:
        """Plugs and screws in very different numbers (one screw per plug)."""
        plugs, screws = kinds.get("wall_plug", []), kinds.get("screw", [])
        if not plugs or not screws:
            return []

        def pieces(items):
            return sum(int(i.quantity * (kit.pack_amount(i.variant.product, i.variant, "pcs") or 1)) for i in items)

        p, s = pieces(plugs), pieces(screws)
        if s < p:
            first = screws[0]
            per_pack = int(kit.pack_amount(first.variant.product, first.variant, "pcs") or 1)
            more_packs = -(-(p - s) // per_pack)  # whole packs to cover the missing screws
            return [{"type": "quantity_mismatch", "message": f"{p} wall plugs but only {s} screws: one screw goes in each plug.",
                     "reason": "One screw per wall plug.", "cart_item_id": first.pk, "quantity": first.quantity + more_packs, "action": "set_quantity", "priority": 60}]  # fmt: skip
        if p < s:
            return [
                {
                    "type": "quantity_mismatch",
                    "message": f"{s} screws but only {p} wall plugs: one plug per screw in brick or concrete.",
                    "reason": "One wall plug per screw.",
                    "cart_item_id": plugs[0].pk,
                    "action": None,
                    "priority": 30,
                }
            ]
        return []

    def _needed_with(self, ctx) -> list[dict]:
        """The shop's REQUIRED links first; then what the compatibility engine knows a kind needs (bits for a
        drill); then the whole-word department rules (`cart_rules.NEED_RULES`) for products the shop hasn't linked."""
        out = []
        products = {item.variant.product_id: item for item in ctx["items"]}
        links = list(
            ProductRelation.objects.filter(
                product_id__in=products, kind__in=(ProductRelation.Kind.REQUIRED, ProductRelation.Kind.ACCESSORY)
            )
            .select_related("product", "related__category", "related__subcategory")
            .order_by("sort_order", "id")
        )
        required = [r for r in links if r.kind == ProductRelation.Kind.REQUIRED and r.related_id not in ctx["in_cart"]]
        # live rows carry the price annotations (cheapest variant) and the stock filter
        stocked = {p.pk: p for p in live().filter(pk__in=[r.related_id for r in links], is_demo=ctx["demo"])}
        for relation in required:
            if relation.related_id in stocked:
                out.append(
                    self._add(
                        stocked[relation.related_id],
                        f"Needed with {relation.product.name}" + (f": {relation.note}" if relation.note else "."),
                        85,
                        reason="The shop lists it as needed with this product.",
                    )
                )
        kinds_in_cart = {profiles.kind_of(item.variant.product) for item in ctx["items"]}
        for item in ctx["items"]:
            needed = NEEDS.get(profiles.kind_of(item.variant.product))
            if not needed or needed in kinds_in_cart:
                continue
            options = self.compat.compatible_options(
                item.variant.product, item.variant, needed, exclude=ctx["in_cart"], limit=1
            )
            if options:
                product = live().filter(pk=options[0]["product_id"], is_demo=ctx["demo"]).first()
                if product is not None:
                    out.append(
                        self._add(
                            product,
                            f"{item.variant.product.name} needs {needed.replace('_', ' ')}s: {options[0]['reason']}",
                            80,
                            variant_id=options[0]["variant_id"],
                            reason=options[0]["reason"],
                        )
                    )
                    kinds_in_cart.add(needed)
        out += self._rule_needs(ctx, stocked, links, kinds_in_cart)
        return sorted(out, key=lambda s: -s["priority"])

    def _rule_needs(self, ctx, stocked, links, kinds_in_cart) -> list[dict]:
        out, groups_done = [], set()
        cart_products = [item.variant.product for item in ctx["items"]]
        suggested = set(ctx["in_cart"]) | {r.related_id for r in links if r.kind == ProductRelation.Kind.REQUIRED}
        told = {r.product_id for r in links if r.kind == ProductRelation.Kind.REQUIRED}
        for item in ctx["items"][:CONTEXT_LINES]:
            product = item.variant.product
            if product.pk in told:
                continue  # the shop said what this product needs
            for rule in cart_rules.NEED_RULES:
                if rule.group in groups_done or not cart_rules.rule_applies(rule, product):
                    continue
                if rule.target_kind and rule.target_kind in kinds_in_cart:
                    continue
                if cart_rules.satisfied(rule, cart_products):
                    continue
                pick, variant_id, reason = None, None, rule.reason
                # 1. the shop's own "goes with" links of this product that are what the rule asks for
                for link in links:
                    row = stocked.get(link.related_id)
                    if link.product_id == product.pk and row is not None and row.pk not in suggested:
                        if any(cart_rules.has_term(cart_rules.names(row), term) for term in rule.suggest):
                            pick, reason = row, link.note or rule.reason
                            break
                # 2. the compatibility engine, when it can judge this pair (screws that fit the hinge's holes)
                if (
                    pick is None
                    and rule.target_kind
                    and rule.target_kind in rules.related_kinds(profiles.kind_of(product))
                ):
                    options = self.compat.compatible_options(
                        product, item.variant, rule.target_kind, exclude=suggested, limit=1
                    )
                    if options:
                        pick = live().filter(pk=options[0]["product_id"], is_demo=ctx["demo"]).first()
                        variant_id, reason = options[0]["variant_id"], options[0]["reason"] or rule.reason
                # 3. the catalogue, by whole words
                if pick is None:
                    for term in rule.suggest:
                        found = cart_rules.find_live(term, exclude=suggested, demo=ctx["demo"], limit=1)
                        if found:
                            pick = found[0]
                            break
                if pick is None:
                    continue
                groups_done.add(rule.group)
                suggested.add(pick.pk)
                out.append(
                    self._add(
                        pick, f"{product.name}: {rule.reason}", rule.priority, variant_id=variant_id, reason=reason
                    )
                )
        return out

    def _packs(self, ctx) -> list[dict]:
        """A cart line bought cheaper as another pack size of the same product (12 single screws → 1 box of 50):
        `packs.optimise` weighs every combination of the product's pack variants with the pricing engine. Only
        variants whose own label states the pack size, and that are otherwise the same item, are compared."""
        out = []
        product_ids = {item.variant.product_id for item in ctx["items"]}
        variants: dict[int, list] = {}
        for v in (
            ProductVariant.objects.filter(product_id__in=product_ids, is_active=True)
            .select_related("product")
            .prefetch_related(*VARIANT_PREFETCH)
            .order_by("pk")
        ):
            variants.setdefault(v.product_id, []).append(v)
        many = {pid: vs for pid, vs in variants.items() if len(vs) > 1}
        if not many:
            return []
        stock = selectors.variant_stock_map([v.pk for vs in many.values() for v in vs])
        for item in ctx["items"]:
            options = many.get(item.variant.product_id)
            if not options or any(p["id"] == item.pk and p["problem"] for p in ctx["priced"]["items"]):
                continue
            for unit in cart_rules.PACK_UNITS:
                own = cart_rules.explicit_pack(item.variant, unit)
                if own is None:
                    continue
                sized = [(v, cart_rules.explicit_pack(v, unit)) for v in options]
                same = [(v, s[0]) for v, s in sized if s is not None and s[1] == own[1]]
                if len({s for _, s in same}) < 2:
                    break
                product = item.variant.product
                need = item.quantity * own[0]
                choice = pack_optimiser.optimise(same, need, unit, stock=stock, limit=product.max_order_quantity)
                if choice is None or any(
                    stock.get(p.variant.pk, 0) < p.count or p.count > product.max_order_quantity for p in choice.parts
                ):
                    break
                current = line_from_variant(item.variant, item.quantity).line_total
                if choice.cost >= current or [(p.variant.pk, p.count) for p in choice.parts] == [
                    (item.variant_id, item.quantity)
                ]:
                    break
                saving = current - choice.cost
                label = pack_optimiser.describe(choice.parts, unit)
                now = pack_optimiser.describe([pack_optimiser.Part(item.variant, item.quantity, own[0])], unit)
                single = len(choice.parts) == 1
                part = choice.parts[0]
                out.append({
                    "type": "pack_size",
                    "message": f"{product.name}: {label} costs ₹{choice.cost:,.0f} instead of ₹{current:,.0f} for {now} (save ₹{saving:,.0f}).",
                    "reason": f"Same product in another pack size; covers {cart_rules_fmt(choice.covers)} {pack_optimiser.UNIT_LABEL.get(unit, unit)} for the {cart_rules_fmt(need)} you have.",
                    "cart_item_id": item.pk, "product_id": product.pk, "variant_id": part.variant.pk if single else None,
                    "quantity": part.count if single else None, "saving": _money(saving),
                    "parts": [{"variant_id": p.variant.pk, "quantity": p.count, "label": pack_optimiser.pack_label(p.variant, p.size, unit)} for p in choice.parts],
                    "action": "replace" if single else None, "priority": 58 + min(float(saving) / 100, 30),
                })  # fmt: skip
                break
        return sorted(out, key=lambda s: -float(s["saving"]))

    def _bulk(self, ctx) -> list[dict]:
        out = []
        for item in ctx["priced"]["items"]:
            price = item.get("price") or {}
            nxt = price.get("next_tier")
            if not nxt or not nxt.get("reachable") or item["problem"]:
                continue
            variant = next(i.variant for i in ctx["items"] if i.pk == item["id"])
            if ctx["stock"].get(variant.pk, 0) < nxt["min_quantity"]:
                continue  # not enough stock to reach the tier
            at_tier = line_from_variant(variant, nxt["min_quantity"])
            at_current_price = Decimal(price["unit_price"]) * nxt["min_quantity"]
            saving = at_current_price - at_tier.line_total
            if saving <= 0:
                continue
            out.append({
                "type": "bulk_tier",
                "message": f"Add {nxt['units_more']} more {variant.product.name} to pay ₹{at_tier.unit_price:,.0f} each (save ₹{saving:,.0f}).",
                "reason": f"Bulk price from {nxt['min_quantity']}.",
                "cart_item_id": item["id"], "product_id": variant.product_id, "variant_id": variant.pk,
                "quantity": nxt["min_quantity"], "saving": _money(saving), "extra_cost": _money(at_tier.line_total - Decimal(price["line_total"])),
                "action": "set_quantity", "priority": 55 + min(float(saving) / 100, 30),
            })  # fmt: skip
        return sorted(out, key=lambda s: -float(s["saving"]))

    def _free_delivery(self, ctx) -> list[dict]:
        """Only add-ons related to the cart (its accessories, co-purchases, needed-with rules, same department)
        that close the gap on their own, at a sensible quantity, priced by the engine. Nothing relevant: no section."""
        delivery = ctx["priced"]["delivery"]
        gap = Decimal(delivery["amount_to_free_delivery"] or "0")
        fee = Decimal(delivery["fee"] or "0")
        if gap <= 0 or fee <= 0:
            return []
        picks = []
        for product, why in self._addon_pool(ctx):
            if product.pk in ctx["used"]:
                continue
            variant = (
                ProductVariant.objects.select_related("product")
                .prefetch_related("price_tiers")
                .filter(pk=product.cheapest_variant_id)
                .first()
            )
            if variant is None:
                continue
            available = selectors.variant_stock_map([variant.pk]).get(variant.pk, 0)
            quantity = max(1, math.ceil(gap / product.price)) if product.price else 0
            while quantity and quantity <= min(FREE_DELIVERY_MAX_QUANTITY, product.max_order_quantity, available):
                line = line_from_variant(variant, quantity)
                if line.line_total >= gap:
                    picks.append((line.line_total - gap, product, variant, quantity, line, why))
                    break
                quantity += 1
            if len(picks) >= 6:
                break
        if not picks:
            return []
        picks.sort(key=lambda p: (p[0], p[1].pk))
        out = [
            {
                "type": "free_delivery",
                "message": f"Add ₹{gap:,.0f} more for free delivery (saves the ₹{fee:,.0f} fee).",
                "reason": "The shop's free-delivery threshold.",
                "gap": _money(gap),
                "fee": _money(fee),
                "action": None,
                "priority": 50,
            }
        ]
        for _, product, variant, quantity, line, why in picks[:2]:
            item = self._add(
                product,
                f"{quantity} × {product.name} (₹{line.line_total:,.0f}) unlocks free delivery.",
                52,
                variant_id=variant.pk,
                reason=why,
                quantity=quantity,
            )
            item["closes_gap"] = True
            out.append(item)
        return out

    def _alternatives(self, ctx) -> list[dict]:
        """Cheaper equivalents. A kind the compatibility engine knows: same kind and it must fit the rest of the
        cart. Any other product: same subcategory, the same value for every defining specification and the same
        variant label, cheaper for the same quantity by the pricing engine (tiers included), in stock."""
        out = []
        lines = ctx["items"][:ALTERNATIVE_LINES]
        kinded = [item for item in lines if profiles.kind_of(item.variant.product) is not None]
        self._load_checkable([item.variant.product_id for item in ctx["items"]])
        products = {p.pk: p for p in selectors.product_queryset().filter(pk__in=[i.variant.product_id for i in kinded])}
        for item in kinded:
            product = products.get(item.variant.product_id)
            if product is None:
                continue
            suggestions = [
                s for s in self.recs.alternatives(product) if s.product_id not in ctx["in_cart"] and "less." in s.reason
            ]
            alts = {
                p.pk: p
                for p in live()
                .filter(pk__in=[s.product_id for s in suggestions], is_demo=ctx["demo"])
                .prefetch_related("specifications")
            }
            self._load_checkable(list(alts))
            specs = cart_rules.defining_specs(item.variant.product)
            for suggestion in suggestions:
                alt = alts.get(suggestion.product_id)
                if alt is None or not cart_rules.states_same(specs, cart_rules.defining_specs(alt)):
                    continue  # differs in (or doesn't state) a defining specification of the cart's product
                if not self._fits_others(alt, item, ctx):
                    continue
                variant = (
                    ProductVariant.objects.filter(pk=alt.cheapest_variant_id).prefetch_related("price_tiers").first()
                )
                if (
                    variant is None
                    or selectors.variant_stock_map([variant.pk]).get(variant.pk, 0) < item.quantity
                    or item.quantity > alt.max_order_quantity
                ):
                    continue
                current = line_from_variant(item.variant, item.quantity).line_total
                new = line_from_variant(variant, item.quantity).line_total
                if new >= current:
                    continue
                kind_name = profiles.kind_of(alt).replace("_", " ")
                same, names = cart_rules.spec_text(item.variant.product, specs)
                out.append({
                    "type": "cheaper_alternative",
                    "message": f"{alt.name} (also a {kind_name}) costs ₹{current - new:,.0f} less for {item.quantity}" + (f" with the same {same}." if specs else ". Compare the specifications before replacing."),
                    "reason": f"Same kind ({kind_name})" + (f", the same {names}" if specs else "") + ", and it fits the rest of your cart.",
                    "cart_item_id": item.pk, "product_id": alt.pk, "variant_id": variant.pk, "quantity": item.quantity,
                    "saving": _money(current - new), "action": "replace", "priority": 45 + min(float(current - new) / 100, 20),
                })  # fmt: skip
                break
        out += self._spec_alternatives([item for item in lines if item not in kinded], ctx)
        return sorted(out, key=lambda s: -float(s["saving"]))

    def _spec_alternatives(self, items, ctx) -> list[dict]:
        out = []
        for item in items:
            product = item.variant.product
            specs = cart_rules.defining_specs(product)
            if not specs:
                continue  # nothing states what the product is: no equivalent can be judged
            scope = (
                {"subcategory_id": product.subcategory_id}
                if product.subcategory_id
                else {"category_id": product.category_id}
            )
            candidates = list(
                live()
                .filter(**scope, unit=product.unit, is_demo=product.is_demo)
                .exclude(pk__in=ctx["in_cart"])
                .prefetch_related("specifications", *(f"variants__{p}" for p in VARIANT_PREFETCH))
                .order_by("price", "pk")[:20]
            )
            current = line_from_variant(item.variant, item.quantity).line_total
            label = cart_rules.variant_label(item.variant)
            best = None
            for alt in candidates:
                if cart_rules.defining_specs(alt) != specs:
                    continue  # differs in (or doesn't state) a defining specification
                variant = next(
                    (v for v in alt.variants.all() if v.is_active and cart_rules.variant_label(v) == label), None
                )
                if variant is None or item.quantity > alt.max_order_quantity:
                    continue
                variant.product = alt
                new = line_from_variant(variant, item.quantity).line_total
                if new < current and (best is None or new < best[0]):
                    best = (new, alt, variant)
            if best is None:
                continue
            new, alt, variant = best
            if selectors.variant_stock_map([variant.pk]).get(variant.pk, 0) < item.quantity:
                continue
            same, names = cart_rules.spec_text(product, specs)
            scope_name = product.subcategory.name if product.subcategory_id else product.category.name
            out.append({
                "type": "cheaper_alternative",
                "message": f"{alt.name} costs ₹{current - new:,.0f} less for {item.quantity} with the same specifications ({same}).",
                "reason": f"Same {scope_name.lower()} and the same {names}.",
                "cart_item_id": item.pk, "product_id": alt.pk, "variant_id": variant.pk, "quantity": item.quantity,
                "saving": _money(current - new), "action": "replace", "priority": 45 + min(float(current - new) / 100, 20),
            })  # fmt: skip
        return out

    def _load_checkable(self, product_ids) -> None:
        missing = [pid for pid in product_ids if pid not in self._checkable]
        if missing:
            loaded = self.compat.load_many(missing)
            self._checkable.update({pid: loaded.get(pid) for pid in missing})

    def _verdict(self, product_id: int, variant_id: int | None, other_id: int, other_variant_id: int | None) -> str:
        """The engine's verdict for a pair, with products loaded once per analysis (not once per check)."""
        key = (product_id, variant_id, other_id, other_variant_id)
        if key not in self._verdicts:
            self._load_checkable([product_id, other_id])
            a, b = self._checkable[product_id], self._checkable[other_id]
            if a is None or b is None:
                self._verdicts[key] = "INSUFFICIENT_INFORMATION"
            else:
                va = next((v for v in a.variants.all() if v.pk == variant_id), None)
                vb = next((v for v in b.variants.all() if v.pk == other_variant_id), None)
                self._verdicts[key] = self.compat.check(a, b, va, vb).verdict
        return self._verdicts[key]

    def _fits_others(self, candidate, replaced_item, ctx) -> bool:
        """The replacement must fit everything else in the cart at least as well as the item it replaces
        (Phase 21 verdicts: a drill that only "possibly" takes the bits doesn't replace one that surely does)."""
        kind = profiles.kind_of(candidate)
        for other in ctx["items"]:
            if other.pk == replaced_item.pk:
                continue
            if rules.find_rule(kind, profiles.kind_of(other.variant.product))[0] is None:
                continue
            now = self._verdict(
                replaced_item.variant.product_id, replaced_item.variant_id, other.variant.product_id, other.variant_id
            )
            then = self._verdict(candidate.pk, None, other.variant.product_id, other.variant_id)
            if ORDER[then] > ORDER[now]:
                return False
        return True

    def _also_bought(self, ctx) -> list[dict]:
        """Customers also bought: recent orders with the cart's products (≥ 2 orders together), best lift first."""
        best: dict[int, tuple] = {}
        for item in ctx["items"][:CONTEXT_LINES]:
            for row in co_purchased(item.variant.product_id):
                if row.product_id in ctx["in_cart"]:
                    continue
                if row.product_id not in best or row.lift > best[row.product_id][0].lift:
                    best[row.product_id] = (row, item)
        if not best:
            return []
        rows = {p.pk: p for p in live().filter(pk__in=list(best), is_demo=ctx["demo"])}
        ranked = sorted(best.values(), key=lambda pair: (-pair[0].lift, -pair[0].confidence, pair[0].product_id))
        return [
            self._add(
                rows[row.product_id],
                f"Customers who bought {item.variant.product.name} also bought this.",
                32,
                reason=row.reason,
                extra={"orders": row.together, "confidence": row.confidence, "lift": row.lift},
            )
            for row, item in ranked
            if row.product_id in rows
        ]

    def _works_with(self, ctx) -> list[dict]:
        found, seen = [], set(ctx["in_cart"])
        for item in ctx["items"][:CONTEXT_LINES]:
            for row in self._accessories(item)["compatible"]:
                if row["product_id"] in seen or row["verdict"] != "COMPATIBLE":
                    continue
                seen.add(row["product_id"])
                found.append((item, row))
        products = {p.pk: p for p in live().filter(pk__in=[row["product_id"] for _, row in found], is_demo=ctx["demo"])}
        return [
            self._add(
                products[row["product_id"]],
                f"Works with {item.variant.product.name}: {row['reason']}",
                30,
                variant_id=row.get("variant_id"),
                reason=row["reason"] or "The shop lists it as compatible.",
            )
            for item, row in found
            if row["product_id"] in products
        ]

    def _bundles(self, ctx) -> list[dict]:
        """An admin bundle the cart already has at least two products of: add the missing ones."""
        out = []
        for bundle in bundle_service.bundles_with(ctx["in_cart"]):
            required = [i for i in bundle.items.all() if not i.is_optional]
            present = [i for i in required if i.product_id in ctx["in_cart"]]
            missing = [i for i in required if i.product_id not in ctx["in_cart"]]
            if not missing or len(present) < 2:
                continue
            lines = []
            for i in missing:
                variant = bundle_service._variant_for(i)
                if variant is None or not i.product.is_purchasable:
                    break
                lines.append(line_from_variant(variant, i.quantity))
            if len(lines) != len(missing):
                continue  # a missing item can't be bought now: the set can't be completed
            total = sum((line.line_total for line in lines), Decimal("0"))
            out.append({
                "type": "bundle",
                "message": f"Complete the {bundle.name}: add {', '.join(i.product.name for i in missing[:3])}{'…' if len(missing) > 3 else ''} for ₹{total:,.0f}.",
                "reason": f"You have {len(present)} of its {len(required)} items.",
                "bundle": {"slug": bundle.slug, "name": bundle.name, "missing": [i.product_id for i in missing]},
                "total": _money(total), "action": "apply_bundle", "priority": 25,
            })  # fmt: skip
        return out

    def _project_kits(self, ctx) -> list[dict]:
        """A project kit (the builder's templates: wall drilling, plumbing…) the cart already has at least two
        materials of: the missing materials as real products, one pack each, priced by the engine."""
        out = []
        cart = [(item.variant.product, [item.variant]) for item in ctx["items"]]
        for _, needs in cart_rules.kit_needs():
            have = [n for n in needs if any(cart_rules.need_met(n, p, vs) for p, vs in cart)]
            if len(have) < 2:
                continue
            exclude = set(ctx["in_cart"]) | ctx["used"]
            lines = []
            for need in needs:
                if need in have:
                    continue
                pick = None
                for term in need.search:
                    for row in cart_rules.find_live(term, exclude=exclude, demo=ctx["demo"], limit=3):
                        if kit.names_the_need(row, [], term, need.avoid):
                            pick = row
                            break
                    if pick:
                        break
                if pick is None:
                    continue
                variant = (
                    ProductVariant.objects.select_related("product")
                    .prefetch_related("price_tiers")
                    .filter(pk=pick.cheapest_variant_id)
                    .first()
                )
                if variant is None:
                    continue
                exclude.add(pick.pk)
                line = line_from_variant(variant, 1)
                lines.append({"product_id": pick.pk, "variant_id": variant.pk, "quantity": 1, "label": need.label, "name": pick.name,
                              "unit_price": _money(line.unit_price), "line_total": _money(line.line_total)})  # fmt: skip
            if not lines:
                continue
            total = sum((Decimal(line["line_total"]) for line in lines), Decimal("0"))
            template = needs[0].template_name
            out.append({
                "type": "complete_kit",
                "message": f"Completing a {template.lower()} job? You have {', '.join(n.label.lower() for n in have)}; add {', '.join(line['label'].lower() for line in lines)} for ₹{total:,.0f}.",
                "reason": f"You have {len(have)} of the {len(needs)} materials of the {template.lower()} kit. One pack each: check the amounts with the project planner.",
                "kit": {"key": needs[0].template, "name": template}, "lines": lines, "total": _money(total),
                "action": "add_lines", "priority": 24,
            })  # fmt: skip
            if len(out) >= 2:
                break
        return out

    def _offers(self, ctx, user) -> list[dict]:
        out = []
        for offer in ctx["priced"]["offers_in_reach"][:2]:
            out.append(
                {
                    "type": "offer",
                    "message": f"{offer['name']}: spend ₹{Decimal(offer['min_order_value']):,.0f} or more to unlock it.",
                    "reason": "An automatic offer with a minimum order value.",
                    "action": None,
                    "priority": 15,
                }
            )
        from apps.carts.services import summarize_cart
        from apps.offers.services import available_coupons
        from apps.offers.views import _coupon_badge

        for coupon in available_coupons(user, summarize_cart(user).priced_lines, badge=_coupon_badge)[:2]:
            text = f"Coupon {coupon['code']} ({coupon['badge']})" + (
                f" saves ₹{coupon['discount']:,.0f} at checkout." if coupon["applicable"] else f": {coupon['message']}"
            )
            out.append(
                {
                    "type": "coupon",
                    "message": text,
                    "reason": "A coupon you can use.",
                    "code": coupon["code"],
                    "applicable": coupon["applicable"],
                    "action": None,
                    "priority": 40 if coupon["applicable"] else 10,
                }
            )
        return out

    def _budget(self, ctx, budget: Decimal) -> dict:
        total = Decimal(ctx["priced"]["totals"]["grand_total"])
        remaining = budget - total
        item = {
            "type": "budget",
            "budget": _money(budget),
            "total": _money(total),
            "remaining": _money(remaining),
            "over": remaining < 0,
            "action": None,
            "priority": 95 if remaining < 0 else 5,
        }
        if remaining < 0:
            savings = [s for s in self._alternatives(ctx)]
            item["message"] = f"₹{-remaining:,.0f} over your ₹{budget:,.0f} budget." + (
                " Cheaper equivalents below could bring it down." if savings else ""
            )
            item["alternatives"] = savings[:3]
        else:
            item["message"] = f"₹{remaining:,.0f} left of your ₹{budget:,.0f} budget."
        return item

    # --- Helpers ------------------------------------------------------------------------------------------

    def _addon_pool(self, ctx) -> list[tuple]:
        """(live product, why it's relevant) for add-ons: the cart lines' required, compatible and accessory
        products, then their co-purchases, then the "needed with" rules, then best sellers of the same
        department (top-level category). Never products of unrelated departments."""
        ids: dict[int, str] = {}
        for item in ctx["items"][:CONTEXT_LINES]:
            groups = self._accessories(item)
            for name in ("required", "compatible", "accessories"):
                for row in groups[name]:
                    ids.setdefault(row["product_id"], f"Goes with {item.variant.product.name}.")
        for item in ctx["items"][:CONTEXT_LINES]:
            for row in co_purchased(item.variant.product_id):
                ids.setdefault(row.product_id, row.reason)
        departments = self._departments({item.variant.product.category_id for item in ctx["items"]})
        same = (
            live()
            .filter(is_demo=ctx["demo"], category_id__in=departments["members"])
            .exclude(pk__in=ctx["in_cart"])
            .order_by("-sold_count", "price", "pk")[:20]
        )
        for row in same:
            ids.setdefault(
                row.pk, f"From the same department ({departments['names'].get(row.category_id, 'this department')})."
            )
        wanted = [i for i in ids if i not in ctx["in_cart"]]
        rows = {p.pk: p for p in live().filter(pk__in=wanted, is_demo=ctx["demo"])}
        return [(rows[i], ids[i]) for i in wanted if i in rows]

    @staticmethod
    def _departments(category_ids) -> dict:
        """The top-level categories of `category_ids` and every category under them (one query)."""
        parents = dict(Category.objects.values_list("pk", "parent_id"))
        names = dict(Category.objects.filter(parent__isnull=True).values_list("pk", "name"))

        def root(pk):
            seen = set()
            while parents.get(pk) and pk not in seen:
                seen.add(pk)
                pk = parents[pk]
            return pk

        roots = {root(c) for c in category_ids}
        members = [pk for pk in parents if root(pk) in roots]
        return {"members": members, "names": {pk: names.get(root(pk), "") for pk in members}}

    @staticmethod
    def _add(
        product,
        message: str,
        priority: float,
        *,
        variant_id: int | None = None,
        reason: str = "",
        quantity: int = 1,
        extra: dict | None = None,
    ) -> dict:
        variant_id = variant_id or product.cheapest_variant_id
        variant = ProductVariant.objects.select_related("product").filter(pk=variant_id).first()
        return {
            "type": "add",
            "message": message,
            "reason": reason,
            "product_id": product.pk,
            "variant_id": variant_id,
            "quantity": quantity,
            "price": _offer_line(variant, quantity) if variant else None,
            "action": "add",
            "priority": priority,
            **(extra or {}),
        }


def cart_rules_fmt(value) -> str:
    if value is None:
        return "?"
    value = float(value)
    return str(int(value)) if value == int(value) else f"{value:g}"
