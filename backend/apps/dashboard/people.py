"""Customers, delivery partners, their jobs, and support conversations for the dashboard.

- Customers and other accounts: administrators only. Passwords, tokens and password-reset data
  are never part of any response. Role and status changes go through
  `accounts.admin_services.update_user` (`PATCH /api/admin/users/{id}/`), which audit-logs them.
- Delivery partners: managers see the riders based at their stores; only administrators verify
  riders or change their capacity and home store.
- Support: managers see conversations about orders of their stores; administrators see all.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError
from apps.core.money import ZERO, q
from apps.core.permissions import IsAdminRole, IsStaffRole, is_admin, managed_store_ids
from apps.delivery.assignment import partners_with_load
from apps.delivery.cod import cash_by_partner
from apps.delivery.models import DeliveryAssignment, DeliveryPartner
from apps.delivery.serializers import StaffAssignmentSerializer
from apps.orders.models import Order, OrderStatus, PaymentStatus
from apps.stores.models import Store
from apps.support import services as support_services
from apps.support.models import SupportConversation, SupportMessage

from .scope import local_day_start, store_ids_for

User = get_user_model()
PAID = (PaymentStatus.PAID, PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.REFUNDED)
A = DeliveryAssignment.Status


# --- Customers -----------------------------------------------------------------------------------


class CustomerListSerializer(serializers.ModelSerializer):
    order_count = serializers.IntegerField(read_only=True)
    total_spend = serializers.SerializerMethodField()
    last_order_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "phone",
            "role",
            "is_active",
            "email_verified",
            "date_joined",
            "last_login",
            "order_count",
            "total_spend",
            "last_order_at",
        ]
        read_only_fields = fields

    def get_total_spend(self, obj) -> str:
        return str(q(getattr(obj, "total_spend", None) or ZERO))


class CustomerDetailSerializer(CustomerListSerializer):
    recent_orders = serializers.SerializerMethodField()
    addresses = serializers.SerializerMethodField()
    cancelled_orders = serializers.SerializerMethodField()
    returns = serializers.SerializerMethodField()
    managed_stores = serializers.SerializerMethodField()

    class Meta(CustomerListSerializer.Meta):
        fields = CustomerListSerializer.Meta.fields + [
            "deactivated_at",
            "cancelled_orders",
            "returns",
            "addresses",
            "managed_stores",
            "recent_orders",
        ]
        read_only_fields = fields

    def get_recent_orders(self, obj) -> list[dict]:
        orders = Order.objects.filter(user=obj).select_related("store").order_by("-created_at")[:10]
        return [
            {
                "order_number": o.order_number,
                "status": o.status,
                "payment_status": o.payment_status,
                "grand_total": str(o.grand_total),
                "store_name": o.store.name if o.store_id else None,
                "created_at": o.created_at,
            }
            for o in orders
        ]

    def get_addresses(self, obj) -> list[dict]:
        rows = obj.addresses.filter(is_deleted=False).order_by("-is_default", "id")[:10]
        return [
            {"area": a.area, "city": a.city, "postal_code": a.postal_code, "is_default": a.is_default} for a in rows
        ]

    def get_cancelled_orders(self, obj) -> int:
        return Order.objects.filter(user=obj, status=OrderStatus.CANCELLED).count()

    def get_returns(self, obj) -> int:
        return obj.return_requests.count()

    def get_managed_stores(self, obj) -> list[dict]:
        return [{"id": s.pk, "name": s.name, "code": s.code} for s in obj.managed_stores.all()]


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Name, email or phone"),
            OpenApiParameter("role", str, description="Default: customer. 'all' lists every account"),
            OpenApiParameter("is_active", bool),
            OpenApiParameter("has_orders", bool),
            OpenApiParameter(
                "ordering", str, enum=["-date_joined", "date_joined", "-total_spend", "-order_count", "-last_order_at"]
            ),
        ]
    )
)
class AdminCustomerViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminRole]
    ORDERINGS = ("-date_joined", "date_joined", "-total_spend", "-order_count", "-last_order_at")

    def get_serializer_class(self):
        return CustomerListSerializer if self.action == "list" else CustomerDetailSerializer

    def get_queryset(self):
        counted = ~Q(orders__status=OrderStatus.CANCELLED)
        qs = User.objects.annotate(
            order_count=Count("orders", filter=counted, distinct=True),
            total_spend=Sum("orders__grand_total", filter=Q(orders__payment_status__in=PAID)),
            last_order_at=Max("orders__created_at"),
        )
        if self.action != "list":
            return qs.prefetch_related("managed_stores")
        params = self.request.query_params
        role = params.get("role") or User.Role.CUSTOMER
        if role != "all":
            qs = qs.filter(role=role)
        if term := (params.get("q") or "").strip():
            qs = qs.filter(Q(full_name__icontains=term) | Q(email__icontains=term) | Q(phone__icontains=term))
        if (active := params.get("is_active")) in ("true", "false"):
            qs = qs.filter(is_active=active == "true")
        if params.get("has_orders") in ("1", "true"):
            qs = qs.filter(order_count__gt=0)
        ordering = params.get("ordering")
        return qs.order_by(ordering if ordering in self.ORDERINGS else "-date_joined", "-id")


# --- Delivery partners ---------------------------------------------------------------------------


class RiderSerializer(serializers.Serializer):
    partner_id = serializers.IntegerField(source="pk")
    user_id = serializers.IntegerField()
    full_name = serializers.CharField(source="user.full_name")
    email = serializers.CharField(source="user.email")
    phone = serializers.CharField()
    vehicle_type = serializers.CharField()
    vehicle_number = serializers.CharField()
    home_store = serializers.IntegerField(source="home_store_id", allow_null=True)
    home_store_name = serializers.CharField(source="home_store.name", default=None)
    status = serializers.CharField()
    is_verified = serializers.BooleanField()
    is_active = serializers.BooleanField()
    active_assignments = serializers.IntegerField(source="active_count")
    capacity = serializers.IntegerField(source="max_active_assignments")
    can_take_jobs = serializers.SerializerMethodField()
    last_location_at = serializers.DateTimeField(allow_null=True)
    cash_in_hand = serializers.SerializerMethodField()
    delivered = serializers.SerializerMethodField()
    delivered_today = serializers.SerializerMethodField()
    failed = serializers.SerializerMethodField()
    earnings_today = serializers.SerializerMethodField()
    earnings_7_days = serializers.SerializerMethodField()
    earnings_total = serializers.SerializerMethodField()

    def _stat(self, obj, key, default=0):
        return self.context.get("stats", {}).get(obj.pk, {}).get(key) or default

    def get_can_take_jobs(self, obj) -> bool:
        online = obj.status == DeliveryPartner.Status.AVAILABLE
        return obj.is_active and obj.is_verified and online and obj.active_count < obj.max_active_assignments

    def get_cash_in_hand(self, obj) -> str:
        return str(self.context.get("cash", {}).get(obj.pk, q(ZERO)))

    def get_delivered(self, obj) -> int:
        return self._stat(obj, "delivered")

    def get_delivered_today(self, obj) -> int:
        return self._stat(obj, "delivered_today")

    def get_failed(self, obj) -> int:
        return self._stat(obj, "failed")

    def get_earnings_today(self, obj) -> str:
        return str(q(self._stat(obj, "earned_today", ZERO)))

    def get_earnings_7_days(self, obj) -> str:
        return str(q(self._stat(obj, "earned_week", ZERO)))

    def get_earnings_total(self, obj) -> str:
        return str(q(self._stat(obj, "earned", ZERO)))


class RiderUpdateSerializer(serializers.Serializer):
    is_verified = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
    max_active_assignments = serializers.IntegerField(min_value=1, max_value=10, required=False)
    home_store = serializers.PrimaryKeyRelatedField(
        queryset=Store.objects.filter(kind__in=Store.FULFILLMENT_KINDS), required=False, allow_null=True
    )
    vehicle_type = serializers.ChoiceField(choices=DeliveryPartner.Vehicle.choices, required=False)
    vehicle_number = serializers.CharField(max_length=20, required=False, allow_blank=True)


def rider_stats(partner_ids) -> dict:
    now = timezone.now()
    today = local_day_start(timezone.localdate())
    week = now - timedelta(days=7)
    delivered = Q(status=A.DELIVERED)
    rows = (
        DeliveryAssignment.objects.filter(partner_id__in=list(partner_ids))
        .values("partner_id")
        .annotate(
            delivered=Count("id", filter=delivered),
            delivered_today=Count("id", filter=delivered & Q(delivered_at__gte=today)),
            failed=Count("id", filter=Q(status=A.FAILED)),
            earned=Sum("earning_amount"),
            earned_today=Sum("earning_amount", filter=Q(delivered_at__gte=today) | Q(failed_at__gte=today)),
            earned_week=Sum("earning_amount", filter=Q(delivered_at__gte=week) | Q(failed_at__gte=week)),
        )
    )
    return {row["partner_id"]: row for row in rows}


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Name, email, phone or vehicle number"),
            OpenApiParameter("status", str, enum=["offline", "available", "busy", "online"]),
            OpenApiParameter("store", int),
            OpenApiParameter("is_verified", bool),
            OpenApiParameter("is_active", bool),
        ],
        responses=RiderSerializer(many=True),
    )
)
class AdminRiderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsStaffRole]
    serializer_class = RiderSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DeliveryPartner.objects.none()
        qs = partners_with_load()
        store_ids = store_ids_for(self.request)
        if store_ids is not None:
            qs = qs.filter(home_store_id__in=store_ids)
        params = self.request.query_params
        if term := (params.get("q") or "").strip():
            qs = qs.filter(
                Q(user__full_name__icontains=term)
                | Q(user__email__icontains=term)
                | Q(phone__icontains=term)
                | Q(vehicle_number__icontains=term)
            )
        wanted = params.get("status")
        if wanted == "online":
            qs = qs.filter(status__in=("available", "busy"))
        elif wanted in DeliveryPartner.Status.values:
            qs = qs.filter(status=wanted)
        for name in ("is_verified", "is_active"):
            if (value := params.get(name)) in ("true", "false"):
                qs = qs.filter(**{name: value == "true"})
        return qs.order_by("home_store__name", "user__full_name", "id")

    def _rows(self, partners, many=True):
        items = list(partners) if many else [partners]
        ids = [p.pk for p in items]
        context = {"stats": rider_stats(ids), "cash": cash_by_partner(ids)}
        return RiderSerializer(items if many else items[0], many=many, context=context).data

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(self._rows(page))

    def retrieve(self, request, *args, **kwargs):
        return Response(self._rows(self.get_object(), many=False))

    @extend_schema(request=RiderUpdateSerializer, responses=RiderSerializer)
    @transaction.atomic
    def partial_update(self, request, pk=None):
        """Verify a rider, change capacity, home store or vehicle (administrators)."""
        if not is_admin(request.user):
            raise PermissionDenied("Only an administrator can change delivery partner records.")
        partner = DeliveryPartner.objects.select_for_update().get(pk=self.get_object().pk)
        serializer = RiderUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        stops = data.get("is_active") is False or data.get("is_verified") is False
        if stops and partner.assignments.filter(status__in=DeliveryAssignment.ACTIVE_STATUSES).exists():
            raise ConflictError(
                "This delivery partner has an active job. Reassign it or wait until it is finished.",
                code="active_delivery",
            )
        for field, value in data.items():
            setattr(partner, field, value)
        if stops:
            partner.status = DeliveryPartner.Status.OFFLINE
        partner.save()
        record_audit(
            action="delivery.partner_update",
            actor=request.user,
            target=partner,
            request=request,
            changes={k: (v.pk if hasattr(v, "pk") else v) for k, v in data.items()},
        )
        return Response(self._rows(self.get_queryset().get(pk=partner.pk), many=False))


class JobRowSerializer(StaffAssignmentSerializer):
    order_number = serializers.CharField(source="order.order_number")
    order_status = serializers.CharField(source="order.status")
    shipment_id = serializers.IntegerField(allow_null=True)
    store_name = serializers.SerializerMethodField()
    return_number = serializers.CharField(source="return_request.return_number", default=None)
    distance_km = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)

    class Meta(StaffAssignmentSerializer.Meta):
        fields = [f for f in StaffAssignmentSerializer.Meta.fields if f != "status_history"] + [
            "order_number",
            "order_status",
            "shipment_id",
            "store_name",
            "return_number",
            "distance_km",
        ]

    def get_store_name(self, obj) -> str | None:
        store = obj.shipment.store if obj.shipment_id else obj.order.store
        return store.name if store else None


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("status", str, description="A status, or: active, completed, failed"),
            OpenApiParameter("kind", str, enum=["delivery", "return_pickup"]),
            OpenApiParameter("partner", int),
            OpenApiParameter("store", int),
            OpenApiParameter("q", str, description="Order number or rider name"),
        ]
    )
)
class AdminJobViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Every rider job at the staff member's stores: active, completed, failed, rejected."""

    permission_classes = [IsStaffRole]
    serializer_class = JobRowSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DeliveryAssignment.objects.none()
        qs = DeliveryAssignment.objects.select_related(
            "order__store", "shipment__store", "partner__user", "return_request"
        ).prefetch_related("status_history")
        store_ids = store_ids_for(self.request)
        if store_ids is not None:
            # A return pickup has no shipment; it belongs to the store that receives the goods back.
            qs = qs.filter(
                Q(shipment__store_id__in=store_ids) | Q(shipment__isnull=True, order__store_id__in=store_ids)
            )
        params = self.request.query_params
        wanted = params.get("status")
        if wanted == "active":
            qs = qs.filter(status__in=DeliveryAssignment.ACTIVE_STATUSES)
        elif wanted == "completed":
            qs = qs.filter(status=A.DELIVERED)
        elif wanted in A.values:
            qs = qs.filter(status=wanted)
        if (kind := params.get("kind")) in DeliveryAssignment.Kind.values:
            qs = qs.filter(kind=kind)
        if (partner := params.get("partner")) and partner.isdigit():
            qs = qs.filter(partner_id=partner)
        if term := (params.get("q") or "").strip():
            qs = qs.filter(Q(order__order_number__icontains=term) | Q(partner__user__full_name__icontains=term))
        return qs.order_by("-assigned_at", "-id")


