# ruff: noqa: E501 — reasons read better on one line
"""RecommendationService (Phase 22): which products to suggest, from catalogue facts only.

Signals, all from the shop's own data (no paid API, no ML infrastructure):
- the shop's links (`ProductRelation`: required → "Needed with this", compatible/rules → "Works with this",
  alternative → "Better alternative", accessory → "Frequently bought together" when no order data exists);
- the Phase 21 compatibility engine (never suggests a product it marks NOT_COMPATIBLE);
- real orders: products bought in the same orders ("Frequently bought together"), a customer's own past orders
  ("Buy again");
- category rules (`RecommendationRule`: "Complete the project"), popularity (units sold), bulk prices and discounts
  ("Best value"), price limits ("Best for your budget").

Every suggestion is a published, active product with stock (`selectors.product_queryset()` + `stock_total > 0`);
prices on the cards come from the catalogue, totals from the pricing engine. Nothing is personalised without the
customer's own history; a new visitor sees catalogue-wide groups with honest titles ("Popular right now").
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, Q

from apps.catalog import selectors
from apps.catalog.compatibility import profiles
from apps.catalog.compatibility.rules import NOT
from apps.catalog.compatibility.service import CompatibilityService
from apps.catalog.models import Category, ProductRelation
from apps.core.exceptions import NotFoundError

from ..models import RecommendationRule

GROUP_LIMIT = 6
CACHE_SECONDS = 600
SOLD = selectors.SOLD_STATUSES  # the orders "best sellers" count (Phase 15)
BOUGHT = selectors.SOLD_STATUSES

TITLES = {
    "needed_with": "Needed with this",
    "works_with": "Works with this",
    "frequently_bought_together": "Frequently bought together",
    "better_alternatives": "Better alternatives",
    "complete_the_project": "Complete the project",
    "best_value": "Best value",
    "popular_in_category": "Popular in this category",
    "best_for_budget": "Best for your budget",
    "buy_again": "Buy again",
    "recommended_for_you": "Based on your orders",
    "popular_now": "Popular right now",
    "complete_your_project": "Complete your project",
}


@dataclass
class Suggestion:
    product_id: int
    reason: str
    score: float = 0.0
    variant_id: int | None = None
    verdict: str | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "reason": self.reason,
            "variant_id": self.variant_id,
            "verdict": self.verdict,
            **self.extra,
        }


def live():
    """Published, active, in-stock products, annotated with price, stock and units sold."""
    return selectors.product_queryset().filter(stock_total__gt=0)


def _subtree(category_id: int) -> list[int]:
    ids, frontier = [category_id], [category_id]
    while frontier:
        frontier = list(Category.objects.filter(parent_id__in=frontier, is_active=True).values_list("pk", flat=True))
        ids += frontier
    return ids


def _in_categories(qs, category_ids):
    return qs.filter(Q(category_id__in=category_ids) | Q(subcategory_id__in=category_ids))


def co_purchased(product_id: int, limit: int = GROUP_LIMIT) -> list[tuple[int, int]]:
    """(product_id, orders) bought in the same orders as `product_id`, most often first. Cached."""
    key = f"shopping:fbt:{product_id}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    from apps.orders.models import OrderItem

    orders = OrderItem.objects.filter(product_id=product_id, order__status__in=SOLD).values("order_id")[:500]
    rows = list(
        OrderItem.objects.filter(order_id__in=orders, product__isnull=False)
        .exclude(product_id=product_id)
        .values("product_id")
        .annotate(orders=Count("order_id", distinct=True))
        .order_by("-orders", "product_id")[: limit * 2]
    )
    result = [(row["product_id"], row["orders"]) for row in rows]
    cache.set(key, result, CACHE_SECONDS)
    return result


class RecommendationService:
    def __init__(self):
        self.compat = CompatibilityService()
        self.checked: dict[int, str] = {}  # product id → the engine's reason, from _not_incompatible

    # --- Product page ---------------------------------------------------------------------------------------

    def for_product(self, product_id: int, *, variant_id: int | None = None, budget: Decimal | None = None) -> dict:
        product = selectors.product_queryset().filter(pk=product_id).first()
        if product is None:
            raise NotFoundError("Product not found.")
        stocked = set()
        groups: dict[str, list[Suggestion]] = {}
        seen = {product.pk}
        links = list(ProductRelation.objects.filter(product=product).order_by("sort_order", "id"))
        blocked = {r.related_id for r in links if r.kind == ProductRelation.Kind.INCOMPATIBLE}
        blocked |= set(
            ProductRelation.objects.filter(related=product, kind=ProductRelation.Kind.INCOMPATIBLE).values_list(
                "product_id", flat=True
            )
        )
        candidate_ids = {r.related_id for r in links}
        stocked = set(live().filter(pk__in=candidate_ids).values_list("pk", flat=True))

        def take(name, items: list[Suggestion]):
            out = []
            for s in items:
                if s.product_id in seen or s.product_id in blocked:
                    continue
                seen.add(s.product_id)
                out.append(s)
                if len(out) >= GROUP_LIMIT:
                    break
            if out:
                groups[name] = out

        # 1. Needed with this: the shop's "required" links
        take("needed_with", [Suggestion(r.related_id, r.note or "The shop lists it as needed with this.", 100 - i) for i, r in enumerate(links)
                             if r.kind == ProductRelation.Kind.REQUIRED and r.related_id in stocked])  # fmt: skip
        # 2. Works with this: shop "compatible" links and products the compatibility rules confirm
        accessories = self.compat.accessories(product.pk, variant_id)["groups"]
        works = [Suggestion(row["product_id"], row["reason"] or row["note"] or "Works with this.", 90, row.get("variant_id"), row["verdict"])
                 for row in accessories["compatible"] if row["product_id"] in self._stocked([r["product_id"] for r in accessories["compatible"]])]  # fmt: skip
        # the shop's "goes with" links that the compatibility rules confirm also work with it
        confirmed = [s for s in self._not_incompatible(product, [Suggestion(r.related_id, r.note, 85) for r in links
                     if r.kind == ProductRelation.Kind.ACCESSORY and r.related_id in stocked]) if s.verdict == "COMPATIBLE"]  # fmt: skip
        for s in confirmed:
            s.reason = self.checked.get(s.product_id) or s.reason
        take("works_with", works + confirmed)
        # 3. Frequently bought together: real orders, else the shop's "goes with" links
        bought = co_purchased(product.pk)
        live_bought = self._stocked([pid for pid, _ in bought])
        together = [
            Suggestion(pid, f"Bought together in {n} order{'s' if n != 1 else ''}.", n, extra={"orders": n})
            for pid, n in bought
            if pid in live_bought
        ]
        together += [
            Suggestion(r.related_id, r.note or "Often bought with this.", 1)
            for r in links
            if r.kind == ProductRelation.Kind.ACCESSORY and r.related_id in stocked
        ]
        take("frequently_bought_together", self._not_incompatible(product, together))
        # 4. Better alternatives: the shop's alternatives, then cheaper or better-rated products of the same kind
        take("better_alternatives", [Suggestion(r.related_id, r.note or "An alternative the shop suggests.", 80) for r in links
                                     if r.kind == ProductRelation.Kind.ALTERNATIVE and r.related_id in stocked] + self.alternatives(product))  # fmt: skip
        # 5. Complete the project: category rules
        take("complete_the_project", self.complete_project([product.category_id, product.subcategory_id]))
        # 6. Best value and popular in the same (sub)category
        category_ids = _subtree(product.subcategory_id or product.category_id)
        take("best_value", self.best_value(category_ids, exclude={product.pk}))
        take(
            "popular_in_category", self.popular(category_ids, exclude={product.pk}, reason="Popular in this category.")
        )
        if budget is not None:
            take(
                "best_for_budget",
                self.within_budget(budget, category_ids=_subtree(product.category_id), exclude={product.pk}),
            )
        return {
            "product_id": product.pk,
            "groups": {name: [s.as_dict() for s in items] for name, items in groups.items()},
            "titles": TITLES,
        }

    # --- Home page ------------------------------------------------------------------------------------------

    def for_home(self, user=None) -> dict:
        """Personal groups only from the customer's own history; everyone gets catalogue-wide groups."""
        groups: dict[str, list[Suggestion]] = {}
        seen: set[int] = set()

        def take(name, items):
            out = [s for s in items if s.product_id not in seen][:GROUP_LIMIT]
            seen.update(s.product_id for s in out)
            if out:
                groups[name] = out

        personal = False
        if user is not None and getattr(user, "is_authenticated", False):
            again = self.buy_again(user)
            take("buy_again", again)
            categories = self._customer_categories(user)
            if categories:
                personal = True
                bought = {s.product_id for s in again}
                take(
                    "recommended_for_you",
                    self.popular(categories, exclude=bought, reason="Based on your orders and saved items."),
                )
                take("complete_your_project", self.complete_project(categories))
        take("best_value", self.best_value(None, exclude=set()))
        take("popular_now", self.popular(None, exclude=set(), reason="Popular right now."))
        return {
            "personal": personal,
            "groups": {name: [s.as_dict() for s in items] for name, items in groups.items()},
            "titles": TITLES,
        }

    # --- Building blocks -----------------------------------------------------------------------------------

    @staticmethod
    def _stocked(ids) -> set[int]:
        ids = list(ids)
        return set(live().filter(pk__in=ids).values_list("pk", flat=True)) if ids else set()

    def _not_incompatible(self, product, items: list[Suggestion]) -> list[Suggestion]:
        """Drop suggestions the compatibility engine marks NOT_COMPATIBLE with `product` (when a rule applies). The
        products and links are loaded once for all suggestions; a checked one keeps the engine's reason in `checked`."""
        if not items:
            return items
        from apps.catalog.compatibility import rules

        ids = [s.product_id for s in items]
        loaded = self.compat.load_many([product.pk, *ids])
        source = loaded.get(product.pk)
        links = self.compat.links_between(product.pk, ids)
        own = profiles.kind_of(product)
        out = []
        for s in items:
            other = loaded.get(s.product_id)
            if other is None:  # went off sale: not suggested
                continue
            if rules.find_rule(own, profiles.kind_of(other))[0] is not None:
                if source is None:
                    continue
                result = self.compat.check(source, other, relations=links)
                if result.verdict == NOT:
                    continue
                s.verdict = result.verdict
                self.checked[s.product_id] = result.reason
            out.append(s)
        return out

    def alternatives(self, product, *, max_price: Decimal | None = None) -> list[Suggestion]:
        """Same recognised kind (Phase 21 kinds: drill, drill bit, pipe…) and (sub)category, in stock: cheaper ones
        first, then better-rated ones at a similar price. Products of no recognised kind (cement, paint, adhesive)
        get none here: a grade or a use can't be judged equivalent from the category alone (shop "alternative"
        links still apply)."""
        kind = profiles.kind_of(product)
        if kind is None:
            return []
        category_ids = _subtree(product.subcategory_id or product.category_id)
        rows = list(_in_categories(live(), category_ids).exclude(pk=product.pk).order_by("price", "-rating_avg")[:40])
        out = []
        price = product.price or Decimal("0")
        for row in rows:
            if profiles.kind_of(row) != kind:
                continue
            if row.price is None or (max_price is not None and row.price > max_price):
                continue
            if row.price < price:
                out.append(
                    Suggestion(
                        row.pk,
                        f"Also a {kind.replace('_', ' ')}, ₹{price - row.price:,.0f} less. Compare the specifications.",
                        float(price - row.price),
                        extra={"saving_each": f"{price - row.price:.2f}"},
                    )
                )
            elif (
                row.rating_avg
                and product.rating_avg is not None
                and row.rating_avg > product.rating_avg
                and row.price <= price * Decimal("1.1")
            ):
                out.append(
                    Suggestion(row.pk, f"Rated {row.rating_avg:.1f}★ at a similar price.", float(row.rating_avg))
                )
        return sorted(out, key=lambda s: -s.score)

    def complete_project(self, category_ids) -> list[Suggestion]:
        ids = [c for c in category_ids if c]
        if not ids:
            return []
        parents = set(Category.objects.filter(pk__in=ids).values_list("parent_id", flat=True)) - {None}
        rules = list(
            RecommendationRule.objects.filter(source_category_id__in=set(ids) | parents, is_active=True).select_related(
                "target_category"
            )[:10]
        )
        out = []
        for rule in rules:
            label = rule.label or f"Often needed with {rule.source_category.name.lower()}."
            for row in _in_categories(live(), _subtree(rule.target_category_id)).order_by(
                "-sold_count", "-rating_avg", "name"
            )[:4]:
                out.append(Suggestion(row.pk, label, 200 - rule.priority + row.sold_count))
        return out

    def best_value(self, category_ids, *, exclude: set[int]) -> list[Suggestion]:
        """Bulk prices first, then the biggest discount off MRP, then popularity."""
        qs = live() if category_ids is None else _in_categories(live(), category_ids)
        out = []
        for row in (
            qs.exclude(pk__in=exclude)
            .filter(Q(bulk_min_price__isnull=False) | Q(discount_rank__gt=0))
            .order_by("-discount_rank", "-sold_count")[:20]
        ):
            if row.bulk_min_price is not None and row.bulk_min_quantity:
                reason = f"Bulk price ₹{row.bulk_min_price:,.0f} each from {row.bulk_min_quantity}."
                score = 100 + float(row.discount_rank or 0)
            else:
                reason = f"{row.discount_rank:.0f}% below MRP."
                score = float(row.discount_rank or 0)
            out.append(Suggestion(row.pk, reason, score))
        return sorted(out, key=lambda s: -s.score)

    def popular(self, category_ids, *, exclude: set[int], reason: str) -> list[Suggestion]:
        qs = live() if category_ids is None else _in_categories(live(), category_ids)
        return [
            Suggestion(row.pk, reason, row.sold_count)
            for row in qs.exclude(pk__in=exclude).order_by("-sold_count", "-rating_count", "name")[: GROUP_LIMIT * 2]
        ]

    def within_budget(self, budget: Decimal, *, category_ids=None, exclude: set[int] = frozenset()) -> list[Suggestion]:
        qs = live().filter(price__lte=budget)
        if category_ids:
            qs = _in_categories(qs, category_ids)
        return [Suggestion(row.pk, f"₹{row.price:,.0f}, within ₹{budget:,.0f}.", float(row.rating_avg or 0) * 10 + row.sold_count)
                for row in qs.exclude(pk__in=exclude).order_by("-rating_avg", "-sold_count", "price")[: GROUP_LIMIT * 2]]  # fmt: skip

    def buy_again(self, user) -> list[Suggestion]:
        """Products the customer actually received or ordered, most recent first, still on sale and in stock."""
        from apps.orders.models import OrderItem

        rows = (
            OrderItem.objects.filter(order__user=user, order__status__in=BOUGHT, product__isnull=False)
            .order_by("-order__created_at")
            .values_list("product_id", "variant_id")[:60]
        )
        firsts: dict[int, int | None] = {}
        for product_id, variant_id in rows:
            firsts.setdefault(product_id, variant_id)
        stocked = self._stocked(firsts)
        return [
            Suggestion(pid, "You ordered this before.", 0, variant_id=vid)
            for pid, vid in firsts.items()
            if pid in stocked
        ]

    @staticmethod
    def _customer_categories(user) -> list[int]:
        from apps.carts.models import CartItem, WishlistItem
        from apps.orders.models import OrderItem

        ids = list(
            OrderItem.objects.filter(order__user=user, product__isnull=False).values_list(
                "product__subcategory_id", "product__category_id"
            )[:50]
        )
        ids += list(
            WishlistItem.objects.filter(wishlist__user=user).values_list(
                "product__subcategory_id", "product__category_id"
            )[:30]
        )
        ids += list(
            CartItem.objects.filter(cart__user=user).values_list(
                "variant__product__subcategory_id", "variant__product__category_id"
            )[:30]
        )
        out = []
        for sub, cat in ids:
            chosen = sub or cat
            if chosen and chosen not in out:
                out.append(chosen)
        expanded = []
        for category_id in out[:5]:
            expanded += _subtree(category_id)
        return expanded
