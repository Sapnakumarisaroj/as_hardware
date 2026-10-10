"""Smart shopping API (Phase 22).

Customers (read-only; nothing here changes a cart except the explicit bundle "add to cart"):
- `GET  /api/shopping/recommendations/?product=&variant=&budget=`  product-page groups; without `product`, the
                                                                  home-page groups (personal only from own history)
- `GET  /api/shopping/cart/?postal_code=&budget=`                 smart-cart analysis of the signed-in cart
- `POST /api/shopping/budget/`                                    a plan within a stated budget
- `GET  /api/shopping/bundles/?product=`                          live bundles (priced by the pricing engine)
- `POST /api/shopping/bundles/{slug}/price/`                      a bundle with the customer's edits, priced
- `POST /api/shopping/bundles/{slug}/add-to-cart/`                the ticked items into the cart, all or nothing

Staff (administrators; every change audited):
- `/api/admin/bundles/` (+ `{id}/preview/`) · `/api/admin/recommendation-rules/`
"""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Prefetch
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.ai.project_views import attach_cards, location_params
from apps.catalog.compatibility_views import cards
from apps.catalog.models import Category, Product, ProductVariant
from apps.core.audit import record_audit
from apps.core.permissions import IsAdminRole

from .models import Bundle, BundleItem, RecommendationRule
from .services import bundles as bundle_service
from .services.budget import BudgetPlanner
from .services.recommendations import RecommendationService
from .services.smart_cart import SmartCartService

LANGUAGES = ["en", "hi", "hinglish"]


def _decimal(raw) -> Decimal | None:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if Decimal("0") < value < Decimal("100000000") else None


def _with_cards(groups: dict, request) -> dict:
    """Product cards (live catalogue rows) for every suggestion; a product that just went off sale disappears."""
    ids = {row["product_id"] for rows in groups.values() for row in rows}
    found = cards(ids, request)
    return {
        name: [{**row, "product": found[row["product_id"]]} for row in rows if row["product_id"] in found]
        for name, rows in groups.items()
    }


# --- Customers -------------------------------------------------------------------------------------------


class RecommendationsView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("product", int),
            OpenApiParameter("variant", int),
            OpenApiParameter("budget", str),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        params = request.query_params
        service = RecommendationService()
        product = params.get("product") or ""
        if product.isdigit():
            variant = params.get("variant") or ""
            data = service.for_product(
                int(product),
                variant_id=int(variant) if variant.isdigit() else None,
                budget=_decimal(params.get("budget")),
            )
            data["bundles"] = [bundle_service.summary(b) for b in bundle_service.bundles_with([int(product)])]
        else:
            data = service.for_home(request.user)
        data["groups"] = _with_cards(data["groups"], request)
        return Response(data)


class SmartCartView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("postal_code", str), OpenApiParameter("budget", str)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        location = location_params(request)
        data = SmartCartService().analyze(request.user, budget=_decimal(request.query_params.get("budget")), **location)
        ids = set()
        for section in data["sections"]:
            for item in section["items"]:
                if item.get("product_id"):
                    ids.add(item["product_id"])
                ids.update(o["product_id"] for o in item.get("options", []))
                ids.update(a["product_id"] for a in item.get("alternatives", []))
                ids.update(line["product_id"] for line in item.get("lines", []))
        found = cards(ids, request)
        for section in data["sections"]:
            for item in section["items"]:
                item["product"] = found.get(item.get("product_id"))
                for option in item.get("options", []):
                    option["product"] = found.get(option["product_id"])
                for line in item.get("lines", []):  # "complete the set": a line that went off sale is dropped
                    line["product"] = found.get(line["product_id"])
                if item.get("lines"):
                    item["lines"] = [line for line in item["lines"] if line["product"]]
        return Response(data)


class BudgetSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500, required=False, allow_blank=True, trim_whitespace=True)
    budget = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("1"), required=False)
    calculator = serializers.CharField(max_length=40, required=False, allow_blank=True)
    answers = serializers.DictField(required=False)
    language = serializers.ChoiceField(choices=LANGUAGES, required=False)
    postal_code = serializers.RegexField(r"^\d{6}$", required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get("text") and not attrs.get("calculator"):
            raise serializers.ValidationError("Describe what you need or choose a calculator.")
        return attrs


class BudgetView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai"

    @extend_schema(request=BudgetSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = BudgetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = BudgetPlanner().plan(
            text=data.get("text", ""),
            budget=data.get("budget"),
            calculator=data.get("calculator", ""),
            answers=data.get("answers") or {},
            language=data.get("language", ""),
            user=request.user,
            postal_code=data.get("postal_code") or "",
        )
        attach_cards(result.get("kit"), request)
        found = cards(
            {
                row["product_id"]
                for key in ("cheaper_options", "premium_options", "best_for_budget")
                for row in result.get(key, [])
            },
            request,
        )
        for key in ("cheaper_options", "premium_options", "best_for_budget"):
            if key in result:
                result[key] = [
                    {**row, "product": found[row["product_id"]]} for row in result[key] if row["product_id"] in found
                ]
        return Response(result)


class BundleEditSerializer(serializers.Serializer):
    overrides = serializers.DictField(child=serializers.DictField(), required=False)
    postal_code = serializers.RegexField(r"^\d{6}$", required=False, allow_blank=True)
    only_missing = serializers.BooleanField(required=False, default=False)


class BundleListView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(parameters=[OpenApiParameter("product", int)], responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        product = request.query_params.get("product") or ""
        rows = (
            bundle_service.bundles_with([int(product)], limit=10)
            if product.isdigit()
            else list(bundle_service.live_bundles()[:30])
        )
        return Response({"results": [bundle_service.summary(b) for b in rows]})


class BundlePriceView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=BundleEditSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, slug: str):
        serializer = BundleEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bundle = bundle_service.get_live(slug)
        user = request.user if request.user.is_authenticated else None
        location = location_params(request)
        data = bundle_service.price(
            bundle,
            user=user,
            overrides=serializer.validated_data.get("overrides") or {},
            postal_code=location["postal_code"],
            address_id=location["address_id"] if user else None,
        )
        attach_cards(data["kit"], request)
        return Response(data)


class BundleAddToCartView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=BundleEditSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, slug: str):
        serializer = BundleEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bundle = bundle_service.get_live(slug)
        data = serializer.validated_data
        return Response(
            bundle_service.add_to_cart(
                bundle, user=request.user, overrides=data.get("overrides") or {}, only_missing=data["only_missing"]
            )
        )


# --- Staff -----------------------------------------------------------------------------------------------


class BundleItemInputSerializer(serializers.Serializer):
    product = serializers.IntegerField(min_value=1)
    variant = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1, max_value=999, default=1)
    note = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    is_optional = serializers.BooleanField(required=False, default=False)


class AdminBundleSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    item_rows = BundleItemInputSerializer(many=True, write_only=True, required=False, max_length=40)
    state = serializers.SerializerMethodField()

    class Meta:
        model = Bundle
        fields = [
            "id",
            "name",
            "slug",
            "kind",
            "description",
            "promo_label",
            "is_active",
            "starts_at",
            "ends_at",
            "priority",
            "items",
            "item_rows",
            "state",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"slug": {"required": False}}

    def get_items(self, obj) -> list[dict]:
        return [
            {
                "id": i.pk,
                "product": i.product_id,
                "name": i.product.name,
                "variant": i.variant_id,
                "variant_name": i.variant.name if i.variant else "",
                "quantity": i.quantity,
                "note": i.note,
                "is_optional": i.is_optional,
                "live": i.product.is_purchasable,
            }
            for i in obj.items.all()
        ]

    def get_state(self, obj) -> str:
        from django.utils import timezone

        now = timezone.now()
        if not obj.is_active:
            return "inactive"
        if obj.starts_at and obj.starts_at > now:
            return "scheduled"
        if obj.ends_at and obj.ends_at <= now:
            return "expired"
        return "live"

    def validate(self, attrs):
        starts = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_at": "End must be after start."})
        rows = attrs.get("item_rows")
        if rows is not None:
            ids = [r["product"] for r in rows]
            if len(set(ids)) != len(ids):
                raise serializers.ValidationError({"item_rows": "A product is listed twice."})
            found = set(Product.objects.filter(pk__in=ids, is_deleted=False).values_list("pk", flat=True))
            if missing := [i for i in ids if i not in found]:
                raise serializers.ValidationError({"item_rows": f"Unknown products: {missing[:5]}"})
            for row in rows:
                if (
                    row.get("variant")
                    and not ProductVariant.objects.filter(pk=row["variant"], product_id=row["product"]).exists()
                ):
                    raise serializers.ValidationError(
                        {"item_rows": f"Variant {row['variant']} isn't a variant of product {row['product']}."}
                    )
        if self.instance is None and not rows:
            raise serializers.ValidationError({"item_rows": "Add the products of this bundle."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        from django.utils.text import slugify

        rows = validated_data.pop("item_rows", [])
        if not validated_data.get("slug"):
            base = slugify(validated_data["name"])[:120] or "bundle"
            slug, n = base, 2
            while Bundle.objects.filter(slug=slug).exists():
                slug, n = f"{base}-{n}", n + 1
            validated_data["slug"] = slug
        bundle = Bundle.objects.create(created_by=self.context["request"].user, **validated_data)
        self._set_items(bundle, rows)
        return bundle

    @transaction.atomic
    def update(self, instance, validated_data):
        rows = validated_data.pop("item_rows", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if rows is not None:
            self._set_items(instance, rows)
        return instance

    @staticmethod
    def _set_items(bundle, rows):
        bundle.items.all().delete()
        BundleItem.objects.bulk_create(
            [
                BundleItem(
                    bundle=bundle,
                    product_id=r["product"],
                    variant_id=r.get("variant"),
                    quantity=r["quantity"],
                    note=r.get("note", ""),
                    is_optional=r.get("is_optional", False),
                    sort_order=pos,
                )
                for pos, r in enumerate(rows)
            ]
        )


def _items(bundle) -> list:
    return [
        {"product": i.product_id, "variant": i.variant_id, "quantity": i.quantity, "optional": i.is_optional}
        for i in bundle.items.all()
    ]


class AdminBundleViewSet(viewsets.ModelViewSet):
    """Bundles of real catalogue products (administrators only; every change audited)."""

    permission_classes = [IsAdminRole]
    serializer_class = AdminBundleSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        items = (
            BundleItem.objects.select_related("product", "variant__product")
            .prefetch_related("product__variants")
            .order_by("sort_order", "id")
        )
        return Bundle.objects.prefetch_related(Prefetch("items", queryset=items)).order_by("priority", "name")

    def perform_create(self, serializer):
        bundle = serializer.save()
        record_audit(
            action="bundle.create",
            actor=self.request.user,
            target=bundle,
            request=self.request,
            changes={"items": _items(bundle)},
        )

    def perform_update(self, serializer):
        before = _items(serializer.instance)
        bundle = serializer.save()
        changes = {"fields": sorted(k for k in serializer.validated_data if k != "item_rows")}
        if "item_rows" in serializer.validated_data:
            changes["items"] = {"before": before, "after": _items(Bundle.objects.get(pk=bundle.pk))}
        record_audit(
            action="bundle.update", actor=self.request.user, target=bundle, request=self.request, changes=changes
        )

    def perform_destroy(self, instance):
        record_audit(
            action="bundle.delete",
            actor=self.request.user,
            target=instance,
            request=self.request,
            changes={"name": instance.name, "items": _items(instance)},
        )
        instance.delete()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        """The bundle as customers would see it now: priced, stock and compatibility checked."""
        bundle = self.get_object()
        data = bundle_service.price(bundle)
        attach_cards(data["kit"], request)
        data["is_live"] = bundle.is_live()
        return Response(data)


class AdminRecommendationRuleSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source_category.name", read_only=True)
    target_name = serializers.CharField(source="target_category.name", read_only=True)
    source_category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    target_category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())

    class Meta:
        model = RecommendationRule
        fields = [
            "id",
            "source_category",
            "source_name",
            "target_category",
            "target_name",
            "label",
            "priority",
            "is_active",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        source = attrs.get("source_category", getattr(self.instance, "source_category", None))
        target = attrs.get("target_category", getattr(self.instance, "target_category", None))
        if source and target and source.pk == target.pk:
            raise serializers.ValidationError({"target_category": "Choose a different category."})
        clash = RecommendationRule.objects.filter(source_category=source, target_category=target)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError({"target_category": "This rule already exists."})
        return attrs


class AdminRecommendationRuleViewSet(viewsets.ModelViewSet):
    """ "Complete the project" rules: category → category (administrators only; audited)."""

    permission_classes = [IsAdminRole]
    serializer_class = AdminRecommendationRuleSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return RecommendationRule.objects.select_related("source_category", "target_category").order_by(
            "priority", "id"
        )

    def perform_create(self, serializer):
        rule = serializer.save()
        record_audit(
            action="recommendation_rule.create",
            actor=self.request.user,
            target=rule,
            request=self.request,
            changes={"source": rule.source_category_id, "target": rule.target_category_id},
        )

    def perform_update(self, serializer):
        rule = serializer.save()
        record_audit(
            action="recommendation_rule.update",
            actor=self.request.user,
            target=rule,
            request=self.request,
            changes={"fields": sorted(serializer.validated_data)},
        )

    def perform_destroy(self, instance):
        record_audit(
            action="recommendation_rule.delete",
            actor=self.request.user,
            target=instance,
            request=self.request,
            changes={"source": instance.source_category_id, "target": instance.target_category_id},
        )
        instance.delete()