# --- Support -------------------------------------------------------------------------------------


class SupportMessageRowSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()

    class Meta:
        model = SupportMessage
        fields = ["id", "sender_type", "sender_name", "body", "created_at"]

    def get_sender_name(self, obj) -> str:
        if obj.sender_type == SupportMessage.Sender.CUSTOMER:
            return obj.sender.full_name if obj.sender_id else "Customer"
        if obj.sender_type == SupportMessage.Sender.AGENT:
            return obj.sender.full_name if obj.sender_id else "Support"
        return obj.get_sender_type_display()


class SupportListSerializer(serializers.ModelSerializer):
    customer = serializers.SerializerMethodField()
    order_number = serializers.CharField(source="order.order_number", default=None)
    store_name = serializers.CharField(source="order.store.name", default=None)
    status_label = serializers.CharField(source="get_status_display")
    assigned_to_name = serializers.CharField(source="assigned_to.full_name", default=None)
    message_count = serializers.IntegerField(read_only=True, default=0)
    last_message = serializers.SerializerMethodField()
    waiting_for_reply = serializers.SerializerMethodField()

    class Meta:
        model = SupportConversation
        fields = [
            "id",
            "subject",
            "channel",
            "status",
            "status_label",
            "customer",
            "order_number",
            "store_name",
            "assigned_to",
            "assigned_to_name",
            "message_count",
            "last_message",
            "waiting_for_reply",
            "last_message_at",
            "created_at",
        ]

    def get_customer(self, obj) -> dict | None:
        if obj.user_id is None:
            return {"id": None, "name": "", "email": "", "phone": obj.contact_phone}
        return {"id": obj.user_id, "name": obj.user.full_name, "email": obj.user.email, "phone": obj.user.phone or ""}

    def _last(self, obj):
        messages = list(obj.messages.all())
        return messages[-1] if messages else None

    def get_last_message(self, obj) -> str:
        last = self._last(obj)
        return (last.body[:140] + ("…" if len(last.body) > 140 else "")) if last else ""

    def get_waiting_for_reply(self, obj) -> bool:
        last = self._last(obj)
        open_ = obj.status in (SupportConversation.Status.OPEN, SupportConversation.Status.WAITING_CUSTOMER)
        return bool(last and open_ and last.sender_type == SupportMessage.Sender.CUSTOMER)


