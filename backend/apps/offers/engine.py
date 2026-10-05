"""Automatic offers: discounts applied without a code.

Rules (documented in docs/ARCHITECTURE.md → Offers and coupons):

- An offer is live when `is_active` and `starts_at <= now < ends_at` (no end = open-ended) and it
  has uses left (`usage_limit`).
- Targets: products and/or categories (a category also matches everything below it, down to the
  third level). No targets = every line.
- Phase 15 conditions: a line counts only with at least `min_quantity` units; `max_prior_orders`
  and `per_customer_limit` depend on the signed-in customer (a visitor never gets those offers).
- One discount offer per cart line. Where several offers match a line, the lowest `priority`
  number wins (ties: the older offer, i.e. lower id), so admins control overlap explicitly.
- `min_order_value` is measured on the lines the offer won ("spend ₹2,000 on power tools"). An offer
  that misses its minimum releases its lines to the next-best matching offer; this repeats until stable.
- Percent: `eligible × value / 100`, capped by `max_discount_amount`. Fixed: `value`, never more than
  the eligible amount. The discount is spread over the offer's lines in proportion to their totals
  (rounding remainder on the last line), so tax can be computed per line on the net amount.
- Free-delivery offers (`benefit = free_delivery`) don't take lines from discount offers: the best
  one whose matching lines reach its minimum makes the order's delivery free (orders.pricing).
- Coupons are applied afterwards, on the amounts left after offers (see `orders.pricing.price_lines`).

Everything is Decimal. The engine reads active offers once per call and does the rest in Python,
so it is portable to every database and cheap for the handful of offers a store runs.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from apps.core.money import ZERO, q

from .models import DiscountType, Offer


@dataclass(frozen=True)
class OfferRule:
    """An offer with its targets loaded (ids only)."""

    id: int
    name: str
    description: str
    discount_type: str
    value: Decimal
    max_discount_amount: Decimal | None
    min_order_value: Decimal
    priority: int
    product_ids: frozenset[int]
    category_ids: frozenset[int]
    ends_at: datetime | None = None
    # Phase 15
    benefit: str = Offer.Benefit.DISCOUNT
    min_quantity: int = 0
    max_prior_orders: int | None = None
    per_customer_limit: int | None = None
    campaign: str = ""

    @property
    def targets_everything(self) -> bool:
        return not self.product_ids and not self.category_ids

    @property
    def is_free_delivery(self) -> bool:
        return self.benefit == Offer.Benefit.FREE_DELIVERY

    @property
    def customer_specific(self) -> bool:
        return self.max_prior_orders is not None or self.per_customer_limit is not None

    def matches(
        self, *, product_id: int, category_id: int, subcategory_id: int | None, lineage: frozenset[int] | None = None
    ) -> bool:
        """`lineage` = the line's categories with all their ancestors (catalog.tree.lineage)."""
        if self.targets_everything:
            return True
        if product_id in self.product_ids:
            return True
        if lineage is not None:
            return bool(self.category_ids & lineage)
        return category_id in self.category_ids or (subcategory_id is not None and subcategory_id in self.category_ids)

    def discount_for(self, eligible: Decimal) -> Decimal:
        if eligible <= 0 or self.is_free_delivery:
            return ZERO
        if self.discount_type == DiscountType.PERCENT:
            amount = q(eligible * self.value / 100)
            if self.max_discount_amount is not None:
                amount = min(amount, self.max_discount_amount)
        else:
            amount = self.value
        return q(min(amount, eligible))

    @property
    def badge(self) -> str:
        """Short customer-facing label, e.g. "10% off", "₹50 off" or "Free delivery"."""
        if self.is_free_delivery:
            return "Free delivery"
        if self.discount_type == DiscountType.PERCENT:
            value = self.value.normalize()
            text = f"{value:f}% off"
            if self.max_discount_amount is not None:
                text += f" (up to ₹{self.max_discount_amount.normalize():f})"
            return text
        return f"₹{self.value.normalize():f} off"

    @property
    def conditions(self) -> list[str]:
        """The conditions in words, shown wherever the offer is advertised (nothing hidden)."""
        out = []
        if self.min_quantity > 1:
            out.append(f"Buy {self.min_quantity} or more of an item")
        if self.min_order_value > 0:
            out.append(f"Spend ₹{self.min_order_value.normalize():f} on eligible items")
        if self.max_prior_orders == 0:
            out.append("First order only")
        elif self.max_prior_orders is not None:
            out.append(f"Your first {self.max_prior_orders + 1} orders")
        if self.per_customer_limit is not None:
            out.append(f"Up to {self.per_customer_limit} order(s) per customer")
        return out


