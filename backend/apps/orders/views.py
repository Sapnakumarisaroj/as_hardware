import re

from django.db import IntegrityError
from django.db.models import Prefetch, Q
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import ProductImage
from apps.core.exceptions import NotFoundError
from apps.core.permissions import IsStaffRole, is_admin, is_staff_member, managed_store_ids
from apps.payments.models import Payment, Refund
from apps.payments.services import retry_payment

from . import returns, services
from .checkout import build_checkout
from .models import Order, OrderItem, OrderShipment, ReturnItem, ReturnRequest
from .serializers import (
    IDEMPOTENCY_KEY_PATTERN,
    AssignPickupSerializer,
    CancelOrderSerializer,
    CheckoutPreviewRequestSerializer,
    CheckoutPreviewSerializer,
    CreateReturnSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
    PlaceOrderSerializer,
    ReceiveReturnSerializer,
    ReorderResultSerializer,
    ReturnDecisionSerializer,
    ReturnRequestSerializer,
    TransitionOrderSerializer,
)

IDEMPOTENCY_HEADER = "Idempotency-Key"
IDEMPOTENCY_KEY_RE = re.compile(IDEMPOTENCY_KEY_PATTERN)


def _jobs():
    """Delivery jobs with their rider, newest first (apps.delivery.serializers.latest_delivery)."""
    from apps.delivery.models import DeliveryAssignment

    return DeliveryAssignment.objects.select_related("partner__user").order_by("-assigned_at")


def _returns_queryset():
    return ReturnRequest.objects.select_related("order", "refund").prefetch_related(
        Prefetch("pickups", queryset=_jobs()),
        Prefetch(
            "items",
            queryset=ReturnItem.objects.select_related("order_item__product").prefetch_related(
                Prefetch(
                    "order_item__product__images", queryset=ProductImage.objects.order_by("-is_primary", "sort_order")
                )
            ),
        ),
    )


