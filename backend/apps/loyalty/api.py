"""Loyalty HTTP API (Phase 17).

Customers (`/api/loyalty/…`): their own wallet, ledger and referral code — read only, apart from claiming
a referral code once. Nothing a customer sends changes a balance.
Administrators (`/api/admin/loyalty/…`): settings, cashback rules, promotional credits (always a ledger
entry with a reason, audited), the ledger of any customer, referrals.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Category, Product
from apps.core.audit import record_audit
from apps.core.exceptions import NotFoundError
from apps.core.money import ZERO, q
from apps.core.permissions import IsAdminRole

from . import ledger
from .models import CashbackRule, CreditEntry, LoyaltySettings, Referral, ReferralCode

K, S = CreditEntry.Kind, CreditEntry.Status


class LedgerPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class CreditEntrySerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display")
    status_label = serializers.CharField(source="get_status_display")
    order_number = serializers.CharField(source="order.order_number", default=None)
    remaining = serializers.SerializerMethodField()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if ledger.is_welcome(instance):
            data["kind_label"] = "Welcome reward"
        return data

    class Meta:
        model = CreditEntry
        fields = [
            "id",
            "kind",
            "kind_label",
            "status",
            "status_label",
            "amount",
            "remaining",
            "available_at",
            "expires_at",
            "order_number",
            "reference",
            "description",
            "created_at",
        ]

    def get_remaining(self, obj) -> str | None:
        """For credits: what is left of this credit (used/expired parts taken off)."""
        if obj.kind not in CreditEntry.CREDIT_KINDS or obj.status != S.AVAILABLE:
            return None
        used = getattr(obj, "used_total", None)
        if used is None:
            used = obj.used_by.aggregate(t=Sum("amount"))["t"] or ZERO
        return str(q(obj.amount - used))


def wallet_summary(user) -> dict:
    """Balance and totals by kind of movement, all from the ledger."""
    rows = CreditEntry.objects.filter(user=user)

    def total(**filters) -> Decimal:
        return q(rows.filter(**filters).aggregate(t=Sum("amount"))["t"] or ZERO)

    rules = LoyaltySettings.load()
    soon, first_expiry = ledger.expiring_soon(user)
    code = ReferralCode.for_user(user)
    referral = Referral.objects.filter(referee=user).select_related("referrer").first()
    made = Referral.objects.filter(referrer=user)
    # Rewards for friends' orders (the friend's own referral reward is on their order, not this user's).
    for_friends = rows.filter(kind=K.REFERRAL).exclude(order__user=user)
    welcome = rows.filter(kind=K.PROMO, reference__startswith=ledger.WELCOME_PREFIX).first()
    return {
        "balance": str(ledger.balance(user)),
        "spendable": str(ledger.spendable(user)),
        "pending": str(total(status=S.PENDING)),
        "eligible": str(total(status=S.ELIGIBLE)),
        "earned": str(total(kind__in=(K.CASHBACK, K.PROMO, K.REFERRAL), status__in=(S.AVAILABLE, S.EXPIRED))),
        "restored": str(total(kind=K.RESTORE)),
        "used": str(-total(kind=K.REDEMPTION)),
        "expired": str(-total(kind=K.EXPIRY)),
        "reversed": str(total(status=S.REVERSED)),
        "expiring_soon": {"amount": str(soon), "first_expiry": first_expiry, "within_days": 14},
        "rules": {
            "enabled": rules.credits_enabled,
            "max_order_share": str(rules.max_order_share),
            "expiry_days": rules.expiry_days,
            "never_cash": True,
            "referral_reward": str(rules.referral_reward),
            "referee_reward": str(rules.referee_reward),
            "welcome_reward": str(rules.welcome_reward),
        },
        "referral": {
            "code": code.code,
            "rewards_on": rules.referral_reward > 0 or rules.referee_reward > 0,
            "joined": made.count(),
            "rewarded": made.filter(status=Referral.Status.REWARDED).count(),
            # Joined with the code, first order not delivered yet.
            "waiting": made.filter(status=Referral.Status.JOINED).count(),
            "credited": str(total(kind=K.REFERRAL, status__in=(S.AVAILABLE, S.EXPIRED), pk__in=for_friends)),
            "pending": str(total(kind=K.REFERRAL, status__in=CreditEntry.WAITING, pk__in=for_friends)),
            "used_code": bool(referral),
        },
        "welcome": _welcome_state(user, rules, welcome),
    }


def _welcome_state(user, rules, entry) -> dict | None:
    """The welcome reward as this customer sees it: the one they earned (with its status), the offer if
    their first order hasn't been delivered yet, or nothing."""
    if entry is not None:
        return {
            "amount": str(entry.amount),
            "status": entry.status,
            "status_label": entry.get_status_display(),
            "available_at": entry.available_at,
            "order_number": entry.reference.removeprefix(ledger.WELCOME_PREFIX),
        }
    if rules.welcome_reward <= 0:
        return None
    from apps.orders.models import Order

    if Order.objects.filter(user=user, delivered_at__isnull=False).exists():
        return None
    return {"amount": str(rules.welcome_reward), "status": "offer", "status_label": "On your first delivered order"}


