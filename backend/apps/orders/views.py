import re

from django.db import IntegrityError
from django.db.models import Prefetch, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import ProductImage
from apps.core.permissions import IsStaffRole, is_admin, is_staff_member, managed_store_ids
from apps.payments.models import Payment, Refund
from apps.payments.services import retry_payment

from . import services
from .checkout import build_checkout
from .models import Order, OrderItem
from .serializers import (
    IDEMPOTENCY_KEY_PATTERN,
    CancelOrderSerializer,
    CheckoutPreviewRequestSerializer,
    CheckoutPreviewSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
    PlaceOrderSerializer,
    TransitionOrderSerializer,
)

IDEMPOTENCY_HEADER = "Idempotency-Key"
IDEMPOTENCY_KEY_RE = re.compile(IDEMPOTENCY_KEY_PATTERN)


@extend_schema_view(list=extend_schema(parameters=[OpenApiParameter("status", str)]))
class OrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Customers: own orders. Store managers: orders of their assigned stores (+ own). Admins: all.

    Customers can create, view, cancel and retry payment. Status changes other than
    cancellation are staff-only (`transition`); there is no update/partial-update endpoint.
    """

    lookup_field = "order_number"

    def get_queryset(self):
        qs = Order.objects.select_related("store").prefetch_related(
            Prefetch(
                "items",
                queryset=OrderItem.objects.select_related("product").prefetch_related(
                    Prefetch("product__images", queryset=ProductImage.objects.order_by("-is_primary", "sort_order"))
                ),
            ),
            "status_history",
            Prefetch("payments", queryset=Payment.objects.prefetch_related(Prefetch("refunds", Refund.objects.all()))),
        )
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

    def _detail(self, order: Order, status_code=status.HTTP_200_OK, headers=None) -> Response:
        data = OrderDetailSerializer(self.get_queryset().get(pk=order.pk), context={"request": self.request}).data
        return Response(data, status=status_code, headers=headers)

    @extend_schema(
        request=PlaceOrderSerializer,
        responses={201: OrderDetailSerializer, 200: OrderDetailSerializer},
        parameters=[OpenApiParameter(IDEMPOTENCY_HEADER, str, OpenApiParameter.HEADER, required=False)],
    )
    def create(self, request):
        serializer = PlaceOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        body_key = data.pop("idempotency_key", None)
        key = request.headers.get(IDEMPOTENCY_HEADER) or body_key or None
        if key and not IDEMPOTENCY_KEY_RE.match(key):
            key = None  # malformed header: ignore rather than store junk
        replay = {"Idempotent-Replayed": "true"}
        if existing := services.find_idempotent_order(request.user, key):
            return self._detail(existing, headers=replay)
        try:
            order, _payment = services.place_order(user=request.user, idempotency_key=key, **data)
        except IntegrityError:
            # A concurrent request with the same key won the race; return its order.
            if existing := services.find_idempotent_order(request.user, key):
                return self._detail(existing, headers=replay)
            raise
        return self._detail(order, status.HTTP_201_CREATED)

    @extend_schema(request=CancelOrderSerializer, responses=OrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, order_number=None):
        order = self.get_object()
        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.cancel_order_by_customer(order, user=request.user, reason=serializer.validated_data["reason"])
        return self._detail(order)

    @extend_schema(request=None, responses=OrderDetailSerializer)
    @action(detail=True, methods=["post"], url_path="retry-payment")
    def retry_payment(self, request, order_number=None):
        """New online payment attempt after a failed/cancelled one (order must still be pending)."""
        order = self.get_object()
        retry_payment(order, user=request.user)
        return self._detail(order)

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
        return self._detail(order)


class CheckoutPreviewView(APIView):
    """Validate the cart for checkout and return server-calculated totals, coupon and delivery info.
    Nothing is reserved or written."""

    @extend_schema(request=CheckoutPreviewRequestSerializer, responses=CheckoutPreviewSerializer)
    def post(self, request):
        serializer = CheckoutPreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        summary = build_checkout(
            request.user,
            address_id=serializer.validated_data.get("address_id"),
            coupon_code=serializer.validated_data["coupon_code"],
        )
        return Response(CheckoutPreviewSerializer(summary, context={"request": request}).data)
