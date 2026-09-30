"""Automatic offers and coupons for the dashboard (administrators only).

These endpoints only store the *rules*. What a rule takes off a cart is calculated in one
place, `orders.pricing.price_lines` with `offers.engine` and `offers.services` (Phase 6); the
dashboard never calculates a discount.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers, viewsets

from apps.catalog.models import Category, Product
from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError
from apps.core.permissions import IsAdminRole
from apps.offers.models import Coupon, DiscountType, Offer

RULE_FIELDS = [
    "discount_type",
    "value",
    "max_discount_amount",
    "min_order_value",
    "starts_at",
    "ends_at",
    "is_active",
    "state",
    "summary",
    "products",
    "categories",
    "product_details",
    "category_details",
]


def rule_state(rule, now=None) -> str:
    """inactive | scheduled | expired | live"""
    now = now or timezone.now()
    if not rule.is_active:
        return "inactive"
    if rule.starts_at > now:
        return "scheduled"
    if rule.ends_at and rule.ends_at <= now:
        return "expired"
    return "live"


class _RuleSerializer(serializers.ModelSerializer):
    products = serializers.PrimaryKeyRelatedField(many=True, queryset=Product.objects.all(), required=False)
    categories = serializers.PrimaryKeyRelatedField(many=True, queryset=Category.objects.all(), required=False)
    product_details = serializers.SerializerMethodField()
    category_details = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    def get_product_details(self, obj) -> list[dict]:
        return [{"id": p.pk, "name": p.name, "sku": p.sku} for p in obj.products.all()]

    def get_category_details(self, obj) -> list[dict]:
        return [{"id": c.pk, "name": str(c)} for c in obj.categories.all()]

    def get_state(self, obj) -> str:
        return rule_state(obj)

    def get_summary(self, obj) -> str:
        """The rule in words, e.g. "10% off (up to ₹400) on Tools, from ₹1500"."""
        if obj.discount_type == DiscountType.PERCENT:
            text = f"{obj.value.normalize():f}% off"
            if obj.max_discount_amount:
                text += f" (up to ₹{obj.max_discount_amount.normalize():f})"
        else:
            text = f"₹{obj.value.normalize():f} off"
        targets = [c.name for c in obj.categories.all()] + [p.name for p in obj.products.all()]
        text += " on " + (", ".join(targets[:3]) + ("…" if len(targets) > 3 else "") if targets else "the whole cart")
        if obj.min_order_value:
            text += f", from ₹{obj.min_order_value.normalize():f}"
        return text

    def validate(self, attrs):
        values = {f: attrs.get(f, getattr(self.instance, f, None)) for f in
                  ("discount_type", "value", "max_discount_amount", "starts_at", "ends_at")}  # fmt: skip
        probe = self.Meta.model(**{k: v for k, v in values.items() if v is not None})
        try:
            probe.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        if values["discount_type"] == DiscountType.FIXED and values["max_discount_amount"]:
            raise serializers.ValidationError(
                {"max_discount_amount": "A cap only makes sense for percentage discounts."}
            )
        return attrs


class OfferSerializer(_RuleSerializer):
    class Meta:
        model = Offer
        fields = ["id", "name", "description", "priority", *RULE_FIELDS, "created_at", "updated_at"]


class CouponSerializer(_RuleSerializer):
    remaining_uses = serializers.SerializerMethodField()

    class Meta:
        model = Coupon
        fields = [
            "id",
            "code",
            "description",
            "usage_limit",
            "per_customer_limit",
            "used_count",
            "remaining_uses",
            "show_in_checkout",
            *RULE_FIELDS,
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["used_count"]

    def get_remaining_uses(self, obj) -> int | None:
        return None if obj.usage_limit is None else max(obj.usage_limit - obj.used_count, 0)

    def validate_code(self, value):
        code = value.strip().upper()
        if not code.replace("-", "").replace("_", "").isalnum():
            raise serializers.ValidationError("Use letters, digits, '-' and '_' only.")
        clash = Coupon.objects.filter(code=code)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("This code already exists.")
        return code

    def validate(self, attrs):
        attrs = super().validate(attrs)
        limit = attrs.get("usage_limit", getattr(self.instance, "usage_limit", None))
        if self.instance is not None and limit is not None and limit < self.instance.used_count:
            raise serializers.ValidationError(
                {"usage_limit": f"This coupon was already used {self.instance.used_count} times."}
            )
        return attrs


RULE_PARAMS = [
    OpenApiParameter("q", str),
    OpenApiParameter("state", str, enum=["live", "scheduled", "expired", "inactive"]),
]


class _RuleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminRole]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    search_fields: tuple[str, ...] = ()
    audit_name = ""

    def get_queryset(self):
        qs = self.serializer_class.Meta.model.objects.prefetch_related("products", "categories")
        params = self.request.query_params
        if term := (params.get("q") or "").strip():
            query = Q()
            for field in self.search_fields:
                query |= Q(**{f"{field}__icontains": term})
            qs = qs.filter(query)
        now = timezone.now()
        state = params.get("state")
        if state == "inactive":
            qs = qs.filter(is_active=False)
        elif state == "scheduled":
            qs = qs.filter(is_active=True, starts_at__gt=now)
        elif state == "expired":
            qs = qs.filter(is_active=True, ends_at__lte=now)
        elif state == "live":
            qs = qs.filter(is_active=True, starts_at__lte=now).filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        return qs

    def _audit(self, verb: str, target, changes=None):
        record_audit(
            action=f"{self.audit_name}.{verb}",
            actor=self.request.user,
            target=target,
            request=self.request,
            changes=changes,
        )

    def perform_create(self, serializer):
        self._audit("create", serializer.save())

    def perform_update(self, serializer):
        self._audit("update", serializer.save(), {"fields": sorted(serializer.validated_data)})


@extend_schema_view(list=extend_schema(parameters=RULE_PARAMS))
class AdminOfferViewSet(_RuleViewSet):
    serializer_class = OfferSerializer
    search_fields = ("name", "description")
    audit_name = "offer"

    def perform_destroy(self, instance):
        # Orders keep their own snapshot of the offers applied, so nothing else refers to the rule.
        self._audit("delete", instance, {"name": instance.name})
        instance.delete()


@extend_schema_view(list=extend_schema(parameters=RULE_PARAMS))
class AdminCouponViewSet(_RuleViewSet):
    serializer_class = CouponSerializer
    search_fields = ("code", "description")
    audit_name = "coupon"

    def perform_destroy(self, instance):
        if instance.used_count or instance.redemptions.exists():
            raise ConflictError(
                "This coupon has been used, so it is kept for the records. Deactivate it instead.",
                code="coupon_in_use",
            )
        self._audit("delete", instance, {"code": instance.code})
        try:
            instance.delete()
        except ProtectedError as exc:
            raise ConflictError("This coupon is still in use. Deactivate it instead.", code="coupon_in_use") from exc
