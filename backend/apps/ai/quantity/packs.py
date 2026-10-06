"""Pack optimisation (Phase 20): which real packs to buy for an amount.

Need 7.5 L, the product comes in 1 L, 4 L and 10 L: every combination of those packs that covers the need is
priced with the shop's pricing engine (`orders.pricing.line_from_variant`, so bulk tiers count) and the best
one is chosen by the business rule `QUANTITY_PACK_RULE`:

- `lowest_cost` (default): the cheapest combination that covers the need (fewer packs on a tie);
- `fewest_packs`: the fewest packs that cover the need (cheapest on a tie).

Combinations within the stock and the per-order limit always come first. Pack sizes are read from the
listing (`kit.pack_amount`); nothing is assumed about a variant whose size isn't written anywhere.
"""

import itertools
import math
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings

from apps.orders.pricing import line_from_variant

from .units import fmt

MAX_COMBINATIONS = 20_000
MAX_SIZES = 4  # pack sizes combined at once (the cheapest per unit are kept)
UNIT_LABEL = {"l": "L", "kg": "kg", "m": "m", "pcs": "pcs", "sqft": "sq ft", "cft": "cft"}


@dataclass
class Part:
    variant: object
    count: int
    size: float | None


@dataclass
class PackChoice:
    parts: list[Part]
    cost: Decimal
    covers: float | None  # total amount bought (None when a pack size is unknown)
    explanation: str = ""
    options: list[dict] = field(default_factory=list)  # the alternatives weighed: {label, cost, packs}

    @property
    def packs(self) -> int:
        return sum(p.count for p in self.parts)


def rule() -> str:
    value = getattr(settings, "QUANTITY_PACK_RULE", "lowest_cost")
    return value if value in ("lowest_cost", "fewest_packs") else "lowest_cost"


def pack_label(variant, size: float | None, unit: str) -> str:
    if size is None:
        return variant.name or variant.sku
    return f"{fmt(size, 2)} {UNIT_LABEL.get(unit, unit)}" if unit != "pcs" or size != 1 else (variant.name or "1 pc")


def describe(parts: list[Part], unit: str) -> str:
    return " + ".join(f"{p.count} × {pack_label(p.variant, p.size, unit)}" for p in parts if p.count)


def _cost(parts) -> Decimal:
    return sum((line_from_variant(p.variant, p.count).line_total for p in parts if p.count), Decimal("0"))


def optimise(
    options: list[tuple[object, float | None]], amount: float, unit: str, *, stock: dict, limit: int
) -> PackChoice | None:
    """options: (variant, pack size in `unit` or None). Returns the chosen combination, explained."""
    if not options:
        return None
    sized = [(v, s) for v, s in options if s]
    if not sized:  # no size written anywhere: one of the default (or cheapest) variant, flagged by the caller
        variant = next((v for v, _ in options if v.is_default), options[0][0])
        parts = [Part(variant, 1, None)]
        return PackChoice(parts, _cost(parts), None)
    amount = max(amount, 0.0)
    # keep the sizes with the lowest price per unit (at most MAX_SIZES), so the search stays small
    sized.sort(key=lambda o: (o[0].price / Decimal(str(o[1])), -o[1]))
    sized = sized[:MAX_SIZES]
    ranges = [range(0, max(1, math.ceil(round(amount / s, 6))) + 1) for _, s in sized]
    total = math.prod(len(r) for r in ranges)
    if total > MAX_COMBINATIONS:  # huge amounts: single pack sizes only
        combos = [
            tuple(n if i == j else 0 for j in range(len(sized))) for i in range(len(sized)) for n in [ranges[i][-1]]
        ]
    else:
        combos = itertools.product(*ranges)
    mode = rule()
    best, best_key, seen = None, None, []
    for counts in combos:
        if not any(counts):
            continue
        covered = sum(c * s for c, (_, s) in zip(counts, sized, strict=True))
        if covered + 1e-9 < amount:
            continue
        # no pointless packs: dropping any one pack must leave the need uncovered
        if any(c and covered - s + 1e-9 >= amount for c, (_, s) in zip(counts, sized, strict=True)):
            continue
        parts = [Part(v, c, s) for c, (v, s) in zip(counts, sized, strict=True) if c]
        cost = _cost(parts)
        packs = sum(counts)
        short = any(stock.get(p.variant.pk, 0) < p.count for p in parts)
        over = any(p.count > limit for p in parts)
        key = (over, short, cost, packs, covered) if mode == "lowest_cost" else (over, short, packs, cost, covered)
        seen.append((key, parts, cost, covered))
        if best_key is None or key < best_key:
            best, best_key = (parts, cost, covered), key
    if best is None:
        return None
    parts, cost, covered = best
    parts.sort(key=lambda p: -(p.size or 0))
    seen.sort(key=lambda row: row[0])
    others = [row for row in seen if row[1] is not parts][:2]
    choice = PackChoice(parts, cost, covered)
    choice.options = [
        {"label": describe(row[1], unit), "cost": f"{row[2]:.2f}", "packs": sum(p.count for p in row[1])}
        for row in seen[:3]
    ]
    rule_text = "cheapest way" if mode == "lowest_cost" else "fewest packs"
    others_text = "; ".join(f"{describe(row[1], unit)} = ₹{row[2]:,.0f}" for row in others)
    choice.explanation = (
        f"{describe(parts, unit)} = ₹{cost:,.0f} covers {fmt(amount)} {UNIT_LABEL.get(unit, unit)} ({rule_text}"
        + (f"; other options: {others_text}" if others_text else "")
        + ")."
    )
    return choice