@dataclass(frozen=True)
class AppliedOffer:
    offer: OfferRule
    discount: Decimal
    eligible_amount: Decimal
    variant_ids: tuple[int, ...]


@dataclass(frozen=True)
class MissedOffer:
    """An offer the cart matches but whose minimum spend (or quantity) isn't reached yet."""

    offer: OfferRule
    eligible_amount: Decimal
    shortfall: Decimal
    units_short: int = 0  # Phase 15: "add 3 more of this item"


@dataclass
class OfferResult:
    line_discounts: dict[int, Decimal] = field(default_factory=dict)  # variant_id → discount
    applied: list[AppliedOffer] = field(default_factory=list)
    missed: list[MissedOffer] = field(default_factory=list)
    free_delivery: AppliedOffer | None = None  # Phase 15

    @property
    def total(self) -> Decimal:
        return q(sum((a.discount for a in self.applied), ZERO))

    @property
    def all_applied(self) -> list[AppliedOffer]:
        """Discount offers and the free-delivery offer (for redemptions and order snapshots)."""
        return self.applied + ([self.free_delivery] if self.free_delivery else [])


def _rule(o: Offer) -> OfferRule:
    return OfferRule(
        id=o.id,
        name=o.name,
        description=o.description,
        discount_type=o.discount_type,
        value=o.value,
        max_discount_amount=o.max_discount_amount,
        min_order_value=o.min_order_value,
        priority=o.priority,
        product_ids=frozenset(p.id for p in o.products.all()),
        category_ids=frozenset(c.id for c in o.categories.all()),
        ends_at=o.ends_at,
        benefit=o.benefit,
        min_quantity=o.min_quantity,
        max_prior_orders=o.max_prior_orders,
        per_customer_limit=o.per_customer_limit,
        campaign=o.campaign,
    )


def load_active_offers(now=None) -> list[OfferRule]:
    """Live offers with uses left (for everyone; customer conditions are checked per customer)."""
    now = now or timezone.now()
    offers = (
        Offer.objects.filter(is_active=True, starts_at__lte=now)
        .exclude(ends_at__isnull=False, ends_at__lte=now)
        .prefetch_related("products", "categories")
        .order_by("priority", "id")
    )
    return [_rule(o) for o in offers if o.usage_limit is None or o.used_count < o.usage_limit]


def prior_order_count(user) -> int:
    """Earlier orders that count for first-order offers (cancelled ones don't)."""
    from apps.orders.models import Order, OrderStatus

    return Order.objects.filter(user=user).exclude(status=OrderStatus.CANCELLED).count()


def eligible_for(rules: Sequence[OfferRule], user) -> list[OfferRule]:
    """Drop offers this customer can't use: first-order and per-customer limits need a signed-in customer."""
    if not any(r.customer_specific for r in rules):
        return list(rules)
    signed_in = user is not None and getattr(user, "is_authenticated", False)
    if not signed_in:
        return [r for r in rules if not r.customer_specific]
    from .models import OfferRedemption

    prior = prior_order_count(user) if any(r.max_prior_orders is not None for r in rules) else 0
    limited = [r.id for r in rules if r.per_customer_limit is not None]
    used: dict[int, int] = defaultdict(int)
    if limited:
        for offer_id in OfferRedemption.objects.filter(user=user, offer_id__in=limited).values_list(
            "offer_id", flat=True
        ):
            used[offer_id] += 1
    return [
        r
        for r in rules
        if (r.max_prior_orders is None or prior <= r.max_prior_orders)
        and (r.per_customer_limit is None or used[r.id] < r.per_customer_limit)
    ]


