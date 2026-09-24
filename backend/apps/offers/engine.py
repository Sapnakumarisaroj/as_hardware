"""Automatic offers: discounts applied without a code.

Rules (documented in docs/ARCHITECTURE.md → Offers and coupons):

- An offer is live when `is_active` and `starts_at <= now < ends_at` (no end = open-ended).
- Targets: products and/or categories (a category also matches its subcategories). No targets = every line.
- One offer per cart line. Where several offers match a line, the lowest `priority` number wins
  (ties: the older offer, i.e. lower id), so admins control overlap explicitly.
- `min_order_value` is measured on the lines the offer won ("spend ₹2,000 on power tools"). An offer
  that misses its minimum releases its lines to the next-best matching offer; this repeats until stable.
- Percent: `eligible × value / 100`, capped by `max_discount_amount`. Fixed: `value`, never more than
  the eligible amount. The discount is spread over the offer's lines in proportion to their totals
  (rounding remainder on the last line), so tax can be computed per line on the net amount.
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

    @property
    def targets_everything(self) -> bool:
        return not self.product_ids and not self.category_ids

    def matches(self, *, product_id: int, category_id: int, subcategory_id: int | None) -> bool:
        if self.targets_everything:
            return True
        return (
            product_id in self.product_ids
            or category_id in self.category_ids
            or (subcategory_id is not None and subcategory_id in self.category_ids)
        )

    def discount_for(self, eligible: Decimal) -> Decimal:
        if eligible <= 0:
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
        """Short customer-facing label, e.g. "10% off" or "₹50 off"."""
        if self.discount_type == DiscountType.PERCENT:
            value = self.value.normalize()
            text = f"{value:f}% off"
            if self.max_discount_amount is not None:
                text += f" (up to ₹{self.max_discount_amount.normalize():f})"
            return text
        return f"₹{self.value.normalize():f} off"


@dataclass(frozen=True)
class AppliedOffer:
    offer: OfferRule
    discount: Decimal
    eligible_amount: Decimal
    variant_ids: tuple[int, ...]


@dataclass(frozen=True)
class MissedOffer:
    """An offer the cart matches but whose minimum spend isn't reached yet."""

    offer: OfferRule
    eligible_amount: Decimal
    shortfall: Decimal


@dataclass
class OfferResult:
    line_discounts: dict[int, Decimal] = field(default_factory=dict)  # variant_id → discount
    applied: list[AppliedOffer] = field(default_factory=list)
    missed: list[MissedOffer] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return q(sum((a.discount for a in self.applied), ZERO))


def load_active_offers(now=None) -> list[OfferRule]:
    now = now or timezone.now()
    offers = (
        Offer.objects.filter(is_active=True, starts_at__lte=now)
        .exclude(ends_at__isnull=False, ends_at__lte=now)
        .prefetch_related("products", "categories")
        .order_by("priority", "id")
    )
    return [
        OfferRule(
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
        )
        for o in offers
    ]


def apply_offers(lines: Sequence, offers: Iterable[OfferRule] | None = None) -> OfferResult:
    """Assign each line to its best offer and compute discounts.

    `lines` need: variant_id, product_id, category_id, subcategory_id, line_total (Decimal).
    """
    rules = sorted(load_active_offers() if offers is None else offers, key=lambda r: (r.priority, r.id))
    if not rules or not lines:
        return OfferResult()

    candidates = {
        line.variant_id: [
            rule
            for rule in rules
            if rule.matches(
                product_id=line.product_id, category_id=line.category_id, subcategory_id=line.subcategory_id
            )
        ]
        for line in lines
    }
    disqualified: set[int] = set()
    while True:
        assignment: dict[int, list] = defaultdict(list)
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

    result = OfferResult()
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
    return result


def _spread(discount: Decimal, lines: list, eligible: Decimal, into: dict[int, Decimal]) -> None:
    """Allocate `discount` over `lines` pro rata to their totals; the last line takes the rounding remainder."""
    remaining = discount
    for index, line in enumerate(lines):
        share = remaining if index == len(lines) - 1 else q(discount * line.line_total / eligible)
        into[line.variant_id] = q(min(share, line.line_total))
        remaining -= into[line.variant_id]


def best_offer_for_product(product, offers: Sequence[OfferRule]) -> OfferRule | None:
    """Highest-priority live offer that targets this product (for badges on listings/detail pages)."""
    for rule in sorted(offers, key=lambda r: (r.priority, r.id)):
        if rule.matches(product_id=product.id, category_id=product.category_id, subcategory_id=product.subcategory_id):
            return rule
    return None
