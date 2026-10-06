# ruff: noqa: E501 — messages read better on one line
"""SmartCartService (Phase 22): what's worth telling the customer about their cart, highest value first.

Read-only. It never changes the cart: each suggestion carries an action (add, replace, remove, set the quantity,
apply a bundle) that the customer confirms on the page, and the cart API then checks it again.

Sources (no second pricing, stock, offer, delivery or compatibility logic):
- `ai.projects.kit.price_rows` over the cart lines → the pricing engine (tiers, offers, coupon rules, free-delivery
  rules, zone fee), stock, order limits, delivery plan and the Phase 21 compatibility problems;
- `catalog.compatibility` for needed accessories and compatible replacements;
- `RecommendationService` for add-ons and cheaper equivalents; `offers.services.available_coupons`; bundles.

Sections, in this order (each capped so the cart stays calm): cart warnings, needed with it, save with bulk pricing,
free delivery opportunity, better alternatives, works with it, bundle opportunities, offers and coupons, budget.
"""

from decimal import Decimal

from apps.ai.projects import kit
from apps.carts.models import CartItem
from apps.catalog import selectors
from apps.catalog.compatibility import profiles, rules
from apps.catalog.compatibility.rules import ORDER
from apps.catalog.compatibility.service import CompatibilityService
from apps.catalog.models import ProductRelation, ProductVariant
from apps.orders.pricing import line_from_variant

from . import bundles as bundle_service
from .recommendations import RecommendationService, live

SECTION_LIMIT = 3
ALTERNATIVE_LINES = 10  # cheaper equivalents are looked for on the first 10 lines of a kind the engine knows
# A cart with a product of the first kind usually needs one of the second ("your drill needs bits").
NEEDS = {"drill": "drill_bit", "wall_plug": "screw", "screw": "wall_plug"}
TITLES = {
    "warnings": "Cart warnings",
    "needed_with": "Needed with it",
    "bulk": "Save with bulk pricing",
    "free_delivery": "Free delivery opportunity",
    "alternatives": "Better alternatives",
    "works_with": "Works with it",
    "bundles": "Bundle opportunities",
    "offers": "Offers and coupons",
    "budget": "Budget",
}


def _money(value) -> str:
    return f"{Decimal(value):.2f}"


