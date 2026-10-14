"""Server-side price calculation shared by the cart and checkout. Client-sent prices are
never used: every total is derived from current catalog prices.

This is the one pricing engine (cart, checkout preview, coupon preview, order placement, the
product price quote and everything AI-driven that goes through those). Order of operations:

1. Unit price per line: the variant's price, or its bulk tier for the line's quantity
   (`tier_for`; Phase 15). A higher quantity never costs more per unit.
2. Automatic offers (`offers.engine`), one discount offer per line, plus free-delivery offers.
3. The coupon, on what is left after offers.
4. GST included in each line's net amount.
5. Delivery fee from the zone rule, waived by the zone's free-delivery threshold, a live
   `FreeDeliveryRule` or a free-delivery offer (`resolve_delivery`; Phase 15).
6. Credits (Phase 17), only when the customer chooses to use them: at most the shop's share of the
   goods after offers and coupon, spread over the lines like the coupon. They don't change the
   delivery decision (using credits never costs free delivery).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.conf import settings

from apps.core.money import ZERO, included_tax, q

if TYPE_CHECKING:
    from apps.offers.engine import OfferResult


@dataclass(frozen=True)
class PricedLine:
    variant_id: int
    product_id: int
    category_id: int
    subcategory_id: int | None
    unit_price: Decimal
    unit_mrp: Decimal
    gst_rate: Decimal
    quantity: int
    # Phase 15 bulk pricing: the variant's normal price when a tier lowered `unit_price`, the tier's
    # minimum quantity, and the next cheaper tier above the current quantity: (min_quantity, price).
    base_unit_price: Decimal | None = None
    tier_min_quantity: int | None = None
    next_tier: tuple[int, Decimal] | None = None

    @property
    def line_total(self) -> Decimal:
        return q(self.unit_price * self.quantity)

    @property
    def line_mrp_total(self) -> Decimal:
        return q(self.unit_mrp * self.quantity)

    @property
    def bulk_saving(self) -> Decimal:
        """What the tier saves on this line compared with the normal price."""
        if self.base_unit_price is None:
            return ZERO
        return q((self.base_unit_price - self.unit_price) * self.quantity)


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal
    mrp_total: Decimal
    discount_total: Decimal  # offers + coupon
    delivery_fee: Decimal
    tax_total: Decimal
    grand_total: Decimal
    offer_discount: Decimal = ZERO
    coupon_discount: Decimal = ZERO
    # Phase 15: why delivery is free, or how much more would make it free.
    free_delivery_reason: str = ""
    amount_to_free_delivery: Decimal = ZERO
    free_delivery_threshold: Decimal | None = None
    free_delivery_hint: str = ""
    bulk_savings: Decimal = ZERO
    # Phase 17: shop credit used on this order (already deducted from grand_total; not in discount_total).
    credit_discount: Decimal = ZERO
    # The delivery charge before any free-delivery rule (delivery_fee is what is charged).
    delivery_charge: Decimal = ZERO
    first_order_free_delivery: bool = False  # the waiver used one of the customer's first free orders
    unloading_fee: Decimal = ZERO  # optional unloading service (included in grand_total)
    # Cancellation fees the customer owes from earlier cancelled COD orders (included in grand_total).
    previous_cancellation_fees: Decimal = ZERO
    cancellation_fee_orders: tuple[str, ...] = ()  # their order numbers

    @property
    def delivery_discount(self) -> Decimal:
        return q(max(self.delivery_charge - self.delivery_fee, ZERO))

    @property
    def goods_after_discounts(self) -> Decimal:
        """Goods after offers and coupon, before credits: what the credit share is measured on."""
        return q(self.subtotal - self.discount_total)

    @property
    def savings_vs_mrp(self) -> Decimal:
        return q(self.mrp_total - self.subtotal + self.discount_total)

    @property
    def free_delivery(self) -> bool:
        return bool(self.free_delivery_reason)


# --- 1. Unit price (bulk tiers) ------------------------------------------------------------------


@dataclass(frozen=True)
class TierPrice:
    unit_price: Decimal
    tier_min_quantity: int | None  # None = the normal price
    next_tier: tuple[int, Decimal] | None


def price_tiers(variant) -> list[tuple[int, Decimal]]:
    """(min_quantity, unit_price) sorted by quantity. Uses prefetched `price_tiers` when present."""
    return sorted((t.min_quantity, t.unit_price) for t in variant.price_tiers.all())


def tier_for(variant, quantity: int, tiers: Sequence[tuple[int, Decimal]] | None = None) -> TierPrice:
    """The unit price for `quantity` units. Defensive: a tier never raises the price above the
    normal price or a lower tier, even if bad data slipped past validation."""
    tiers = price_tiers(variant) if tiers is None else tiers
    price, applied = variant.price, None
    for min_quantity, tier_price in tiers:
        if quantity >= min_quantity and tier_price < price:
            price, applied = tier_price, min_quantity
    upcoming = next(((m, p) for m, p in tiers if m > quantity and p < price), None)
    return TierPrice(price, applied, upcoming)


def line_from_variant(variant, quantity: int) -> PricedLine:
    product = variant.product
    tier = tier_for(variant, quantity)
    return PricedLine(
        variant_id=variant.id,
        product_id=product.id,
        category_id=product.category_id,
        subcategory_id=product.subcategory_id,
        unit_price=tier.unit_price,
        unit_mrp=variant.mrp,
        gst_rate=product.gst_rate,
        quantity=quantity,
        base_unit_price=variant.price if tier.tier_min_quantity is not None else None,
        tier_min_quantity=tier.tier_min_quantity,
        next_tier=tier.next_tier,
    )


def line_from_quote_item(item) -> PricedLine:
    """A quotation line (quotes.QuoteItem): the staff-quoted unit price for the agreed quantity.
    `base_unit_price` keeps the catalogue price so savings and refunds stay explainable."""
    variant = item.variant
    product = variant.product
    unit_price = item.quoted_unit_price
    return PricedLine(
        variant_id=variant.id,
        product_id=product.id,
        category_id=product.category_id,
        subcategory_id=product.subcategory_id,
        unit_price=unit_price,
        unit_mrp=variant.mrp,
        gst_rate=product.gst_rate,
        quantity=item.quantity,
        base_unit_price=variant.price if unit_price < variant.price else None,
    )


# --- 5. Delivery fee -----------------------------------------------------------------------------


def delivery_fee_for(amount_after_discount: Decimal, fee_rule=None) -> Decimal:
    """`fee_rule` (apps.delivery.fulfillment.FeeRule) comes from the delivery zone; None = global settings.
    The basic rule only; `resolve_delivery` adds free-delivery rules and offers."""
    fee = fee_rule.fee if fee_rule else q(settings.DELIVERY_FEE)
    free_min = fee_rule.free_min if fee_rule else settings.FREE_DELIVERY_MIN_ORDER
    if amount_after_discount <= 0 or amount_after_discount >= free_min:
        return ZERO
    return q(fee)


@dataclass(frozen=True)
class FreeDeliveryTarget:
    """A live free-delivery rule as the engine sees it (loaded by `load_free_delivery_rules`)."""

    id: int
    name: str
    threshold: Decimal
    zone_ids: frozenset[int]
    product_ids: frozenset[int]
    category_ids: frozenset[int]
    scope_label: str = ""  # "Cement" — for "Add ₹X more of Cement"

    @property
    def targets_everything(self) -> bool:
        return not self.product_ids and not self.category_ids


@dataclass(frozen=True)
class DeliveryDecision:
    fee: Decimal
    free_reason: str = ""
    amount_to_free: Decimal = ZERO
    threshold: Decimal | None = None
    hint: str = ""
    charge: Decimal = ZERO  # the fee before free-delivery rules
    first_order: bool = False


def first_order_waiver(user) -> str:
    """Why delivery is free under the "first N orders" rule for this customer, or "" if it doesn't apply.
    Counted from orders that used the waiver and weren't cancelled (a cancelled or unpaid-and-expired
    order gives the free delivery back; a retried payment stays on the same order)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return ""
    from apps.delivery.models import DeliveryCharges

    from .models import Order, OrderStatus

    limit = DeliveryCharges.load().free_first_orders
    if not limit:
        return ""
    used = Order.objects.filter(user=user, first_order_free_delivery=True).exclude(status=OrderStatus.CANCELLED).count()
    if used >= limit:
        return ""
    return f"Free delivery on your first {limit} orders ({used + 1} of {limit})"


