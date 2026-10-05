"""Phase 15 commerce settings for the dashboard: option types, curated lists, free-delivery rules
and payment (cash on delivery) settings.

Administrators change them; store managers may read option types (they see products) but none of
the pricing rules. These endpoints only store rules: prices, delivery fees and COD decisions are
calculated in one place (`orders.pricing`, `payments.cod_rules`), never here.
"""

from django.db import transaction
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.collections import collection_products
from apps.catalog.models import Category, Collection, CollectionItem, OptionType, OptionValue, Product, VariantOption
from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError
from apps.core.permissions import IsAdminOrStaffReadOnly, IsAdminRole
from apps.delivery.models import DeliveryZone, FreeDeliveryRule
from apps.payments.cod_rules import format_inr
from apps.payments.models import PaymentSettings
from apps.stores.models import Store

from .offers import rule_state


def _audit(request, action_name: str, target, changes=None):
    record_audit(action=action_name, actor=request.user, target=target, request=request, changes=changes)


# --- Option types --------------------------------------------------------------------------------


class OptionValueInputSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    value = serializers.CharField(max_length=80)


class AdminOptionTypeSerializer(serializers.ModelSerializer):
    categories = serializers.PrimaryKeyRelatedField(many=True, queryset=Category.objects.all(), required=False)
    category_details = serializers.SerializerMethodField()
    values = serializers.SerializerMethodField()
    value_list = OptionValueInputSerializer(many=True, write_only=True, required=False)
    variant_count = serializers.SerializerMethodField()

    class Meta:
        model = OptionType
        fields = [
            "id",
            "name",
            "slug",
            "unit",
            "sort_order",
            "is_active",
            "categories",
            "category_details",
            "values",
            "value_list",
            "variant_count",
        ]
        extra_kwargs = {"slug": {"required": False}}

    def get_category_details(self, obj) -> list[dict]:
        return [{"id": c.pk, "name": str(c)} for c in obj.categories.all()]

    def get_variant_count(self, obj) -> int:
        return VariantOption.objects.filter(option_type=obj).count()

    def get_values(self, obj) -> list[dict]:
        used = dict(
            VariantOption.objects.filter(option_type=obj).values_list("value_id").annotate(n=Count("variant_id"))
        )
        return [{"id": v.pk, "value": v.value, "slug": v.slug, "used_by": used.get(v.pk, 0)} for v in obj.values.all()]

    def validate_name(self, value):
        name = " ".join(value.split())
        clash = OptionType.objects.filter(name__iexact=name)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("An option with this name already exists.")
        return name

    def validate_value_list(self, rows):
        seen = set()
        for row in rows:
            key = row["value"].strip().lower()
            if not key:
                raise serializers.ValidationError("Values can't be empty.")
            if key in seen:
                raise serializers.ValidationError(f"'{row['value']}' is listed twice.")
            seen.add(key)
        return rows

    @transaction.atomic
    def create(self, validated_data):
        values = validated_data.pop("value_list", [])
        categories = validated_data.pop("categories", [])
        option_type = OptionType.objects.create(**validated_data)
        option_type.categories.set(categories)
        self._save_values(option_type, values)
        return option_type

    @transaction.atomic
    def update(self, instance, validated_data):
        values = validated_data.pop("value_list", None)
        categories = validated_data.pop("categories", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if categories is not None:
            instance.categories.set(categories)
        if values is not None:
            self._save_values(instance, values)
        return instance

    @staticmethod
    def _save_values(option_type: OptionType, rows: list[dict]) -> None:
        """Replace the value list: rename kept values, add new ones, remove unused missing ones.
        A value still used by a variant can't be removed (it would change that variant)."""
        from django.utils.text import slugify

        keep = []
        for position, row in enumerate(rows):
            text = " ".join(row["value"].split())[:80]
            slug = slugify(text)[:90] or "value"
            value = option_type.values.filter(pk=row.get("id")).first() if row.get("id") else None
            if value is None:
                value = option_type.values.filter(slug=slug).first() or OptionValue(option_type=option_type)
            # Renaming keeps the same row (variants follow it); the slug follows the new name.
            value.value, value.slug, value.sort_order = text, slug, position
            clash = option_type.values.filter(slug=value.slug).exclude(pk=value.pk).exists()
            if clash:
                raise ConflictError(f"'{text}' is listed twice.", code="duplicate_option_value")
            value.save()
            keep.append(value.pk)
        removed = option_type.values.exclude(pk__in=keep)
        in_use = removed.filter(variant_options__isnull=False).distinct()
        if in_use.exists():
            names = ", ".join(v.value for v in in_use[:3])
            raise ConflictError(
                f"{names} is still used by product variants. Change those variants first.", code="option_value_in_use"
            )
        removed.delete()


@extend_schema_view(list=extend_schema(parameters=[OpenApiParameter("q", str)]))
class AdminOptionTypeViewSet(viewsets.ModelViewSet):
    """Structured product options (Grade, Bag size, Thickness, …). Administrators manage them;
    store managers can read them."""

    permission_classes = [IsAdminOrStaffReadOnly]
    serializer_class = AdminOptionTypeSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = OptionType.objects.prefetch_related("categories", "values")
        if term := (self.request.query_params.get("q") or "").strip():
            qs = qs.filter(name__icontains=term)
        return qs.order_by("sort_order", "name")

    def perform_create(self, serializer):
        _audit(self.request, "option_type.create", serializer.save())

    def perform_update(self, serializer):
        _audit(self.request, "option_type.update", serializer.save(), {"fields": sorted(serializer.validated_data)})

    def perform_destroy(self, instance):
        if VariantOption.objects.filter(option_type=instance).exists():
            raise ConflictError(
                "Variants still use this option. Deactivate it instead, or change those variants first.",
                code="option_type_in_use",
            )
        _audit(self.request, "option_type.delete", instance, {"name": instance.name})
        try:
            instance.delete()
        except ProtectedError as exc:  # pragma: no cover - guarded above
            raise ConflictError("This option is still in use.", code="option_type_in_use") from exc


# --- Curated lists -------------------------------------------------------------------------------


class AdminCollectionSerializer(serializers.ModelSerializer):
    categories = serializers.PrimaryKeyRelatedField(many=True, queryset=Category.objects.all(), required=False)
    category_details = serializers.SerializerMethodField()
    product_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), write_only=True, required=False)
    items = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()

    class Meta:
        model = Collection
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "rule",
            "window_days",
            "max_items",
            "categories",
            "category_details",
            "starts_at",
            "ends_at",
            "is_active",
            "sort_order",
            "product_ids",
            "items",
            "state",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"slug": {"required": False}}

    def get_category_details(self, obj) -> list[dict]:
        return [{"id": c.pk, "name": str(c)} for c in obj.categories.all()]

    def get_items(self, obj) -> list[dict]:
        rows = obj.items.select_related("product").order_by("sort_order", "id")
        return [
            {"product_id": i.product_id, "name": i.product.name, "sku": i.product.sku, "live": i.product.is_purchasable}
            for i in rows
        ]

    def get_state(self, obj) -> str:
        """inactive | scheduled | expired | live"""
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
        rule = attrs.get("rule", getattr(self.instance, "rule", Collection.Rule.MANUAL))
        ids = attrs.get("product_ids")
        if ids is not None:
            if len(set(ids)) != len(ids):
                raise serializers.ValidationError({"product_ids": "A product is listed twice."})
            found = set(Product.objects.filter(pk__in=ids).values_list("pk", flat=True))
            if missing := [i for i in ids if i not in found]:
                raise serializers.ValidationError({"product_ids": f"Unknown products: {missing[:5]}"})
        if rule == Collection.Rule.MANUAL and self.instance is None and not ids:
            raise serializers.ValidationError({"product_ids": "Choose the products for this list."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        ids = validated_data.pop("product_ids", [])
        categories = validated_data.pop("categories", [])
        collection = Collection.objects.create(**validated_data)
        collection.categories.set(categories)
        self._set_items(collection, ids)
        return collection

    @transaction.atomic
    def update(self, instance, validated_data):
        ids = validated_data.pop("product_ids", None)
        categories = validated_data.pop("categories", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if categories is not None:
            instance.categories.set(categories)
        if ids is not None:
            self._set_items(instance, ids)
        return instance

    @staticmethod
    def _set_items(collection, ids):
        collection.items.all().delete()
        CollectionItem.objects.bulk_create(
            [CollectionItem(collection=collection, product_id=pid, sort_order=pos) for pos, pid in enumerate(ids)]
        )


@extend_schema_view(list=extend_schema(parameters=[OpenApiParameter("q", str)]))
class AdminCollectionViewSet(viewsets.ModelViewSet):
    """Curated product lists for the shop front (administrators only)."""

    permission_classes = [IsAdminRole]
    serializer_class = AdminCollectionSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Collection.objects.prefetch_related("categories")
        if term := (self.request.query_params.get("q") or "").strip():
            qs = qs.filter(Q(name__icontains=term) | Q(description__icontains=term))
        return qs.order_by("sort_order", "name")

    def perform_create(self, serializer):
        _audit(self.request, "collection.create", serializer.save())

    def perform_update(self, serializer):
        _audit(self.request, "collection.update", serializer.save(), {"fields": sorted(serializer.validated_data)})

    def perform_destroy(self, instance):
        _audit(self.request, "collection.delete", instance, {"name": instance.name})
        instance.delete()

    @extend_schema(responses={200: None})
    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        """What customers would see in this list right now (live products only, real data)."""
        collection = self.get_object()
        products = collection_products(collection)
        return Response(
            {
                "is_live": collection.is_live(),
                "count": len(products),
                "products": [{"id": p.pk, "name": p.name, "sku": p.sku, "price": str(p.price)} for p in products],
            }
        )


# --- Free-delivery rules --------------------------------------------------------------------------


class FreeDeliveryRuleSerializer(serializers.ModelSerializer):
    zones = serializers.PrimaryKeyRelatedField(many=True, queryset=DeliveryZone.objects.all(), required=False)
    products = serializers.PrimaryKeyRelatedField(many=True, queryset=Product.objects.all(), required=False)
    categories = serializers.PrimaryKeyRelatedField(many=True, queryset=Category.objects.all(), required=False)
    zone_details = serializers.SerializerMethodField()
    product_details = serializers.SerializerMethodField()
    category_details = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    class Meta:
        model = FreeDeliveryRule
        fields = [
            "id",
            "name",
            "description",
            "threshold",
            "zones",
            "products",
            "categories",
            "zone_details",
            "product_details",
            "category_details",
            "starts_at",
            "ends_at",
            "is_active",
            "state",
            "summary",
            "created_at",
            "updated_at",
        ]

    def get_zone_details(self, obj) -> list[dict]:
        return [{"id": z.pk, "name": f"{z.store.name} · {z.name}"} for z in obj.zones.select_related("store")]

    def get_product_details(self, obj) -> list[dict]:
        return [{"id": p.pk, "name": p.name, "sku": p.sku} for p in obj.products.all()]

    def get_category_details(self, obj) -> list[dict]:
        return [{"id": c.pk, "name": str(c)} for c in obj.categories.all()]

    def get_state(self, obj) -> str:
        return rule_state(obj)

    def get_summary(self, obj) -> str:
        """The rule in words: "Free delivery from ₹2,000 of Cement in Kothrud 5 km"."""
        targets = [c.name for c in obj.categories.all()] + [p.name for p in obj.products.all()]
        text = f"Free delivery from {format_inr(obj.threshold)}"
        if targets:
            text += " of " + ", ".join(targets[:3]) + ("…" if len(targets) > 3 else "")
        zones = [z.name for z in obj.zones.all()]
        text += " in " + ", ".join(zones[:3]) if zones else " everywhere we deliver"
        return text

    def validate(self, attrs):
        starts = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_at": "End must be after start."})
        return attrs


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("q", str),
            OpenApiParameter("state", str, enum=["live", "scheduled", "expired", "inactive"]),
        ]
    )
)
class AdminFreeDeliveryRuleViewSet(viewsets.ModelViewSet):
    """Free-delivery rules (administrators only). The checkout applies them through `orders.pricing`."""

    permission_classes = [IsAdminRole]
    serializer_class = FreeDeliveryRuleSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = FreeDeliveryRule.objects.prefetch_related("zones__store", "products", "categories")
        params = self.request.query_params
        if term := (params.get("q") or "").strip():
            qs = qs.filter(Q(name__icontains=term) | Q(description__icontains=term))
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
        return qs.order_by("threshold", "id")

    def perform_create(self, serializer):
        _audit(self.request, "free_delivery_rule.create", serializer.save())

    def perform_update(self, serializer):
        _audit(
            self.request, "free_delivery_rule.update", serializer.save(), {"fields": sorted(serializer.validated_data)}
        )

    def perform_destroy(self, instance):
        _audit(self.request, "free_delivery_rule.delete", instance, {"name": instance.name})
        instance.delete()