def apply_offers(lines: Sequence, offers: Iterable[OfferRule] | None = None, *, user=None) -> OfferResult:
    """Assign each line to its best offer and compute discounts.

    `lines` need: variant_id, product_id, category_id, subcategory_id, quantity, line_total (Decimal).
    """
    all_rules = sorted(load_active_offers() if offers is None else offers, key=lambda r: (r.priority, r.id))
    if not all_rules or not lines:
        return OfferResult()
    all_rules = eligible_for(all_rules, user)

    lineages: dict[int, frozenset[int] | None] = {line.variant_id: None for line in lines}
    if any(r.category_ids for r in all_rules):
        from apps.catalog.tree import lineage, parent_map

        parents = parent_map()
        lineages = {line.variant_id: lineage((line.category_id, line.subcategory_id), parents) for line in lines}

    def targets(rule: OfferRule, line) -> bool:
        return rule.matches(
            product_id=line.product_id,
            category_id=line.category_id,
            subcategory_id=line.subcategory_id,
            lineage=lineages[line.variant_id],
        )

    def enough_units(rule: OfferRule, line) -> bool:
        return getattr(line, "quantity", 0) >= rule.min_quantity

    result = OfferResult()
    rules = [r for r in all_rules if not r.is_free_delivery]
    candidates = {line.variant_id: [r for r in rules if targets(r, line) and enough_units(r, line)] for line in lines}
    disqualified: set[int] = set()
    assignment: dict[int, list] = defaultdict(list)
    while rules:
        assignment = defaultdict(list)
        for line in lines:
            best = next((r for r in candidates[line.variant_id] if r.id not in disqualified), None)
            if best is not None:
                assignment[best.id].append(line)
        rules_by_id = {r.id: r for r in rules}
        newly_out = {
            rule_id
            for rule_id, won in assignment.items()
            if sum((line.line_total for line in won), ZERO) < rules_by_id[rule_id].min_order_value
        }
        if not newly_out:
            break
        disqualified |= newly_out

    for rule in rules:
        won = assignment.get(rule.id, [])
        if not won:
            continue
        eligible = q(sum((line.line_total for line in won), ZERO))
        discount = rule.discount_for(eligible)
        if discount <= 0:
            continue
        _spread(discount, won, eligible, result.line_discounts)
        result.applied.append(
            AppliedOffer(
                offer=rule, discount=discount, eligible_amount=eligible, variant_ids=tuple(li.variant_id for li in won)
            )
        )

    # "Add ₹X more to unlock": offers that match something in the cart but missed their minimum.
    for rule in rules:
        if rule.id not in disqualified:
            continue
        eligible = q(sum((li.line_total for li in lines if rule in candidates[li.variant_id]), ZERO))
        if eligible < rule.min_order_value:
            result.missed.append(
                MissedOffer(offer=rule, eligible_amount=eligible, shortfall=q(rule.min_order_value - eligible))
            )
    # "Add N more of this item": quantity offers on lines just below the minimum (Phase 15).
    applied_ids = {a.offer.id for a in result.applied}
    for rule in rules:
        if rule.min_quantity <= 1 or rule.id in applied_ids or rule.id in disqualified:
            continue
        short = [rule.min_quantity - li.quantity for li in lines if targets(rule, li) and not enough_units(rule, li)]
        if short:
            result.missed.append(MissedOffer(offer=rule, eligible_amount=ZERO, shortfall=ZERO, units_short=min(short)))

    # Free-delivery offers: the best one whose qualifying lines reach its minimum.
    for rule in (r for r in all_rules if r.is_free_delivery):
        matching = [li for li in lines if targets(rule, li)]
        counted = [li for li in matching if enough_units(rule, li)]
        if not matching:
            continue
        eligible = q(sum((li.line_total for li in counted), ZERO))
        if counted and eligible >= rule.min_order_value:
            result.free_delivery = AppliedOffer(
                offer=rule, discount=ZERO, eligible_amount=eligible, variant_ids=tuple(li.variant_id for li in counted)
            )
            break
    if result.free_delivery is None:
        for rule in (r for r in all_rules if r.is_free_delivery):
            matching = [li for li in lines if targets(rule, li) and enough_units(rule, li)]
            eligible = q(sum((li.line_total for li in matching), ZERO))
            if matching and eligible < rule.min_order_value:
                result.missed.append(
                    MissedOffer(offer=rule, eligible_amount=eligible, shortfall=q(rule.min_order_value - eligible))
                )
    return result


def _spread(discount: Decimal, lines: list, eligible: Decimal, into: dict[int, Decimal]) -> None:
    """Allocate `discount` over `lines` pro rata to their totals; the last line takes the rounding remainder."""
    remaining = discount
    for index, line in enumerate(lines):
        share = remaining if index == len(lines) - 1 else q(discount * line.line_total / eligible)
        into[line.variant_id] = q(min(share, line.line_total))
        remaining -= into[line.variant_id]


def best_offer_for_product(product, offers: Sequence[OfferRule], parents=None) -> OfferRule | None:
    """Highest-priority live offer that targets this product (for badges on listings/detail pages).
    Discount offers first; a free-delivery offer only when no discount offer targets it."""
    lineage = None
    if parents is not None:
        from apps.catalog.tree import lineage as lineage_of

        lineage = lineage_of((product.category_id, product.subcategory_id), parents)
    ranked = sorted(offers, key=lambda r: (r.is_free_delivery, r.priority, r.id))
    for rule in ranked:
        if rule.matches(
            product_id=product.id,
            category_id=product.category_id,
            subcategory_id=product.subcategory_id,
            lineage=lineage,
        ):
            return rule
    return None