def outstanding_cancellation_fees(user) -> tuple[Decimal, tuple[str, ...]]:
    """(amount, order numbers) of the customer's cancellation fees not yet added to another order."""
    if user is None or not getattr(user, "is_authenticated", False):
        return ZERO, ()
    from .models import Order, OrderStatus

    owed = list(
        Order.objects.filter(
            user=user, status=OrderStatus.CANCELLED, cancellation_fee__gt=0, cancellation_fee_collected_on__isnull=True
        )
        .order_by("created_at")
        .values_list("order_number", "cancellation_fee")
    )
    return q(sum((fee for _, fee in owed), ZERO)), tuple(number for number, _ in owed)


def load_free_delivery_rules(zone_id: int | None, now=None) -> list[FreeDeliveryTarget]:
    from django.db.models import Q
    from django.utils import timezone

    from apps.delivery.models import FreeDeliveryRule

    now = now or timezone.now()
    rows = (
        FreeDeliveryRule.objects.filter(is_active=True, starts_at__lte=now)
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .prefetch_related("zones", "products", "categories")
        .order_by("threshold", "id")
    )
    rules = []
    for row in rows:
        zone_ids = frozenset(z.id for z in row.zones.all())
        if zone_ids and zone_id not in zone_ids:
            continue
        names = [c.name for c in row.categories.all()] + [p.name for p in row.products.all()]
        rules.append(
            FreeDeliveryTarget(
                id=row.id,
                name=row.name,
                threshold=q(row.threshold),
                zone_ids=zone_ids,
                product_ids=frozenset(p.id for p in row.products.all()),
                category_ids=frozenset(c.id for c in row.categories.all()),
                scope_label=", ".join(names[:2]) + ("…" if len(names) > 2 else ""),
            )
        )
    return rules


