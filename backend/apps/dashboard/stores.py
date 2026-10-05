"""Stores, warehouses, delivery zones and PIN codes for the dashboard.

Administrators create and change everything. A store manager sees the stores assigned to them
and may change how *their* store runs day to day (opening hours, preparation time, own riders,
pausing orders, contact phone); name, address, location, delivery zones and fees stay with the
administrator, because they decide where we deliver and what customers pay.
"""

from datetime import time

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Q, Sum
from django.db.models.deletion import ProtectedError
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError
from apps.core.permissions import IsAdminOrStaffReadOnly, IsStaffRole, is_admin, managed_store_ids
from apps.delivery.fulfillment import FeeRule
from apps.delivery.models import DeliveryPartner, DeliveryZone, PinCode
from apps.inventory.models import Inventory
from apps.orders.models import Order, OrderStatus
from apps.stores.models import Store

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MANAGER_FIELDS = {"opening_hours", "avg_prep_minutes", "prep_minutes_per_item", "own_riders", "accepts_orders", "phone"}
OPEN_ORDERS = [s for s in OrderStatus.values if s not in ("delivered", "cancelled", "returned", "return_requested")]


def clean_opening_hours(value) -> dict:
    """{} = always open. Otherwise one entry per day: ["09:00", "21:00"], or null for closed."""
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise serializers.ValidationError("Opening hours must be a list of days with opening and closing times.")
    cleaned = {}
    for day, hours in value.items():
        if day not in DAYS:
            raise serializers.ValidationError(f"Unknown day '{day}'. Use mon, tue, wed, thu, fri, sat, sun.")
        if hours in (None, [], ""):
            cleaned[day] = None
            continue
        if not isinstance(hours, (list, tuple)) or len(hours) != 2:
            raise serializers.ValidationError(f"{day}: give an opening and a closing time, e.g. 09:00 and 21:00.")
        try:
            opens, closes = (time.fromisoformat(str(v)) for v in hours)
        except ValueError:
            raise serializers.ValidationError(f"{day}: times must look like 09:00.") from None
        if opens == closes:
            raise serializers.ValidationError(f"{day}: opening and closing time are the same.")
        cleaned[day] = [opens.strftime("%H:%M"), closes.strftime("%H:%M")]
    return cleaned


class ZoneSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    effective_fee = serializers.SerializerMethodField()
    effective_free_from = serializers.SerializerMethodField()
    pin_codes = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryZone
        fields = [
            "id",
            "store",
            "store_name",
            "name",
            "radius_km",
            "postal_codes",
            "pin_codes",
            "polygon",
            "fast_delivery_enabled",
            "fast_delivery_max_minutes",
            "delivery_fee_override",
            "free_delivery_min_order",
            "effective_fee",
            "effective_free_from",
            "cod_enabled",
            "is_active",
        ]

    def get_effective_fee(self, obj) -> str:
        return str(FeeRule.for_zone(obj).fee)

    def get_effective_free_from(self, obj) -> str:
        return str(FeeRule.for_zone(obj).free_min)

    def get_pin_codes(self, obj) -> list[str]:
        return sorted(obj.postal_code_set)

    def validate_store(self, store):
        if store.kind not in Store.FULFILLMENT_KINDS:
            raise serializers.ValidationError("Warehouses don't deliver to customers; choose a store.")
        return store

    def validate_postal_codes(self, value):
        codes = value.replace(",", " ").split()
        bad = [c for c in codes if not (c.isdigit() and len(c) == 6)]
        if bad:
            raise serializers.ValidationError(f"PIN codes have 6 digits. Check: {', '.join(bad[:5])}")
        return " ".join(dict.fromkeys(codes))

    def validate_polygon(self, value):
        if value in (None, [], ""):
            return None
        ok = isinstance(value, list) and len(value) >= 3
        for point in value if ok else []:
            ok = ok and isinstance(point, (list, tuple)) and len(point) == 2
            ok = ok and all(isinstance(n, (int, float)) for n in point)
            ok = ok and -90 <= point[0] <= 90 and -180 <= point[1] <= 180
        if not ok:
            raise serializers.ValidationError("A polygon is a list of at least 3 [latitude, longitude] points.")
        return value


class StoreListSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    zone_count = serializers.IntegerField(read_only=True, default=0)
    open_orders = serializers.IntegerField(read_only=True, default=0)
    has_location = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            "id",
            "name",
            "code",
            "kind",
            "kind_label",
            "phone",
            "area",
            "city",
            "postal_code",
            "is_active",
            "accepts_orders",
            "cod_enabled",
            "avg_prep_minutes",
            "own_riders",
            "has_location",
            "zone_count",
            "open_orders",
            "can_edit",
        ]

    def get_has_location(self, obj) -> bool:
        return obj.latitude is not None and obj.longitude is not None

    def get_can_edit(self, obj) -> str:
        """all (administrator) | operations (the store's manager) | none"""
        user = self.context["request"].user
        if is_admin(user):
            return "all"
        return "operations" if obj.pk in (managed_store_ids(user) or []) else "none"


class StoreSerializer(StoreListSerializer):
    managers = serializers.SerializerMethodField()
    manager_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), write_only=True, required=False)
    zones = ZoneSerializer(source="delivery_zones", many=True, read_only=True)
    inventory = serializers.SerializerMethodField()
    riders = serializers.SerializerMethodField()

    class Meta(StoreListSerializer.Meta):
        fields = StoreListSerializer.Meta.fields + [
            "email",
            "address_line1",
            "address_line2",
            "state",
            "latitude",
            "longitude",
            "opening_hours",
            "prep_minutes_per_item",
            "managers",
            "manager_ids",
            "zones",
            "inventory",
            "riders",
        ]

    def validate_opening_hours(self, value):
        return clean_opening_hours(value)

    def validate(self, attrs):
        latitude = attrs.get("latitude", getattr(self.instance, "latitude", None))
        longitude = attrs.get("longitude", getattr(self.instance, "longitude", None))
        if (latitude is None) != (longitude is None):
            raise serializers.ValidationError({"latitude": "Give both latitude and longitude, or neither."})
        return attrs

    def validate_manager_ids(self, ids):
        User = get_user_model()
        found = User.objects.filter(pk__in=ids, role=User.Role.STORE_MANAGER, is_active=True).count()
        if found != len(set(ids)):
            raise serializers.ValidationError("Choose active users with the role 'store manager'.")
        return ids

    def get_managers(self, obj) -> list[dict]:
        return [{"id": m.pk, "name": m.full_name, "email": m.email} for m in obj.managers.all()]

    def get_inventory(self, obj) -> dict:
        rows = Inventory.objects.filter(store=obj, is_active=True)
        totals = rows.aggregate(
            records=Count("id"), available=Sum("available_quantity"), reserved=Sum("reserved_quantity")
        )
        return {
            "stock_records": totals["records"],
            "units_available": totals["available"] or 0,
            "units_reserved": totals["reserved"] or 0,
            "low_stock": rows.filter(available_quantity__lte=F("low_stock_threshold")).count(),
            "out_of_stock": rows.filter(available_quantity=0).count(),
        }

    def get_riders(self, obj) -> dict:
        partners = DeliveryPartner.objects.filter(home_store=obj, is_active=True, is_verified=True)
        return {
            "partners": partners.count(),
            "online": partners.filter(status__in=("available", "busy")).count(),
            "own_riders": obj.own_riders,
        }

    def _save(self, instance, validated_data):
        manager_ids = validated_data.pop("manager_ids", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.full_clean(exclude=["managers"])
        instance.save()
        if manager_ids is not None:
            instance.managers.set(manager_ids)
        return instance

    def create(self, validated_data):
        return self._save(Store(), validated_data)

    def update(self, instance, validated_data):
        return self._save(instance, validated_data)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("kind", str, enum=["store", "dark_store", "warehouse", "fulfilment"]),
            OpenApiParameter("q", str, description="Name, code, area, city or PIN code"),
            OpenApiParameter("is_active", bool),
        ]
    )
)
class AdminStoreViewSet(viewsets.ModelViewSet):
    """`?kind=warehouse` lists warehouses; `?kind=fulfilment` stores and dark stores."""

    permission_classes = [IsStaffRole]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        return StoreListSerializer if self.action == "list" else StoreSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Store.objects.none()
        qs = Store.objects.annotate(
            zone_count=Count("delivery_zones", filter=Q(delivery_zones__is_active=True), distinct=True),
            open_orders=Count("orders", filter=Q(orders__status__in=OPEN_ORDERS), distinct=True),
        ).prefetch_related("managers", "delivery_zones")
        allowed = managed_store_ids(self.request.user)
        if allowed is not None:
            qs = qs.filter(pk__in=allowed)
        params = self.request.query_params
        kind = params.get("kind")
        if kind == "fulfilment":
            qs = qs.filter(kind__in=Store.FULFILLMENT_KINDS)
        elif kind in Store.Kind.values:
            qs = qs.filter(kind=kind)
        if term := (params.get("q") or "").strip():
            qs = qs.filter(
                Q(name__icontains=term)
                | Q(code__icontains=term)
                | Q(area__icontains=term)
                | Q(city__icontains=term)
                | Q(postal_code__icontains=term)
            )
        if (active := params.get("is_active")) in ("true", "false"):
            qs = qs.filter(is_active=active == "true")
        return qs.order_by("name")

    def _require_admin(self, what: str):
        if not is_admin(self.request.user):
            raise PermissionDenied(f"Only an administrator can {what}.")

    def create(self, request, *args, **kwargs):
        self._require_admin("add stores")  # before validation: a manager gets 403, not a list of missing fields
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        store = serializer.save()
        record_audit(action="store.create", actor=self.request.user, target=store, request=self.request)

    def perform_update(self, serializer):
        fields = set(serializer.validated_data)
        if not is_admin(self.request.user) and not fields <= MANAGER_FIELDS:
            locked = ", ".join(sorted(fields - MANAGER_FIELDS))
            raise PermissionDenied(f"Only an administrator can change: {locked}.")
        store = serializer.save()
        record_audit(
            action="store.update",
            actor=self.request.user,
            target=store,
            request=self.request,
            changes={"fields": sorted(fields)},
        )

    def perform_destroy(self, instance):
        self._require_admin("remove stores")
        if Order.objects.filter(store=instance, status__in=OPEN_ORDERS).exists():
            raise ConflictError(
                "This store still has orders in progress. Pause new orders and finish them first.",
                code="store_has_open_orders",
            )
        stocked = Inventory.objects.filter(store=instance).filter(
            Q(available_quantity__gt=0) | Q(reserved_quantity__gt=0)
        )
        if stocked.exists():
            raise ConflictError(
                "This store still holds stock. Move or write off the stock first, or deactivate the store.",
                code="store_has_stock",
            )
        instance.delete()  # soft delete; past orders keep pointing to it
        record_audit(action="store.delete", actor=self.request.user, target=instance, request=self.request)


