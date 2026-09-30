"""Orders for staff: search, filters and a detail view with the customer and every shipment.

Reading only. Every change goes through the endpoints that already enforce the rules:
`POST /api/orders/{n}/transition/`, the returns and refunds endpoints and the shipment
endpoints of apps.delivery. `allowed_actions` tells the dashboard which buttons to show; the
server checks each action again when it is used.
"""

from django.db.models import Count, Prefetch, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from rest_framework import mixins, serializers, viewsets

from apps.catalog.models import ProductImage
from apps.core.permissions import IsStaffRole
from apps.delivery.assignment import has_rider_in_charge
from apps.delivery.models import DeliveryAssignment
from apps.delivery.serializers import StaffShipmentSerializer, latest_delivery
from apps.orders.models import Order, OrderItem, OrderShipment, OrderStatus, ReturnRequest
from apps.orders.serializers import OrderDetailSerializer
from apps.orders.shipments import LEFT_THE_STORE
from apps.orders.state_machine import DELIVERY_STATUSES, RETURN_WORKFLOW_STATUSES, TRANSITIONS
from apps.payments.models import Payment, Refund

from .scope import date_range, may_manage_store, scope_orders, store_ids_for

STATUS_GROUPS = {
    "open": [s for s in OrderStatus.values if s not in ("delivered", "cancelled", "returned")],
    "preparing": ["confirmed", "processing", "packed"],
    "on_the_way": ["assigned", "picked_up", "out_for_delivery"],
    "closed": ["delivered", "cancelled", "returned"],
}


def _customer(order) -> dict:
    user = order.user
    snapshot = order.address_snapshot or {}
    return {
        "id": user.pk,
        "name": user.full_name or snapshot.get("name", ""),
        "email": user.email,
        "phone": user.phone or snapshot.get("phone") or "",
        "is_active": user.is_active,
    }


def _jobs():
    return DeliveryAssignment.objects.select_related("partner__user").order_by("-assigned_at")


class AdminOrderListSerializer(serializers.ModelSerializer):
    customer = serializers.SerializerMethodField()
    store_name = serializers.CharField(source="store.name", default=None)
    item_count = serializers.SerializerMethodField()
    item_names = serializers.SerializerMethodField()
    shipments = serializers.SerializerMethodField()
    open_return = serializers.SerializerMethodField()
    refund_status = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "order_number",
            "status",
            "payment_method",
            "payment_status",
            "grand_total",
            "delivery_type",
            "estimated_delivery_at",
            "created_at",
            "customer",
            "store_name",
            "item_count",
            "item_names",
            "shipments",
            "open_return",
            "refund_status",
        ]

    def get_customer(self, obj) -> dict:
        return _customer(obj)

    def get_item_count(self, obj) -> int:
        return sum(item.quantity for item in obj.items.all())

    def get_item_names(self, obj) -> list[str]:
        return [item.product_name for item in list(obj.items.all())[:3]]

    def get_shipments(self, obj) -> list[dict]:
        rows = []
        for shipment in obj.shipments.all():
            job = latest_delivery(shipment)
            rows.append(
                {
                    "id": shipment.pk,
                    "sequence": shipment.sequence,
                    "store_name": shipment.store.name,
                    "status": shipment.status,
                    "rider": job.partner.user.full_name if job else None,
                }
            )
        return rows

    def get_open_return(self, obj) -> bool:
        return any(r.status in ReturnRequest.OPEN_STATUSES for r in obj.returns.all())

    def get_refund_status(self, obj) -> str | None:
        """The least finished refund of the order: failed, then pending, then processed."""
        found = {refund.status for payment in obj.payments.all() for refund in payment.refunds.all()}
        return next((s for s in ("failed", "pending", "processed") if s in found), None)