def _line_matches(line, product_ids: frozenset, category_ids: frozenset, parents) -> bool:
    if line.product_id in product_ids:
        return True
    if not category_ids:
        return False
    from apps.catalog.tree import lineage

    return bool(category_ids & lineage((line.category_id, line.subcategory_id), parents))


def resolve_delivery(
    lines: Sequence[PricedLine],
    nets: Mapping[int, Decimal],
    net_total: Decimal,
    fee_rule=None,
    *,
    rules: Sequence[FreeDeliveryTarget] = (),
    free_delivery_offer=None,
    first_order_reason: str = "",
) -> DeliveryDecision:
    decision = _resolve_delivery(lines, nets, net_total, fee_rule, rules=rules, free_delivery_offer=free_delivery_offer)
    if decision.fee > 0 and first_order_reason:
        return DeliveryDecision(ZERO, free_reason=first_order_reason, charge=decision.fee, first_order=True)
    return decision


def _resolve_delivery(
    lines: Sequence[PricedLine],
    nets: Mapping[int, Decimal],
    net_total: Decimal,
    fee_rule=None,
    *,
    rules: Sequence[FreeDeliveryTarget] = (),
    free_delivery_offer=None,
) -> DeliveryDecision:
    """The delivery fee, and why it is free or how much more would make it free.

    Candidates for free delivery: the zone's (or global) threshold on the whole order, each live
    `FreeDeliveryRule` on its qualifying lines, and an applied free-delivery offer. Amounts are
    after offers and coupon (`nets`, variant_id → net amount).
    """
    fee = fee_rule.fee if fee_rule else q(settings.DELIVERY_FEE)
    base_min = fee_rule.free_min if fee_rule else q(settings.FREE_DELIVERY_MIN_ORDER)
    if net_total <= 0 or q(fee) <= 0:
        return DeliveryDecision(ZERO)
    if free_delivery_offer is not None:
        return DeliveryDecision(ZERO, free_reason=free_delivery_offer.offer.name, charge=q(fee))
    if net_total >= base_min:
        return DeliveryDecision(ZERO, free_reason=f"Orders from ₹{base_min.normalize():f}", charge=q(fee))

    parents = None
    if any(r.category_ids for r in rules):
        from apps.catalog.tree import parent_map

        parents = parent_map()
    # (shortfall, threshold, hint) of every rule that could still be reached.
    reachable = [(q(base_min - net_total), base_min, "")]
    for rule in rules:
        if rule.targets_everything:
            eligible, relevant = net_total, True
        else:
            matching = [li for li in lines if _line_matches(li, rule.product_ids, rule.category_ids, parents)]
            eligible, relevant = q(sum((nets.get(li.variant_id, ZERO) for li in matching), ZERO)), bool(matching)
        if eligible > 0 and eligible >= rule.threshold:
            return DeliveryDecision(ZERO, free_reason=rule.name, charge=q(fee))
        if relevant:
            hint = "" if rule.targets_everything else rule.scope_label
            reachable.append((q(rule.threshold - eligible), rule.threshold, hint))
    shortfall, threshold, hint = min(reachable, key=lambda r: r[0])
    return DeliveryDecision(q(fee), amount_to_free=shortfall, threshold=threshold, hint=hint, charge=q(fee))


