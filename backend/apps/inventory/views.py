from django.db import transaction
from django.db.models import F
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.audit import record_audit
from apps.core.permissions import IsStaffRole

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
            OpenApiParameter("low_stock", bool),
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
    """Staff only. Quantities change exclusively through `adjust` (ledgered), never by PATCH."""

    permission_classes = [IsStaffRole]
    queryset = Inventory.objects.select_related("store", "variant__product").order_by("store__code", "variant__sku")

    def get_serializer_class(self):
        if self.action == "create":
            return InventoryCreateSerializer
        if self.action == "adjust":
            return StockAdjustSerializer
        return InventorySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if store := params.get("store"):
            qs = qs.filter(store_id=store)
        if sku := params.get("sku"):
            qs = qs.filter(variant__sku__icontains=sku)
        if params.get("low_stock") in ("1", "true"):
            qs = qs.filter(available_quantity__lte=F("low_stock_threshold"))
        return qs

    @extend_schema(request=InventoryCreateSerializer, responses={201: InventorySerializer})
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = InventoryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
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
        qs = StockMovement.objects.select_related("inventory__variant", "inventory__store")
        if inv := self.request.query_params.get("inventory"):
            qs = qs.filter(inventory_id=inv)
        if kind := self.request.query_params.get("type"):
            qs = qs.filter(movement_type=kind)
        return qs
