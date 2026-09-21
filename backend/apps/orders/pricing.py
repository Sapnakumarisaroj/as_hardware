"""Server-side price calculation shared by the cart and checkout. Client-sent prices are
never used: every total is derived from current catalog prices."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

from apps.core.money import ZERO, included_tax, q


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
    discount_total: Decimal
    delivery_fee: Decimal
    tax_total: Decimal
    grand_total: Decimal

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


def calculate_totals(lines: Iterable[PricedLine], discount: Decimal = ZERO) -> Totals:
    lines = list(lines)
    subtotal = q(sum((line.line_total for line in lines), ZERO))
    mrp_total = q(sum((line.line_mrp_total for line in lines), ZERO))
    discount = q(min(max(discount, ZERO), subtotal))
    net = subtotal - discount
    # GST is included in prices; a discount reduces each line's taxable value pro rata.
    factor = (net / subtotal) if subtotal else ZERO
    tax_total = q(sum((included_tax(line.line_total * factor, line.gst_rate) for line in lines), ZERO))
    fee = delivery_fee_for(net)
    return Totals(
        subtotal=subtotal,
        mrp_total=mrp_total,
        discount_total=discount,
        delivery_fee=fee,
        tax_total=tax_total,
        grand_total=q(net + fee),
    )
