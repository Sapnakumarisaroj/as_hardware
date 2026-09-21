from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.testing import create_category, create_coupon, create_product
from apps.offers.models import CouponRedemption
from apps.offers.services import CouponError, coupon_discount, get_valid_coupon
from apps.orders.pricing import line_from_variant

pytestmark = pytest.mark.django_db


def _codes(func):
    with pytest.raises(CouponError) as exc:
        func()
    return exc.value.error_code


def test_unknown_inactive_expired_future(user):
    create_coupon("OFF", is_active=False)
    create_coupon("OLD", ends_at=timezone.now() - timedelta(minutes=1))
    create_coupon("SOON", starts_at=timezone.now() + timedelta(days=1), ends_at=None)
    assert _codes(lambda: get_valid_coupon("NOPE", user)) == "invalid_coupon"
    assert _codes(lambda: get_valid_coupon("OFF", user)) == "invalid_coupon"
    assert _codes(lambda: get_valid_coupon("OLD", user)) == "coupon_expired"
    assert _codes(lambda: get_valid_coupon("SOON", user)) == "coupon_not_started"


def test_code_is_case_insensitive(user):
    create_coupon("SAVE10")
    assert get_valid_coupon("  save10 ", user).code == "SAVE10"


def test_usage_limits(user):
    total = create_coupon("ONCE", usage_limit=1, used_count=1)
    assert _codes(lambda: get_valid_coupon(total.code, user)) == "coupon_exhausted"


def test_per_customer_limit(user):
    from apps.orders.models import Order

    coupon = create_coupon("MINE", per_customer_limit=1)
    order = Order.objects.create(
        order_number="ODTEST1",
        user=user,
        address_snapshot={},
        payment_method="cod",
        subtotal=0,
        mrp_total=0,
        discount_total=0,
        delivery_fee=0,
        tax_total=0,
        grand_total=0,
    )
    CouponRedemption.objects.create(coupon=coupon, user=user, order=order, discount_amount=Decimal("10"))
    assert _codes(lambda: get_valid_coupon("MINE", user)) == "coupon_already_used"


def test_percentage_cap_fixed_and_minimum_order():
    _, variant = create_product(price="1000.00", mrp="1000.00")
    lines = [line_from_variant(variant, 2)]
    pct = create_coupon("PCT", value=Decimal("15"), max_discount_amount=Decimal("100"))
    assert coupon_discount(pct, lines, Decimal("2000.00")) == Decimal("100.00")
    fixed = create_coupon("FIX", discount_type="fixed", value=Decimal("5000"))
    assert coupon_discount(fixed, lines, Decimal("2000.00")) == Decimal("2000.00")  # never above eligible amount
    minimum = create_coupon("MIN", min_order_value=Decimal("2500"))
    with pytest.raises(CouponError) as exc:
        coupon_discount(minimum, lines, Decimal("2000.00"))
    assert exc.value.error_code == "coupon_min_order" and exc.value.details["shortfall"] == "500.00"


def test_category_restricted_coupon_only_counts_matching_lines():
    tools, plumbing = create_category("Tools"), create_category("Plumbing")
    drills = create_category("Drills", parent=tools)
    _, drill = create_product(price="1000.00", mrp="1000.00", category=tools, subcategory=drills)
    _, tap = create_product(price="500.00", mrp="500.00", category=plumbing)
    coupon = create_coupon("DRILLS", value=Decimal("10"))
    coupon.categories.add(drills)
    lines = [line_from_variant(drill, 1), line_from_variant(tap, 1)]
    assert coupon_discount(coupon, lines, Decimal("1500.00")) == Decimal("100.00")
    with pytest.raises(CouponError) as exc:
        coupon_discount(coupon, [line_from_variant(tap, 1)], Decimal("500.00"))
    assert exc.value.error_code == "coupon_not_applicable"


def test_coupon_preview_api(auth_client):
    _, variant = create_product(price="600.00", mrp="600.00", stock=5)
    auth_client.post("/api/cart/items/", {"variant_id": variant.id}, format="json")
    create_coupon("TENOFF", value=Decimal("10"))
    res = auth_client.post("/api/cart/coupon-preview/", {"code": "tenoff"}, format="json")
    assert res.status_code == 200
    assert res.json()["discount"] == "60.00"
    assert res.json()["totals"]["grand_total"] == "540.00"  # 600 - 60; still above the free-delivery threshold