@extend_schema_view(
    list=extend_schema(parameters=[OpenApiParameter("store", int), OpenApiParameter("is_active", bool)])
)
class AdminZoneViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrStaffReadOnly]
    serializer_class = ZoneSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = DeliveryZone.objects.select_related("store").filter(store__is_deleted=False)
        allowed = managed_store_ids(self.request.user)
        if allowed is not None:
            qs = qs.filter(store_id__in=allowed)
        params = self.request.query_params
        if (store := params.get("store")) and store.isdigit():
            qs = qs.filter(store_id=store)
        if (active := params.get("is_active")) in ("true", "false"):
            qs = qs.filter(is_active=active == "true")
        return qs.order_by("store__name", "name")

    def perform_create(self, serializer):
        record_audit(action="zone.create", actor=self.request.user, target=serializer.save(), request=self.request)

    def perform_update(self, serializer):
        zone = serializer.save()
        record_audit(
            action="zone.update",
            actor=self.request.user,
            target=zone,
            request=self.request,
            changes={"fields": sorted(serializer.validated_data)},
        )

    def perform_destroy(self, instance):
        record_audit(action="zone.delete", actor=self.request.user, target=instance, request=self.request)
        try:
            instance.delete()
        except ProtectedError as exc:  # pragma: no cover - shipments use SET_NULL
            raise ConflictError("This zone is still in use. Deactivate it instead.", code="zone_in_use") from exc


class PinCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PinCode
        fields = ["id", "postal_code", "area", "city", "state", "latitude", "longitude", "is_active"]

    def validate_postal_code(self, value):
        if not (value.isdigit() and len(value) == 6):
            raise serializers.ValidationError("A PIN code has 6 digits.")
        return value


@extend_schema_view(list=extend_schema(parameters=[OpenApiParameter("q", str, description="PIN code, area or city")]))
class AdminPinCodeViewSet(viewsets.ModelViewSet):
    """Approximate centre of each PIN code, used to estimate distance when an address has no map pin."""

    permission_classes = [IsAdminOrStaffReadOnly]
    serializer_class = PinCodeSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = PinCode.objects.all()
        if term := (self.request.query_params.get("q") or "").strip():
            qs = qs.filter(Q(postal_code__icontains=term) | Q(area__icontains=term) | Q(city__icontains=term))
        return qs