def _scope_by_role(qs, user):
    """Customers: own rows. Store managers: rows of their stores' orders (+ own). Admins: all."""
    store_ids = managed_store_ids(user)
    if store_ids is None:
        return qs
    if is_staff_member(user):
        return qs.filter(Q(order__store_id__in=store_ids) | Q(user=user))
    return qs.filter(user=user)


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
            Prefetch(
                "shipments",
                queryset=OrderShipment.objects.select_related("store", "order").prefetch_related(
                    "items", Prefetch("assignments", queryset=_jobs())
                ),
            ),
            Prefetch("payments", queryset=Payment.objects.prefetch_related(Prefetch("refunds", Refund.objects.all()))),
            Prefetch("returns", queryset=_returns_queryset()),
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
        data["quote"] = data.pop("quote_id", None)
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
        if getattr(order, "idempotent_replay", False):  # lost the race inside place_order
            return self._detail(order, headers=replay)
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

    @extend_schema(request=None, responses=ReorderResultSerializer)
    @action(detail=True, methods=["post"])
    def reorder(self, request, order_number=None):
        """Buy again: add this order's items to the cart at today's prices (stock permitting)."""
        from apps.carts.serializers import CartSerializer
        from apps.carts.services import summarize_cart

        lines = services.reorder(self.get_object(), user=request.user)
        payload = {
            "added": [line for line in lines if line.added],
            "skipped": [line for line in lines if line.reason],
            "cart": CartSerializer(summarize_cart(request.user), context={"request": request}).data,
        }
        return Response(ReorderResultSerializer(payload).data)

    @extend_schema(request=None, responses={(200, "text/html"): OpenApiTypes.STR})
    @action(detail=True, methods=["get"])
    def invoice(self, request, order_number=None):
        """Printable invoice (HTML; print or save as PDF in the browser). Same visibility as the
        order itself: the customer who ordered, the store's staff, admins."""
        from django.http import HttpResponse

        from .invoice import render_invoice

        response = HttpResponse(render_invoice(self.get_object()), content_type="text/html; charset=utf-8")
        response["Cache-Control"] = "private, no-store"
        return response

    @extend_schema(request=None, responses=OrderDetailSerializer)
    @action(detail=True, methods=["post"], url_path=r"shipments/(?P<sequence>\d+)/delivery-code")
    def delivery_code(self, request, order_number=None, sequence=None):
        """The customer asks for a new delivery code (the old one stops working). At most one
        per DELIVERY_OTP_RESEND_SECONDS."""
        from apps.delivery import workflow

        order = self.get_object()
        workflow.new_delivery_code(order, int(sequence), user=request.user)
        return self._detail(order)

    @extend_schema(request=None, responses={(200, "image/jpeg"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"], url_path=r"shipments/(?P<sequence>\d+)/proof")
    def delivery_proof(self, request, order_number=None, sequence=None):
        """Photo taken when this shipment was delivered. Visible to the customer who ordered
        and to the staff of the store; never by URL."""
        from apps.delivery.models import DeliveryAssignment
        from apps.delivery.views import proof_response

        order = self.get_object()
        job = (
            DeliveryAssignment.objects.filter(
                order=order, shipment__sequence=int(sequence), kind="delivery", status="delivered"
            )
            .exclude(proof_image="")
            .first()
        )
        if job is None:
            raise NotFoundError("No photo was uploaded for this delivery.")
        return proof_response(job)

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
            use_credits=serializer.validated_data["use_credits"],
            quote_id=serializer.validated_data.get("quote_id"),
        )
        return Response(CheckoutPreviewSerializer(summary, context={"request": request}).data)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("status", str),
            OpenApiParameter("q", str, description="Return number, order number, customer name, email or phone"),
            OpenApiParameter("store", int),
        ]
    )
)
class ReturnViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Return requests. Customers create, view and cancel their own; store managers (their
    stores) and admins approve, reject and receive them. Refund amounts are server-calculated."""

    lookup_field = "return_number"
    serializer_class = ReturnRequestSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ReturnRequest.objects.none()
        qs = _scope_by_role(_returns_queryset(), self.request.user)
        status_filter = self.request.query_params.get("status")
        if status_filter == "open":  # waiting for a decision, or approved and not received yet
            qs = qs.filter(status__in=ReturnRequest.OPEN_STATUSES)
        elif status_filter:
            qs = qs.filter(status=status_filter)
        params = self.request.query_params
        if term := (params.get("q") or "").strip():
            qs = qs.filter(
                Q(return_number__icontains=term)
                | Q(order__order_number__icontains=term)
                | Q(user__full_name__icontains=term)
                | Q(user__email__icontains=term)
                | Q(user__phone__icontains=term)
            )
        if (store := params.get("store")) and store.isdigit():
            qs = qs.filter(order__store_id=store)
        return qs

    def _detail(self, ret: ReturnRequest, status_code=status.HTTP_200_OK) -> Response:
        fresh = _returns_queryset().get(pk=ret.pk)
        return Response(ReturnRequestSerializer(fresh, context={"request": self.request}).data, status=status_code)

    def _managed(self) -> ReturnRequest:
        ret = self.get_object()
        if not is_admin(self.request.user) and ret.order.store_id not in (managed_store_ids(self.request.user) or []):
            raise PermissionDenied("You can only handle returns for stores assigned to you.")
        return ret

    @extend_schema(request=CreateReturnSerializer, responses={201: ReturnRequestSerializer})
    def create(self, request):
        serializer = CreateReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        order = Order.objects.filter(order_number=data["order_number"], user=request.user).first()
        if order is None:
            raise NotFoundError("Order not found.")
        ret = returns.request_return(
            order, user=request.user, items=data["items"], reason=data["reason"], details=data["details"]
        )
        return self._detail(ret, status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=ReturnRequestSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, return_number=None):
        ret = returns.cancel_return(self.get_object(), user=request.user)
        return self._detail(ret)

    @extend_schema(request=ReturnDecisionSerializer, responses=ReturnRequestSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsStaffRole])
    def approve(self, request, return_number=None):
        serializer = ReturnDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ret = returns.approve_return(self._managed(), actor=request.user, note=serializer.validated_data["note"])
        return self._detail(ret)

    @extend_schema(request=ReturnDecisionSerializer, responses=ReturnRequestSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsStaffRole])
    def reject(self, request, return_number=None):
        serializer = ReturnDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ret = returns.reject_return(self._managed(), actor=request.user, note=serializer.validated_data["note"])
        return self._detail(ret)

    @extend_schema(request=AssignPickupSerializer, responses={201: ReturnRequestSerializer})
    @action(detail=True, methods=["post"], permission_classes=[IsStaffRole], url_path="assign-pickup")
    def assign_pickup(self, request, return_number=None):
        """Send a delivery partner to collect an approved return from the customer (Phase 10)."""
        from apps.delivery.assignment import assign_return_pickup
        from apps.delivery.models import DeliveryPartner

        serializer = AssignPickupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ret = self._managed()
        partner = DeliveryPartner.objects.filter(pk=serializer.validated_data["partner_id"]).first()
        if partner is None:
            raise NotFoundError("Delivery partner not found.")
        assign_return_pickup(ret, partner, actor=request.user)
        return self._detail(ret, status.HTTP_201_CREATED)

    @extend_schema(request=ReceiveReturnSerializer, responses=ReturnRequestSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsStaffRole])
    def receive(self, request, return_number=None):
        serializer = ReceiveReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ret = returns.receive_return(self._managed(), actor=request.user, **serializer.validated_data)
        return self._detail(ret)