# --- 3./4. Totals --------------------------------------------------------------------------------


def calculate_totals(
    lines: Iterable[PricedLine],
    discount: Decimal = ZERO,
    *,
    line_discounts: Mapping[int, Decimal] | None = None,
    fee_rule=None,
    free_delivery_rules: Sequence[FreeDeliveryTarget] = (),
    free_delivery_offer=None,
    credits: Decimal = ZERO,
    first_order_reason: str = "",
    unloading_fee: Decimal = ZERO,
    cancellation_fees: tuple[Decimal, tuple[str, ...]] = (ZERO, ()),
) -> Totals:
    """Totals for priced lines.

    `line_discounts` (variant_id → amount) are automatic-offer discounts on specific lines.
    `discount` is the coupon, spread pro rata over what is left after offers. `credits` (already
    capped by the caller) come off after the coupon in the same way. GST is included in prices, so
    each line's tax is computed on its own net amount.
    """
    lines = list(lines)
    line_discounts = line_discounts or {}
    subtotal = q(sum((line.line_total for line in lines), ZERO))
    mrp_total = q(sum((line.line_mrp_total for line in lines), ZERO))
    nets = {
        line.variant_id: line.line_total - min(line_discounts.get(line.variant_id, ZERO), line.line_total)
        for line in lines
    }
    offer_discount = q(subtotal - sum(nets.values(), ZERO))
    after_offers = subtotal - offer_discount
    coupon = q(min(max(discount, ZERO), after_offers))
    net = after_offers - coupon
    factor = (net / after_offers) if after_offers else ZERO
    final_nets = {variant_id: amount * factor for variant_id, amount in nets.items()}
    delivery = resolve_delivery(
        lines,
        final_nets,
        net,
        fee_rule,
        rules=free_delivery_rules,
        free_delivery_offer=free_delivery_offer,
        first_order_reason=first_order_reason,
    )
    unloading = q(unloading_fee) if net > 0 else ZERO
    owed, owed_orders = cancellation_fees if net > 0 else (ZERO, ())
    credit = q(min(max(credits, ZERO), net))
    paid_factor = ((net - credit) / after_offers) if after_offers else ZERO
    tax_total = q(sum((included_tax(nets[line.variant_id] * paid_factor, line.gst_rate) for line in lines), ZERO))
    net -= credit
    return Totals(
        subtotal=subtotal,
        mrp_total=mrp_total,
        discount_total=q(offer_discount + coupon),
        delivery_fee=delivery.fee,
        tax_total=tax_total,
        grand_total=q(net + delivery.fee + unloading + owed),
        offer_discount=offer_discount,
        coupon_discount=coupon,
        free_delivery_reason=delivery.free_reason,
        amount_to_free_delivery=delivery.amount_to_free,
        free_delivery_threshold=delivery.threshold,
        free_delivery_hint=delivery.hint,
        bulk_savings=q(sum((line.bulk_saving for line in lines), ZERO)),
        credit_discount=credit,
        delivery_charge=delivery.charge,
        first_order_free_delivery=delivery.first_order,
        unloading_fee=unloading,
        previous_cancellation_fees=q(owed),
        cancellation_fee_orders=tuple(owed_orders),
    )