# --- Payment settings (cash on delivery) ---------------------------------------------------------------


class PaymentSettingsSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.CharField(source="updated_by.full_name", read_only=True, default=None)

    class Meta:
        model = PaymentSettings
        fields = ["cod_enabled", "cod_max_order_value", "updated_at", "updated_by_name"]
        read_only_fields = ["updated_at", "updated_by_name"]


class PaymentSettingsView(APIView):
    """Cash-on-delivery rules: on/off and the largest order payable in cash (administrators change
    them; store managers may read them). Per-store and per-zone switches live on stores and zones."""

    permission_classes = [IsAdminOrStaffReadOnly]

    def _payload(self, settings: PaymentSettings) -> dict:
        data = PaymentSettingsSerializer(settings).data
        data["stores_without_cod"] = [
            {"id": s.pk, "name": s.name}
            for s in Store.objects.filter(cod_enabled=False, kind__in=Store.FULFILLMENT_KINDS).order_by("name")
        ]
        data["zones_without_cod"] = [
            {"id": z.pk, "name": z.name, "store_name": z.store.name}
            for z in DeliveryZone.objects.filter(cod_enabled=False, store__is_deleted=False).select_related("store")
        ]
        return data

    @extend_schema(responses={200: PaymentSettingsSerializer})
    def get(self, request):
        return Response(self._payload(PaymentSettings.load()))

    @extend_schema(request=PaymentSettingsSerializer, responses={200: PaymentSettingsSerializer})
    def patch(self, request):
        settings = PaymentSettings.load()
        serializer = PaymentSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        before = {f: str(getattr(settings, f)) for f in serializer.validated_data}
        settings = serializer.save(updated_by=request.user)
        _audit(
            request,
            "payment_settings.update",
            settings,
            {f: {"from": before[f], "to": str(getattr(settings, f))} for f in serializer.validated_data},
        )
        return Response(self._payload(settings))
