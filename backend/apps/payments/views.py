import logging

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsStaffRole, managed_store_ids
from apps.orders.serializers import OrderDetailSerializer
from apps.orders.views import OrderViewSet

from . import refunds, services
from .models import Refund

logger = logging.getLogger(__name__)


class VerifyPaymentSerializer(serializers.Serializer):
    """Whatever the gateway returned to the browser. The server verifies it with the gateway.

    Razorpay: {"razorpay_order_id", "razorpay_payment_id", "razorpay_signature"} or {"cancelled": true}.
    Mock: {"mock_signature": <from client_payload>, "mock_outcome": "success"|"failed"|"cancelled"|"pending"}.
    """

    payload = serializers.DictField()


class VerifyPaymentView(APIView):
    """Verify an online payment for the signed-in customer's own order; returns the updated order."""

    @extend_schema(request=VerifyPaymentSerializer, responses=OrderDetailSerializer)
    def post(self, request, public_id):
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.verify_payment(public_id, user=request.user, payload=serializer.validated_data["payload"])
        viewset = OrderViewSet(request=request, action="retrieve", format_kwarg=None)
        order = viewset.get_queryset().get(pk=payment.order_id)
        return Response(OrderDetailSerializer(order, context={"request": request}).data)


class WebhookView(APIView):
    """Gateway → server notifications. No login: the HMAC signature over the raw body is the
    authentication. Not throttled (the gateway retries on errors). Each event is applied once."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(request=None, responses={200: None, 400: None})
    def post(self, request, provider):
        body = request.body  # raw bytes, exactly as signed
        try:
            event = services.process_webhook(provider, body=body, headers=request.headers)
        except (services.WebhookRejected, services.NotFoundError):
            raise
        except Exception:
            logger.exception("Webhook processing failed (%s); the gateway will redeliver.", provider)
            return Response({"status": "error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"status": event.status, "event_id": event.event_id})


class StaffRefundSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="payment.order.order_number", read_only=True)
    payment_provider = serializers.CharField(source="payment.provider", read_only=True)
    customer_name = serializers.CharField(source="payment.order.user.full_name", read_only=True)
    store_name = serializers.CharField(source="payment.order.store.name", read_only=True, default=None)
    is_manual = serializers.BooleanField(read_only=True)

    class Meta:
        model = Refund
        fields = [
            "public_id",
            "order_number",
            "payment_provider",
            "customer_name",
            "store_name",
            "amount",
            "status",
            "reason",
            "is_manual",
            "provider_refund_id",
            "attempts",
            "failure_reason",
            "manual_reference",
            "created_at",
            "processed_at",
        ]


class ManualRefundSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=100, help_text="UPI/bank reference or cash receipt number.")


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("status", str),
            OpenApiParameter("q", str, description="Order number, customer name or email, refund reference"),
            OpenApiParameter("store", int),
        ]
    )
)
class StaffRefundViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Refunds of the staff member's stores (admins: all). Customers see theirs on the order."""

    permission_classes = [IsStaffRole]
    serializer_class = StaffRefundSerializer
    lookup_field = "public_id"

    def get_queryset(self):
        qs = Refund.objects.select_related("payment__order__user", "payment__order__store")
        store_ids = managed_store_ids(self.request.user)
        if store_ids is not None:
            qs = qs.filter(Q(payment__order__store_id__in=store_ids))
        if status_filter := self.request.query_params.get("status"):
            qs = qs.filter(status=status_filter)
        params = self.request.query_params
        if term := (params.get("q") or "").strip():
            qs = qs.filter(
                Q(payment__order__order_number__icontains=term)
                | Q(payment__order__user__full_name__icontains=term)
                | Q(payment__order__user__email__icontains=term)
                | Q(provider_refund_id__icontains=term)
                | Q(manual_reference__icontains=term)
            )
        if (store := params.get("store")) and store.isdigit():
            qs = qs.filter(payment__order__store_id=store)
        return qs

    def _done(self, refund):
        return Response(StaffRefundSerializer(Refund.objects.select_related("payment__order").get(pk=refund.pk)).data)

    @extend_schema(request=None, responses=StaffRefundSerializer)
    @action(detail=True, methods=["post"])
    def retry(self, request, public_id=None):
        """Send a failed gateway refund again (new gateway reference)."""
        return self._done(refunds.retry_refund(self.get_object(), actor=request.user))

    @extend_schema(request=ManualRefundSerializer, responses=StaffRefundSerializer)
    @action(detail=True, methods=["post"], url_path="mark-processed")
    def mark_processed(self, request, public_id=None):
        """Record a refund paid by hand (COD cash/UPI, or after a gateway failure)."""
        serializer = ManualRefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refund = refunds.mark_refund_processed(
            self.get_object(), actor=request.user, reference=serializer.validated_data["reference"]
        )
        return self._done(refund)
