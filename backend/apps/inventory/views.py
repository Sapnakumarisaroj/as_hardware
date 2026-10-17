from django.db import transaction
from django.db.models import F, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.audit import record_audit
from apps.core.permissions import IsStaffRole, managed_store_ids, scope_to_managed_stores

from . import services
from .models import Inventory, StockMovement
from .serializers import (
    InventoryCreateSerializer,
    InventorySerializer,
    StockAdjustSerializer,
    StockMovementSerializer,
)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("store", int),
            OpenApiParameter("sku", str),
            OpenApiParameter("product", int),
            OpenApiParameter("low_stock", bool),
            OpenApiParameter("q", str, description="SKU, product, variant or store"),
            OpenApiParameter("stock", str, enum=["out", "low", "ok"]),
        ]
    )
)
class InventoryViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Admins: all stores. Store managers: assigned stores only (others 404).
    Quantities change exclusively through `adjust` (ledgered), never by PATCH."""

    permission_classes = [IsStaffRole]
    queryset = Inventory.objects.select_related("store", "variant__product").order_by("store__code", "variant__sku")

    def get_serializer_class(self):
        if self.action == "create":
            return InventoryCreateSerializer
        if self.action == "adjust":
            return StockAdjustSerializer
        return InventorySerializer

    def perform_update(self, serializer):
        """Threshold / on-off changes (quantities only move through `adjust`) are audited too."""
        fields = sorted(serializer.validated_data)
        before = {f: getattr(serializer.instance, f) for f in fields}
        row = serializer.save()
        record_audit(
            action="inventory.update",
            actor=self.request.user,
            target=row,
            request=self.request,
            changes={f: {"from": before[f], "to": getattr(row, f)} for f in fields if before[f] != getattr(row, f)},
        )

    def get_queryset(self):
        qs = scope_to_managed_stores(super().get_queryset(), self.request.user)
        params = self.request.query_params
        if store := params.get("store"):
            qs = qs.filter(store_id=store)
        if sku := params.get("sku"):
            qs = qs.filter(variant__sku__icontains=sku)
        if (product := params.get("product")) and product.isdigit():  # one product's stock (product page)
            qs = qs.filter(variant__product_id=product)
        if params.get("low_stock") in ("1", "true"):
            qs = qs.filter(available_quantity__lte=F("low_stock_threshold"))
        if term := (params.get("q") or "").strip():
            qs = qs.filter(
                Q(variant__sku__icontains=term)
                | Q(variant__name__icontains=term)
                | Q(variant__product__name__icontains=term)
                | Q(store__name__icontains=term)
                | Q(store__code__icontains=term)
            )
        stock = params.get("stock")
        if stock == "out":
            qs = qs.filter(available_quantity=0)
        elif stock == "low":
            qs = qs.filter(available_quantity__gt=0, available_quantity__lte=F("low_stock_threshold"))
        elif stock == "ok":
            qs = qs.filter(available_quantity__gt=F("low_stock_threshold"))
        return qs

    @extend_schema(request=InventoryCreateSerializer, responses={201: InventorySerializer})
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = InventoryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allowed = managed_store_ids(request.user)
        if allowed is not None and serializer.validated_data["store"].id not in allowed:
            raise PermissionDenied("You can only manage stock for stores assigned to you.")
        opening = serializer.validated_data.pop("opening_quantity", 0)
        inventory = serializer.save()
        if opening:
            services.apply_movement(
                inventory, StockMovement.Type.PURCHASE, opening, reason="Opening stock", actor=request.user
            )
        record_audit(action="inventory.create", actor=request.user, target=inventory, request=request)
        return Response(InventorySerializer(inventory).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=StockAdjustSerializer, responses=StockMovementSerializer)
    @action(detail=True, methods=["post"])
    def adjust(self, request, pk=None):
        inventory = self.get_object()
        serializer = StockAdjustSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        movement = services.apply_movement(
            inventory,
            data["movement_type"],
            data["quantity"],
            reason=data["reason"],
            reference_type="manual" if data["reference"] else "",
            reference_id=data["reference"],
            actor=request.user,
        )
        record_audit(
            action="inventory.adjust",
            actor=request.user,
            target=inventory,
            request=request,
            changes={"type": data["movement_type"], "quantity": data["quantity"]},
        )
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)


@extend_schema_view(list=extend_schema(parameters=[OpenApiParameter("inventory", int), OpenApiParameter("type", str)]))
class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsStaffRole]
    serializer_class = StockMovementSerializer

    def get_queryset(self):
        qs = scope_to_managed_stores(
            StockMovement.objects.select_related("inventory__variant", "inventory__store"),
            self.request.user,
            store_field="inventory__store",
        )
        if inv := self.request.query_params.get("inventory"):
            qs = qs.filter(inventory_id=inv)
        if kind := self.request.query_params.get("type"):
            qs = qs.filter(movement_type=kind)
        return qs
