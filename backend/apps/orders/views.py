from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.permissions import IsStaffRole, is_admin, is_staff_member, managed_store_ids

from . import services
from .models import Order
from .serializers import (
    CancelOrderSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
    PlaceOrderSerializer,
    TransitionOrderSerializer,
)


@extend_schema_view(list=extend_schema(parameters=[OpenApiParameter("status", str)]))
class OrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Customers: own orders. Store managers: orders of their assigned stores (+ own). Admins: all."""

    lookup_field = "order_number"

    def get_queryset(self):
        qs = Order.objects.select_related("store").prefetch_related("items", "status_history", "payments")
        if getattr(self, "swagger_fake_view", False):  # OpenAPI schema generation
            return qs.none()
        user = self.request.user
        store_ids = managed_store_ids(user)
        if store_ids is None:
            pass  # admin
        elif is_staff_member(user):
            qs = qs.filter(Q(store_id__in=store_ids) | Q(user=user))
        else:
            qs = qs.filter(user=user)
        if status_filter := self.request.query_params.get("status"):
            qs = qs.filter(status=status_filter)
        return qs

    def get_serializer_class(self):
        return OrderListSerializer if self.action == "list" else OrderDetailSerializer

    @extend_schema(request=PlaceOrderSerializer, responses={201: OrderDetailSerializer})
    def create(self, request):
        serializer = PlaceOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order, _payment = services.place_order(user=request.user, **serializer.validated_data)
        order = self.get_queryset().get(pk=order.pk)
        return Response(OrderDetailSerializer(order).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=CancelOrderSerializer, responses=OrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, order_number=None):
        order = self.get_object()
        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.cancel_order_by_customer(order, user=request.user, reason=serializer.validated_data["reason"])
        return Response(OrderDetailSerializer(self.get_queryset().get(pk=order.pk)).data)

    @extend_schema(request=TransitionOrderSerializer, responses=OrderDetailSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsStaffRole])
    def transition(self, request, order_number=None):
        order = self.get_object()
        # A manager's own purchase at a store they don't manage is visible to them, but not operable.
        if order.store_id not in (managed_store_ids(request.user) or []) and not is_admin(request.user):
            raise PermissionDenied("You can only update orders of stores assigned to you.")
        serializer = TransitionOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.transition_order(
            order, serializer.validated_data["status"], actor=request.user, note=serializer.validated_data["note"]
        )
        return Response(OrderDetailSerializer(self.get_queryset().get(pk=order.pk)).data)