class SupportDetailSerializer(SupportListSerializer):
    messages = SupportMessageRowSerializer(many=True, read_only=True)

    class Meta(SupportListSerializer.Meta):
        fields = SupportListSerializer.Meta.fields + ["messages"]


class ReplySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=4000)


class SupportUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=SupportConversation.Status.choices, required=False)
    assign_to_me = serializers.BooleanField(required=False)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("status", str, description="A status, or 'active' (open or waiting for the customer)"),
            OpenApiParameter("q", str, description="Subject, customer name, email, phone or order number"),
            OpenApiParameter("mine", bool, description="Assigned to me"),
            OpenApiParameter("store", int),
        ]
    )
)
class AdminSupportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsStaffRole]

    def get_serializer_class(self):
        return SupportListSerializer if self.action == "list" else SupportDetailSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SupportConversation.objects.none()
        qs = (
            SupportConversation.objects.select_related("user", "order__store", "assigned_to")
            .prefetch_related(Prefetch("messages", queryset=SupportMessage.objects.select_related("sender")))
            .annotate(message_count=Count("messages"))
        )
        allowed = managed_store_ids(self.request.user)
        if allowed is not None:
            qs = qs.filter(order__store_id__in=allowed)  # managers: conversations about their stores' orders
        params = self.request.query_params
        if (store := params.get("store")) and store.isdigit():
            qs = qs.filter(order__store_id=store)
        wanted = params.get("status")
        if wanted == "active":
            qs = qs.filter(status__in=("open", "waiting_customer"))
        elif wanted in SupportConversation.Status.values:
            qs = qs.filter(status=wanted)
        if params.get("mine") in ("1", "true"):
            qs = qs.filter(assigned_to=self.request.user)
        if term := (params.get("q") or "").strip():
            qs = qs.filter(
                Q(subject__icontains=term)
                | Q(user__full_name__icontains=term)
                | Q(user__email__icontains=term)
                | Q(user__phone__icontains=term)
                | Q(contact_phone__icontains=term)
                | Q(order__order_number__icontains=term)
            )
        return qs.order_by("-last_message_at", "-created_at")

    def _detail(self, conversation, status_code=status.HTTP_200_OK):
        fresh = self.get_queryset().get(pk=conversation.pk)
        return Response(SupportDetailSerializer(fresh).data, status=status_code)

    @extend_schema(request=ReplySerializer, responses={201: SupportDetailSerializer})
    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        """Answer the customer. The conversation then waits for the customer."""
        conversation = self.get_object()
        serializer = ReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            support_services.post_message(
                conversation,
                sender=request.user,
                sender_type=SupportMessage.Sender.AGENT,
                body=serializer.validated_data["body"],
            )
            fields = {"status": SupportConversation.Status.WAITING_CUSTOMER}
            if conversation.assigned_to_id is None:
                fields["assigned_to"] = request.user
            SupportConversation.objects.filter(pk=conversation.pk).update(**fields)
        return self._detail(conversation, status.HTTP_201_CREATED)

    @extend_schema(request=SupportUpdateSerializer, responses=SupportDetailSerializer)
    def partial_update(self, request, pk=None):
        conversation = self.get_object()
        serializer = SupportUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data, fields = serializer.validated_data, {}
        if "status" in data:
            fields["status"] = data["status"]
        if data.get("assign_to_me"):
            fields["assigned_to"] = request.user
        if fields:
            SupportConversation.objects.filter(pk=conversation.pk).update(**fields, updated_at=timezone.now())
            record_audit(
                action="support.update",
                actor=request.user,
                target=conversation,
                request=request,
                changes={k: (v.pk if hasattr(v, "pk") else v) for k, v in fields.items()},
            )
        return self._detail(conversation)