def _offer_line(variant, quantity: int) -> dict:
    line = line_from_variant(variant, quantity)
    return {"unit_price": _money(line.unit_price), "line_total": _money(line.line_total)}


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
            .prefetch_related(
                "variant__price_tiers", "variant__option_values__option_type", "variant__option_values__value"
            )
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
        context = {"items": items, "priced": priced, "in_cart": in_cart, "stock": stock}

        sections = []
        for key, builder in (
            ("warnings", self._warnings),
            ("needed_with", self._needed_with),
            ("bulk", self._bulk),
            ("free_delivery", self._free_delivery),
            ("alternatives", self._alternatives),
            ("works_with", self._works_with),
            ("bundles", self._bundles),
            ("offers", lambda ctx: self._offers(ctx, user)),
        ):
            found = builder(context)
            if found:
                sections.append(
                    {"key": key, "title": TITLES[key], "items": found[: SECTION_LIMIT if key != "warnings" else 10]}
                )
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

    # --- Sections -----------------------------------------------------------------------------------------

    def _warnings(self, ctx) -> list[dict]:
        out = []
        for problem in ctx["priced"]["compatibility"]:
            option = (problem.get("options") or [None])[0]
            out.append({
                "type": "incompatible",
                "verdict": problem["verdict"],
                "message": problem["message"],
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
                            "cart_item_id": same[-1].pk, "product_id": product_id, "action": "remove", "priority": 40})  # fmt: skip
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
                     "cart_item_id": first.pk, "quantity": first.quantity + more_packs, "action": "set_quantity", "priority": 60}]  # fmt: skip
        if p < s:
            return [
                {
                    "type": "quantity_mismatch",
                    "message": f"{s} screws but only {p} wall plugs: one plug per screw in brick or concrete.",
                    "cart_item_id": plugs[0].pk,
                    "action": None,
                    "priority": 30,
                }
            ]
        return []

    def _needed_with(self, ctx) -> list[dict]:
        out = []
        products = {item.variant.product_id: item for item in ctx["items"]}
        required = (
            ProductRelation.objects.filter(product_id__in=products, kind=ProductRelation.Kind.REQUIRED)
            .exclude(related_id__in=ctx["in_cart"])
            .select_related("product", "related")
        )
        # live rows carry the price annotations (cheapest variant) and the stock filter
        stocked = {p.pk: p for p in live().filter(pk__in=[r.related_id for r in required])}
        for relation in required:
            if relation.related_id in stocked:
                out.append(
                    self._add(
                        stocked[relation.related_id],
                        f"Needed with {relation.product.name}" + (f": {relation.note}" if relation.note else "."),
                        85,
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
                product = live().filter(pk=options[0]["product_id"]).first()
                if product is not None:
                    out.append(
                        self._add(
                            product,
                            f"{item.variant.product.name} needs {needed.replace('_', ' ')}s: {options[0]['reason']}",
                            80,
                            variant_id=options[0]["variant_id"],
                        )
                    )
                    kinds_in_cart.add(needed)
        return out

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
                "cart_item_id": item["id"], "product_id": variant.product_id, "variant_id": variant.pk,
                "quantity": nxt["min_quantity"], "saving": _money(saving), "extra_cost": _money(at_tier.line_total - Decimal(price["line_total"])),
                "action": "set_quantity", "priority": 55 + min(float(saving) / 100, 30),
            })  # fmt: skip
        return sorted(out, key=lambda s: -float(s["saving"]))

    def _free_delivery(self, ctx) -> list[dict]:
        delivery = ctx["priced"]["delivery"]
        gap = Decimal(delivery["amount_to_free_delivery"] or "0")
        fee = Decimal(delivery["fee"] or "0")
        if gap <= 0 or fee <= 0:
            return []
        pool = self._addon_pool(ctx)
        above = sorted([p for p in pool if p.price is not None and p.price >= gap], key=lambda p: p.price)
        below = sorted([p for p in pool if p.price is not None and p.price < gap], key=lambda p: -p.price)
        picks = (above + below)[:2]
        out = [
            {
                "type": "free_delivery",
                "message": f"Add ₹{gap:,.0f} more for free delivery (saves the ₹{fee:,.0f} fee).",
                "gap": _money(gap),
                "fee": _money(fee),
                "action": None,
                "priority": 50,
            }
        ]
        for product in picks:
            covers = product.price >= gap
            out.append(
                self._add(
                    product,
                    f"₹{product.price:,.0f}: "
                    + ("unlocks free delivery." if covers else "gets you closer to free delivery."),
                    52 if covers else 35,
                )
            )
        return out

    def _alternatives(self, ctx) -> list[dict]:
        out = []
        # only kinds the compatibility engine recognises have same-kind alternatives; cart products load in one query
        kinded = [item for item in ctx["items"] if profiles.kind_of(item.variant.product) is not None][
            :ALTERNATIVE_LINES
        ]
        self._load_checkable([item.variant.product_id for item in ctx["items"]])
        products = {p.pk: p for p in selectors.product_queryset().filter(pk__in=[i.variant.product_id for i in kinded])}
        for item in kinded:
            product = products.get(item.variant.product_id)
            if product is None:
                continue
            suggestions = [
                s for s in self.recs.alternatives(product) if s.product_id not in ctx["in_cart"] and "less." in s.reason
            ]
            alts = {p.pk: p for p in live().filter(pk__in=[s.product_id for s in suggestions])}
            self._load_checkable(list(alts))
            for suggestion in suggestions:
                alt = alts.get(suggestion.product_id)
                if alt is None or not self._fits_others(alt, item, ctx):
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
                out.append({
                    "type": "cheaper_alternative",
                    "message": f"{alt.name} (also a {profiles.kind_of(alt).replace('_', ' ')}) costs ₹{current - new:,.0f} less for {item.quantity}. Compare the specifications before replacing.",
                    "cart_item_id": item.pk, "product_id": alt.pk, "variant_id": variant.pk, "quantity": item.quantity,
                    "saving": _money(current - new), "action": "replace", "priority": 45 + min(float(current - new) / 100, 20),
                })  # fmt: skip
                break
        return sorted(out, key=lambda s: -float(s["saving"]))

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

    def _works_with(self, ctx) -> list[dict]:
        found, seen = [], set(ctx["in_cart"])
        for item in ctx["items"][:5]:
            for row in self._accessories(item)["compatible"]:
                if row["product_id"] in seen or row["verdict"] != "COMPATIBLE":
                    continue
                seen.add(row["product_id"])
                found.append((item, row))
        products = {p.pk: p for p in live().filter(pk__in=[row["product_id"] for _, row in found])}
        return [
            self._add(
                products[row["product_id"]],
                f"Works with {item.variant.product.name}: {row['reason']}",
                30,
                variant_id=row.get("variant_id"),
            )
            for item, row in found
            if row["product_id"] in products
        ]

    def _bundles(self, ctx) -> list[dict]:
        out = []
        for bundle in bundle_service.bundles_with(ctx["in_cart"]):
            products = [i.product_id for i in bundle.items.all() if not i.is_optional]
            missing = [i for i in bundle.items.all() if not i.is_optional and i.product_id not in ctx["in_cart"]]
            if not missing or len(missing) == len(products):
                continue
            out.append({
                "type": "bundle",
                "message": f"Complete the {bundle.name}: add {', '.join(i.product.name for i in missing[:3])}{'…' if len(missing) > 3 else ''}.",
                "bundle": {"slug": bundle.slug, "name": bundle.name, "missing": [i.product_id for i in missing]},
                "action": "apply_bundle", "priority": 25,
            })  # fmt: skip
        return out

    def _offers(self, ctx, user) -> list[dict]:
        out = []
        for offer in ctx["priced"]["offers_in_reach"][:2]:
            out.append(
                {
                    "type": "offer",
                    "message": f"{offer['name']}: spend ₹{Decimal(offer['min_order_value']):,.0f} or more to unlock it.",
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

    def _addon_pool(self, ctx):
        """Useful, in-stock add-ons: compatible accessories and popular products of the cart's categories."""
        ids = []
        for item in ctx["items"][:5]:
            groups = self._accessories(item)
            ids += [row["product_id"] for name in ("required", "compatible", "accessories") for row in groups[name]]
        categories = {item.variant.product.subcategory_id or item.variant.product.category_id for item in ctx["items"]}
        ids += [s.product_id for s in self.recs.popular(list(categories), exclude=ctx["in_cart"], reason="")]
        ids = [i for i in dict.fromkeys(ids) if i not in ctx["in_cart"]]
        rows = {p.pk: p for p in live().filter(pk__in=ids)}
        return [rows[i] for i in ids if i in rows]

    @staticmethod
    def _add(product, message: str, priority: float, *, variant_id: int | None = None) -> dict:
        variant_id = variant_id or product.cheapest_variant_id
        variant = ProductVariant.objects.select_related("product").filter(pk=variant_id).first()
        return {
            "type": "add",
            "message": message,
            "product_id": product.pk,
            "variant_id": variant_id,
            "quantity": 1,
            "price": _offer_line(variant, 1) if variant else None,
            "action": "add",
            "priority": priority,
        }