def paid_by_line(lines: Sequence[PricedLine], totals: Totals, line_discounts: Mapping[int, Decimal]) -> dict:
    """variant_id → what the customer pays for the goods of each line after offers, coupon and
    credits (coupon and credits spread pro rata, as in `calculate_totals`). Used for cashback."""
    nets = {
        line.variant_id: line.line_total - min(line_discounts.get(line.variant_id, ZERO), line.line_total)
        for line in lines
    }
    after_offers = sum(nets.values(), ZERO)
    if not after_offers:
        return dict.fromkeys(nets, ZERO)
    paid_goods = after_offers - totals.coupon_discount - totals.credit_discount
    return {variant_id: q(amount * paid_goods / after_offers) for variant_id, amount in nets.items()}


@dataclass(frozen=True)
class NetLine:
    """A line as the coupon engine sees it: after automatic offers."""

    variant_id: int
    product_id: int
    category_id: int
    subcategory_id: int | None
    line_total: Decimal


@dataclass(frozen=True)
class Pricing:
    totals: Totals
    offers: "OfferResult"
    coupon: object | None = None  # offers.models.Coupon
    credits: object | None = None  # loyalty.ledger.CreditQuote (signed-in customers)


def price_lines(
    lines: Iterable[PricedLine],
    *,
    coupon=None,
    fee_rule=None,
    user=None,
    use_credits: bool = False,
    automatic_offers: bool = True,
    unloading: bool = False,
) -> Pricing:
    """The one pricing path for cart, checkout, coupon preview and order placement:
    automatic offers first, then the coupon on what remains, then (when `use_credits`) the
    customer's credits up to the shop's share. Raises CouponError if the coupon does not apply
    to these lines. `user` decides customer-specific offers (first order, per-customer limits)
    and whose credits; None = a visitor. `automatic_offers=False` is for quotation orders: the
    quoted price is the negotiated price, so offers don't stack on it (callers pass no coupon)."""
    from apps.offers.engine import OfferResult, apply_offers
    from apps.offers.services import coupon_discount

    lines = list(lines)
    offers = apply_offers(lines, user=user) if automatic_offers else OfferResult()
    discount = ZERO
    if coupon is not None:
        net_lines = [
            NetLine(
                line.variant_id,
                line.product_id,
                line.category_id,
                line.subcategory_id,
                line.line_total - offers.line_discounts.get(line.variant_id, ZERO),
            )
            for line in lines
        ]
        discount = coupon_discount(coupon, net_lines, q(sum((n.line_total for n in net_lines), ZERO)))
    rules = load_free_delivery_rules(getattr(fee_rule, "zone_id", None)) if lines else []
    first_order_reason = first_order_waiver(user) if lines else ""
    owed = outstanding_cancellation_fees(user) if lines else (ZERO, ())
    unloading_fee = ZERO
    if unloading and getattr(fee_rule, "unloading_available", False):
        from apps.delivery.models import DeliveryCharges

        unloading_fee = q(DeliveryCharges.load().unloading_fee)

    def totals_with(credits: Decimal) -> Totals:
        return calculate_totals(
            lines,
            discount,
            line_discounts=offers.line_discounts,
            fee_rule=fee_rule,
            free_delivery_rules=rules,
            free_delivery_offer=offers.free_delivery,
            credits=credits,
            first_order_reason=first_order_reason,
            unloading_fee=unloading_fee,
            cancellation_fees=owed,
        )

    totals = totals_with(ZERO)
    credit_quote = None
    if user is not None and getattr(user, "is_authenticated", False) and lines:
        from apps.loyalty.ledger import credit_quote as quote_credits

        credit_quote = quote_credits(user, totals.goods_after_discounts)  # the 20 % cap is measured here
        if use_credits and credit_quote.usable > 0:
            totals = totals_with(credit_quote.usable)
    return Pricing(totals=totals, offers=offers, coupon=coupon, credits=credit_quote)
