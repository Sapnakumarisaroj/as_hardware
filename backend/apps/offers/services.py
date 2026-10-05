"""Coupon validation and discount calculation. Pure business rules; no request handling."""

from collections.abc import Iterable
from decimal import Decimal

from django.utils import timezone

from apps.catalog.tree import lineage, parent_map
from apps.core.exceptions import ServiceError
from apps.core.money import ZERO, q

from .models import Coupon, CouponRedemption, DiscountType


class CouponError(ServiceError):
    default_code = "invalid_coupon"
    default_detail = "This coupon code is not valid."


def get_valid_coupon(code: str, user, *, lock: bool = False) -> Coupon:
    """Return the coupon if it can be used by `user` right now, else raise CouponError."""
    normalized = (code or "").strip().upper()
    qs = Coupon.objects.select_for_update() if lock else Coupon.objects
    coupon = qs.filter(code=normalized).first() if normalized else None
    now = timezone.now()
    if coupon is None or not coupon.is_active:
        raise CouponError()
    if coupon.starts_at > now:
        raise CouponError("This coupon is not active yet.", code="coupon_not_started")
    if coupon.ends_at and coupon.ends_at <= now:
        raise CouponError("This coupon has expired.", code="coupon_expired")
    if coupon.usage_limit is not None and coupon.used_count >= coupon.usage_limit:
        raise CouponError("This coupon has reached its usage limit.", code="coupon_exhausted")
    if user is not None and user.is_authenticated:
        used = CouponRedemption.objects.filter(coupon=coupon, user=user).count()
        if used >= coupon.per_customer_limit:
            raise CouponError("You have already used this coupon.", code="coupon_already_used")
    return coupon


def coupon_discount(coupon: Coupon, lines: Iterable, subtotal: Decimal) -> Decimal:
    """Discount for the given priced lines (objects with product_id, category_id,
    subcategory_id and line_total). Never exceeds the eligible amount."""
    lines = list(lines)
    if subtotal < coupon.min_order_value:
        short = q(coupon.min_order_value - subtotal)
        raise CouponError(
            f"Add ₹{short} more to use this coupon (minimum order ₹{coupon.min_order_value}).",
            code="coupon_min_order",
            details={"min_order_value": str(coupon.min_order_value), "shortfall": str(short)},
        )

    product_ids = set(coupon.products.values_list("id", flat=True))
    category_ids = set(coupon.categories.values_list("id", flat=True))
    if product_ids or category_ids:
        # A category covers everything below it (department › category › subcategory).
        parents = parent_map() if category_ids else {}
        eligible = sum(
            (
                line.line_total
                for line in lines
                if line.product_id in product_ids
                or category_ids & lineage((line.category_id, line.subcategory_id), parents)
            ),
            ZERO,
        )
        if eligible <= 0:
            raise CouponError("This coupon doesn't apply to the items in your cart.", code="coupon_not_applicable")
    else:
        eligible = subtotal

    if coupon.discount_type == DiscountType.PERCENT:
        discount = q(eligible * coupon.value / 100)
        if coupon.max_discount_amount is not None:
            discount = min(discount, coupon.max_discount_amount)
    else:
        discount = coupon.value
    return q(min(discount, eligible))