class AdminOrderDetailSerializer(OrderDetailSerializer):
    customer = serializers.SerializerMethodField()
    staff_shipments = serializers.SerializerMethodField()
    allowed_actions = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()

    class Meta(OrderDetailSerializer.Meta):
        fields = OrderDetailSerializer.Meta.fields + ["customer", "staff_shipments", "allowed_actions", "can_manage"]

    def get_customer(self, obj) -> dict:
        return _customer(obj)

    @extend_schema_field(StaffShipmentSerializer(many=True))
    def get_staff_shipments(self, obj) -> list[dict]:
        return StaffShipmentSerializer(obj.shipments.all(), many=True).data

    def get_can_manage(self, obj) -> bool:
        return may_manage_store(self.context["request"].user, obj.store_id)

    def get_allowed_actions(self, obj) -> list[dict]:
        """Status changes this user could make now, as the state machine and the delivery rules
        stand. Returns and refunds have their own actions on their own records."""
        if not self.get_can_manage(obj):
            return []
        rider = has_rider_in_charge(obj)
        left_store = any(s.status in LEFT_THE_STORE for s in obj.shipments.all())
        actions = []
        for target in sorted(TRANSITIONS.get(obj.status, ()), key=list(OrderStatus.values).index):
            if target in RETURN_WORKFLOW_STATUSES or obj.status in RETURN_WORKFLOW_STATUSES:
                continue
            if target in DELIVERY_STATUSES and rider:
                continue  # the delivery partner's steps move the order
            if target == OrderStatus.ASSIGNED and rider:
                continue
            if target == OrderStatus.CANCELLED and left_store:
                continue
            actions.append({"status": str(target), "label": OrderStatus(target).label})
        return actions


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Order number, customer name, email or phone, product or SKU"),
            OpenApiParameter("status", str, description="One or more statuses (comma separated), or a group: "
                             "open, preparing, on_the_way, closed"),
            OpenApiParameter("payment_status", str),
            OpenApiParameter("payment_method", str, enum=["cod", "online"]),
            OpenApiParameter("delivery_type", str, enum=["fast", "standard"]),
            OpenApiParameter("store", int),
            OpenApiParameter("customer", int, description="Customer id"),
            OpenApiParameter("from", str, description="Placed on or after (YYYY-MM-DD)"),
            OpenApiParameter("to", str, description="Placed on or before (YYYY-MM-DD)"),
            OpenApiParameter("has_return", bool),
            OpenApiParameter("ordering", str, enum=["-created_at", "created_at", "-grand_total", "grand_total"]),
        ]
    )
)  # fmt: skip
class AdminOrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Admins: all orders. Store managers: orders of their stores only (others are "not found")."""

    permission_classes = [IsStaffRole]
    lookup_field = "order_number"
    ORDERINGS = ("-created_at", "created_at", "-grand_total", "grand_total")

    def get_serializer_class(self):
        return AdminOrderListSerializer if self.action == "list" else AdminOrderDetailSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        images = Prefetch("product__images", queryset=ProductImage.objects.order_by("-is_primary", "sort_order"))
        shipments = OrderShipment.objects.select_related("store", "order").prefetch_related(
            "items", Prefetch("assignments", queryset=_jobs())
        )
        returns = ReturnRequest.objects.select_related("order", "refund").prefetch_related(
            Prefetch("pickups", queryset=_jobs()), "items__order_item__product__images"
        )
        qs = Order.objects.select_related("store", "user").prefetch_related(
            Prefetch("items", queryset=OrderItem.objects.select_related("product").prefetch_related(images)),
            Prefetch("shipments", queryset=shipments),
            Prefetch("payments", queryset=Payment.objects.prefetch_related(Prefetch("refunds", Refund.objects.all()))),
            Prefetch("returns", queryset=returns),
            "status_history",
        )
        qs = scope_orders(qs, store_ids_for(self.request))
        return self._filter(qs) if self.action == "list" else qs

    def _filter(self, qs):
        params = self.request.query_params
        if term := (params.get("q") or "").strip():
            lines = OrderItem.objects.filter(Q(product_name__icontains=term) | Q(sku__icontains=term))
            qs = qs.filter(
                Q(order_number__icontains=term)
                | Q(user__full_name__icontains=term)
                | Q(user__email__icontains=term)
                | Q(user__phone__icontains=term)
                | Q(pk__in=lines.values("order_id"))
            )
        if wanted := (params.get("status") or "").strip():
            statuses = STATUS_GROUPS.get(wanted) or [s for s in wanted.split(",") if s in OrderStatus.values]
            qs = qs.filter(status__in=statuses)
        for name in ("payment_status", "payment_method", "delivery_type"):
            if value := params.get(name):
                qs = qs.filter(**{name: value})
        if (customer := params.get("customer")) and customer.isdigit():
            qs = qs.filter(user_id=customer)
        if params.get("from") or params.get("to"):
            _first, _last, start, end = date_range(self.request, default_days=366)
            qs = qs.filter(created_at__gte=start, created_at__lt=end)
        if params.get("has_return") in ("1", "true"):
            qs = qs.annotate(return_count=Count("returns")).filter(return_count__gt=0)
        ordering = params.get("ordering")
        return qs.order_by(ordering if ordering in self.ORDERINGS else "-created_at", "-id")
