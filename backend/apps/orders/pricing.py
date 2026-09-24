"""Server-side price calculation shared by the cart and checkout. Client-sent prices are
never used: every total is derived from current catalog prices."""

from collections.abc import Iterable, Mapping
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

    @property
    def line_total(self) -> Decimal:
        return q(self.unit_price * self.quantity)

    @property
    def line_mrp_total(self) -> Decimal:
        return q(self.unit_mrp * self.quantity)


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

    @property
    def savings_vs_mrp(self) -> Decimal:
        return q(self.mrp_total - self.subtotal + self.discount_total)


def line_from_variant(variant, quantity: int) -> PricedLine:
    product = variant.product
    return PricedLine(
        variant_id=variant.id,
        product_id=product.id,
        category_id=product.category_id,
        subcategory_id=product.subcategory_id,
        unit_price=variant.price,
        unit_mrp=variant.mrp,
        gst_rate=product.gst_rate,
        quantity=quantity,
    )


def delivery_fee_for(amount_after_discount: Decimal) -> Decimal:
    if amount_after_discount <= 0:
        return ZERO
    if amount_after_discount >= settings.FREE_DELIVERY_MIN_ORDER:
        return ZERO
    return q(settings.DELIVERY_FEE)


def calculate_totals(
    lines: Iterable[PricedLine], discount: Decimal = ZERO, *, line_discounts: Mapping[int, Decimal] | None = None
) -> Totals:
    """Totals for priced lines.

    `line_discounts` (variant_id → amount) are automatic-offer discounts on specific lines.
    `discount` is the coupon, spread pro rata over what is left after offers. GST is included in
    prices, so each line's tax is computed on its own net amount.
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
    tax_total = q(sum((included_tax(nets[line.variant_id] * factor, line.gst_rate) for line in lines), ZERO))
    fee = delivery_fee_for(net)
    return Totals(
        subtotal=subtotal,
        mrp_total=mrp_total,
        discount_total=q(offer_discount + coupon),
        delivery_fee=fee,
        tax_total=tax_total,
        grand_total=q(net + fee),
        offer_discount=offer_discount,
        coupon_discount=coupon,
    )


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


def price_lines(lines: Iterable[PricedLine], *, coupon=None) -> Pricing:
    """The one pricing path for cart, checkout, coupon preview and order placement:
    automatic offers first, then the coupon on what remains. Raises CouponError if the
    coupon does not apply to these lines."""
    from apps.offers.engine import apply_offers
    from apps.offers.services import coupon_discount

    lines = list(lines)
    offers = apply_offers(lines)
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
    return Pricing(
        totals=calculate_totals(lines, discount, line_discounts=offers.line_discounts), offers=offers, coupon=coupon
    )