class WalletView(APIView):
    """GET /api/loyalty/wallet/ — the signed-in customer's balance and totals."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, description="Balance and totals from the ledger.")
    def get(self, request):
        return Response(wallet_summary(request.user))


@extend_schema_view(list=extend_schema(parameters=[OpenApiParameter("kind", str), OpenApiParameter("status", str)]))
class LedgerViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/loyalty/ledger/ — the customer's own entries, newest first (read only)."""

    permission_classes = [IsAuthenticated]
    serializer_class = CreditEntrySerializer
    pagination_class = LedgerPagination
    queryset = CreditEntry.objects.none()  # for the schema; get_queryset scopes to the customer

    def get_queryset(self):
        qs = CreditEntry.objects.filter(user=self.request.user).select_related("order")
        params = self.request.query_params
        if kind := params.get("kind"):
            qs = qs.filter(kind=kind)
        if state := params.get("status"):
            qs = qs.filter(status=state)
        return qs.annotate(used_total=Sum("used_by__amount")).order_by("-created_at", "-id")


class ReferralClaimSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=12)


class ReferralClaimView(APIView):
    """POST /api/loyalty/referral/ {code} — a new customer (no orders yet) names who referred them."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReferralClaimSerializer, responses={201: None})
    def post(self, request):
        serializer = ReferralClaimSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            referral = ledger.claim_referral(request.user, serializer.validated_data["code"])
        return Response({"referrer": referral.referrer.full_name.split(" ")[0] or "A customer"}, status=201)


# --- Administrators -------------------------------------------------------------------------------


class LoyaltySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoyaltySettings
        fields = [
            "credits_enabled",
            "max_order_share",
            "expiry_days",
            "referral_reward",
            "referee_reward",
            "welcome_reward",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


class AdminLoyaltySettingsView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(responses=LoyaltySettingsSerializer)
    def get(self, request):
        return Response(LoyaltySettingsSerializer(LoyaltySettings.load()).data)

    @extend_schema(request=LoyaltySettingsSerializer, responses=LoyaltySettingsSerializer)
    def patch(self, request):
        settings_row = LoyaltySettings.load()
        serializer = LoyaltySettingsSerializer(settings_row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        before = {f: str(getattr(settings_row, f)) for f in serializer.validated_data}
        settings_row = serializer.save(updated_by=request.user)
        record_audit(
            action="loyalty_settings.update",
            actor=request.user,
            target=settings_row,
            request=request,
            changes={f: {"from": before[f], "to": str(getattr(settings_row, f))} for f in serializer.validated_data},
        )
        return Response(LoyaltySettingsSerializer(settings_row).data)


class CashbackRuleSerializer(serializers.ModelSerializer):
    products = serializers.PrimaryKeyRelatedField(many=True, queryset=Product.objects.all(), required=False)
    categories = serializers.PrimaryKeyRelatedField(many=True, queryset=Category.objects.all(), required=False)
    summary = serializers.CharField(read_only=True)
    state = serializers.SerializerMethodField()

    class Meta:
        model = CashbackRule
        fields = [
            "id",
            "name",
            "description",
            "reward_type",
            "percent",
            "fixed_amount",
            "max_amount",
            "min_order_value",
            "products",
            "categories",
            "first_order_only",
            "starts_at",
            "ends_at",
            "is_active",
            "priority",
            "summary",
            "state",
            "created_at",
            "updated_at",
        ]

    def get_state(self, obj) -> str:
        now = timezone.now()
        if not obj.is_active:
            return "inactive"
        if obj.starts_at > now:
            return "scheduled"
        if obj.ends_at and obj.ends_at <= now:
            return "expired"
        return "live"

    def validate(self, attrs):
        reward_type = attrs.get("reward_type", getattr(self.instance, "reward_type", CashbackRule.RewardType.PERCENT))
        percent = attrs.get("percent", getattr(self.instance, "percent", None))
        fixed = attrs.get("fixed_amount", getattr(self.instance, "fixed_amount", None))
        if reward_type == CashbackRule.RewardType.PERCENT and not percent:
            raise serializers.ValidationError({"percent": "Enter the cashback %."})
        if reward_type == CashbackRule.RewardType.FIXED and not fixed:
            raise serializers.ValidationError({"fixed_amount": "Enter the cashback amount."})
        starts = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_at": "End must be after start."})
        return attrs


class AdminCashbackRuleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminRole]
    serializer_class = CashbackRuleSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return CashbackRule.objects.prefetch_related("products", "categories").order_by("priority", "id")

    def perform_create(self, serializer):
        rule = serializer.save()
        record_audit(action="cashback_rule.create", actor=self.request.user, target=rule, request=self.request)

    def perform_update(self, serializer):
        rule = serializer.save()
        record_audit(
            action="cashback_rule.update",
            actor=self.request.user,
            target=rule,
            request=self.request,
            changes={"fields": sorted(serializer.validated_data)},
        )

    def perform_destroy(self, instance):
        record_audit(action="cashback_rule.delete", actor=self.request.user, target=instance, request=self.request)
        instance.delete()  # orders keep their cashback snapshot and ledger entries


class PromoCreditSerializer(serializers.Serializer):
    user = serializers.IntegerField(help_text="Customer id")
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("1.00"), max_value=Decimal("100000")
    )
    reason = serializers.CharField(max_length=200, help_text="Shown to the customer and kept in the audit log.")
    expiry_days = serializers.IntegerField(min_value=1, max_value=3650, required=False)


class AdminPromoCreditView(APIView):
    """POST /api/admin/loyalty/promo-credits/ — give a customer promotional credit. The only way an
    administrator adds credit: a ledger entry with a reason, audited. Balances are never edited."""

    permission_classes = [IsAdminRole]

    @extend_schema(request=PromoCreditSerializer, responses={201: CreditEntrySerializer})
    def post(self, request):
        serializer = PromoCreditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = get_user_model().objects.filter(pk=data["user"], role="customer", is_active=True).first()
        if user is None:
            raise NotFoundError("Customer not found.")
        with transaction.atomic():
            entry = ledger.grant(
                user,
                K.PROMO,
                data["amount"],
                reference=f"admin:{request.user.pk}",
                description=data["reason"],
                actor=request.user,
                expiry_days=data.get("expiry_days"),
            )
            record_audit(
                action="loyalty.promo_credit",
                actor=request.user,
                target=entry,
                request=request,
                changes={"user": user.pk, "amount": str(entry.amount), "reason": data["reason"]},
            )
        return Response(CreditEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("user", int),
            OpenApiParameter("kind", str),
            OpenApiParameter("status", str),
            OpenApiParameter("q", str, description="Customer email/name, order number or reference"),
        ]
    )
)
class AdminLedgerViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/admin/loyalty/ledger/ — every entry, filterable; read only (no edits, no deletes)."""

    permission_classes = [IsAdminRole]
    pagination_class = LedgerPagination

    class Row(CreditEntrySerializer):
        customer = serializers.SerializerMethodField()

        class Meta(CreditEntrySerializer.Meta):
            fields = CreditEntrySerializer.Meta.fields + ["customer"]

        def get_customer(self, obj) -> dict:
            return {"id": obj.user_id, "name": obj.user.full_name, "email": obj.user.email}

    serializer_class = Row

    def get_queryset(self):
        qs = CreditEntry.objects.select_related("user", "order")
        params = self.request.query_params
        if user := params.get("user"):
            qs = qs.filter(user_id=user) if user.isdigit() else qs.none()
        if kind := params.get("kind"):
            qs = qs.filter(kind=kind)
        if state := params.get("status"):
            qs = qs.filter(status=state)
        if term := (params.get("q") or "").strip():
            qs = qs.filter(
                Q(user__email__icontains=term)
                | Q(user__full_name__icontains=term)
                | Q(order__order_number__iexact=term)
                | Q(reference__icontains=term)
            )
        return qs.annotate(used_total=Sum("used_by__amount")).order_by("-created_at", "-id")


class AdminCustomerWalletView(APIView):
    """GET /api/admin/loyalty/customers/{id}/ — a customer's wallet as they see it."""

    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, user_id: int):
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None:
            raise NotFoundError("Customer not found.")
        data = wallet_summary(user)
        data["customer"] = {"id": user.pk, "name": user.full_name, "email": user.email}
        return Response(data)


class AdminReferralView(APIView):
    """GET /api/admin/loyalty/referrals/ — who referred whom and what happened."""

    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        rows = Referral.objects.select_related("referrer", "referee", "rewarded_order").order_by("-created_at")[:200]
        return Response(
            [
                {
                    "id": r.pk,
                    "referrer": {"id": r.referrer_id, "name": r.referrer.full_name, "email": r.referrer.email},
                    "referee": {"id": r.referee_id, "name": r.referee.full_name, "email": r.referee.email},
                    "status": r.status,
                    "status_label": r.get_status_display(),
                    "order_number": r.rewarded_order.order_number if r.rewarded_order else None,
                    "created_at": r.created_at,
                }
                for r in rows
            ]
        )
