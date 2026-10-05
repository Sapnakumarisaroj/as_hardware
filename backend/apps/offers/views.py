from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Category, Product
from apps.core.exceptions import ServiceError
from apps.orders.pricing import price_lines

from .engine import load_active_offers
from .models import Coupon, DiscountType
from .services import get_valid_coupon


class _TargetSerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()


class OfferSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField()
    badge = serializers.CharField()
    min_order_value = serializers.DecimalField(max_digits=12, decimal_places=2)
    ends_at = serializers.DateTimeField(allow_null=True)
    applies_to_everything = serializers.BooleanField()
    categories = _TargetSerializer(many=True)
    products = _TargetSerializer(many=True)
    benefit = serializers.CharField(help_text="discount | free_delivery")
    min_quantity = serializers.IntegerField()
    campaign = serializers.CharField(allow_blank=True)
    conditions = serializers.ListField(child=serializers.CharField(), help_text="Conditions in words")


class LiveOffersView(APIView):
    """Promotions running now. They apply automatically in the cart — no code needed."""

    permission_classes = [AllowAny]

    @extend_schema(responses=OfferSerializer(many=True))
    def get(self, request):
        rules = load_active_offers()
        category_ids = {cid for r in rules for cid in r.category_ids}
        product_ids = {pid for r in rules for pid in r.product_ids}
        categories = {c.id: c for c in Category.objects.filter(id__in=category_ids, is_active=True)}
        products = {p.id: p for p in Product.objects.filter(id__in=product_ids, is_active=True, is_published=True)}
        rows = [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "badge": r.badge,
                "min_order_value": r.min_order_value,
                "ends_at": r.ends_at,
                "applies_to_everything": r.targets_everything,
                "categories": [
                    {"name": categories[c].name, "slug": categories[c].slug} for c in r.category_ids if c in categories
                ],
                "products": [
                    {"name": products[p].name, "slug": products[p].slug} for p in r.product_ids if p in products
                ],
                "benefit": r.benefit,
                "min_quantity": r.min_quantity,
                "campaign": r.campaign,
                "conditions": r.conditions,
            }
            for r in rules
        ]
        return Response(OfferSerializer(rows, many=True).data)


class AvailableCouponSerializer(serializers.Serializer):
    code = serializers.CharField()
    description = serializers.CharField()
    badge = serializers.CharField()
    min_order_value = serializers.DecimalField(max_digits=12, decimal_places=2)
    ends_at = serializers.DateTimeField(allow_null=True)
    applicable = serializers.BooleanField(help_text="Would apply to the current cart right now.")
    discount = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    message = serializers.CharField(allow_blank=True, help_text="Why it doesn't apply yet (if not applicable).")


def _coupon_badge(coupon: Coupon) -> str:
    if coupon.discount_type == DiscountType.PERCENT:
        text = f"{coupon.value.normalize():f}% off"
        if coupon.max_discount_amount is not None:
            text += f" (up to ₹{coupon.max_discount_amount.normalize():f})"
        return text
    return f"₹{coupon.value.normalize():f} off"


class AvailableCouponsView(APIView):
    """Coupons the store advertises (`show_in_checkout`), checked against the customer's cart.

    Only coupons this customer can still use are listed. Each says whether it applies to the
    cart now and, if not, why ("Add ₹120 more…"). Private codes are never listed.
    """

    @extend_schema(responses=AvailableCouponSerializer(many=True))
    def get(self, request):
        from apps.carts.services import summarize_cart

        now = timezone.now()
        coupons = (
            Coupon.objects.filter(is_active=True, show_in_checkout=True, starts_at__lte=now)
            .exclude(ends_at__isnull=False, ends_at__lte=now)
            .order_by("min_order_value", "code")
        )
        lines = summarize_cart(request.user).priced_lines
        rows = []
        for coupon in coupons:
            try:
                get_valid_coupon(coupon.code, request.user)  # usage limits etc. for this customer
            except ServiceError:
                continue  # not usable by this customer at all: don't advertise it
            row = {
                "code": coupon.code,
                "description": coupon.description,
                "badge": _coupon_badge(coupon),
                "min_order_value": coupon.min_order_value,
                "ends_at": coupon.ends_at,
                "applicable": False,
                "discount": None,
                "message": "",
            }
            if not lines:
                row["message"] = "Add items to your cart to use this coupon."
            else:
                try:
                    row["discount"] = price_lines(lines, coupon=coupon, user=request.user).totals.coupon_discount
                    row["applicable"] = True
                except ServiceError as exc:
                    row["message"] = str(exc.detail)
            rows.append(row)
        rows.sort(key=lambda r: (not r["applicable"], -(r["discount"] or 0)))
        return Response(AvailableCouponSerializer(rows, many=True).data)
