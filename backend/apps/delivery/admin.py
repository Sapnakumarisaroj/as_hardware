from django import forms
from django.conf import settings
from django.contrib import admin, messages

from apps.core.exceptions import ServiceError
from apps.orders.models import OrderShipment

from . import workflow
from .assignment import assign_shipment, partners_with_load, reassign_shipment, unassign_shipment
from .cod import cash_by_partner
from .fulfillment import FeeRule
from .models import DeliveryAssignment, DeliveryPartner, DeliveryStatusHistory, DeliveryZone, GeocodeCache, PinCode
from .serializers import latest_delivery


@admin.register(DeliveryPartner)
class DeliveryPartnerAdmin(admin.ModelAdmin):
    """Rider availability at a glance: status, load against capacity and cash carried."""

    list_display = (
        "user",
        "phone",
        "vehicle_type",
        "home_store",
        "status",
        "load",
        "max_active_assignments",
        "cash_carried",
        "is_verified",
        "is_active",
        "last_location_at",
    )
    list_filter = ("status", "is_verified", "is_active", "vehicle_type", "home_store")
    list_editable = ("max_active_assignments",)
    search_fields = ("user__email", "user__full_name", "phone", "vehicle_number")
    raw_id_fields = ("user",)
    readonly_fields = ("current_latitude", "current_longitude", "last_location_at")

    def get_queryset(self, request):
        return partners_with_load(super().get_queryset(request))

    def changelist_view(self, request, extra_context=None):
        self._cash = cash_by_partner(DeliveryPartner.objects.values_list("pk", flat=True))
        return super().changelist_view(request, extra_context)

    @admin.display(description="Active jobs", ordering="active_count")
    def load(self, obj) -> int:
        return obj.active_count

    @admin.display(description="Cash to hand over")
    def cash_carried(self, obj) -> str:
        return f"₹{getattr(self, '_cash', {}).get(obj.pk, '0.00')}"


class DeliveryStatusHistoryInline(admin.TabularInline):
    model = DeliveryStatusHistory
    fields = ("created_at", "from_status", "to_status", "changed_by", "note", "latitude", "longitude")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.action(description="Cash received from the rider (hand over to the store)")
def mark_cash_handed_over(modeladmin, request, queryset):
    done = 0
    for job in queryset:
        try:
            workflow.hand_over_cash(job.pk, actor=request.user, note="Recorded in admin")
            done += 1
        except ServiceError as exc:
            modeladmin.message_user(request, f"{job.order.order_number}: {exc.detail}", level=messages.WARNING)
    if done:
        modeladmin.message_user(request, f"Cash of {done} delivery(ies) recorded as handed over.")


@admin.register(DeliveryAssignment)
class DeliveryAssignmentAdmin(admin.ModelAdmin):
    """Delivery history and cash-on-delivery collection. Read-only: jobs change only through
    apps.delivery.workflow (rider app, staff API, the Shipments page). The delivery code and
    the proof photo are never shown here; the photo is served by the staff API."""

    list_display = (
        "order",
        "kind",
        "partner",
        "status",
        "assigned_at",
        "delivered_at",
        "cod_amount_due",
        "cod_collected_amount",
        "cod_method",
        "cash_handed_over",
        "has_proof",
        "completed_without_otp",
        "earning_amount",
    )
    list_filter = ("status", "kind", "cod_method", "completed_without_otp", "shipment__store", "partner")
    search_fields = ("order__order_number", "partner__user__email", "partner__user__full_name")
    date_hierarchy = "assigned_at"
    list_select_related = ("order", "shipment", "partner__user")
    inlines = [DeliveryStatusHistoryInline]
    actions = [mark_cash_handed_over]
    HIDDEN = ("otp_hash", "otp_nonce", "proof_image")

    def get_fields(self, request, obj=None):
        return [f.name for f in DeliveryAssignment._meta.fields if f.name not in self.HIDDEN] + ["has_proof"]

    def get_readonly_fields(self, request, obj=None):
        return self.get_fields(request, obj)

    @admin.display(boolean=True, description="Cash handed over")
    def cash_handed_over(self, obj) -> bool | None:
        return None if obj.cod_collected_at is None else obj.cod_handed_over_at is not None

    @admin.display(boolean=True, description="Proof photo")
    def has_proof(self, obj) -> bool:
        return bool(obj.proof_image)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ShipmentActionForm(forms.ModelForm):
    """No shipment field is editable. The extra fields run the same services as the staff API."""

    assign_to = forms.ModelChoiceField(
        queryset=DeliveryPartner.objects.none(),
        required=False,
        label="Assign or reassign to",
        help_text="Waiting or failed shipment: assigns the rider. Shipment with a rider who has not picked "
        "up yet: gives it to this rider instead. The rider must be online, verified and below capacity.",
    )
    unassign = forms.BooleanField(required=False, label="Take it off the current rider (before pickup)")
    reason = forms.CharField(required=False, max_length=200, label="Reason (shown to the rider)")

    class Meta:
        model = OrderShipment
        fields: list[str] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assign_to"].queryset = DeliveryPartner.objects.filter(
            is_active=True, is_verified=True
        ).select_related("user")


@admin.register(OrderShipment)
class ShipmentAdmin(admin.ModelAdmin):
    """Shipment status, rider and delivery attempts; assign, reassign or unassign a rider."""

    form = ShipmentActionForm
    list_display = (
        "order",
        "sequence",
        "store",
        "status",
        "rider",
        "delivery_type",
        "delivery_attempts",
        "estimated_delivery_at",
        "delivered_at",
        "failure_reason",
    )
    list_filter = ("status", "store", "delivery_type")
    search_fields = ("order__order_number",)
    list_select_related = ("order", "store")
    SHOWN = (
        "order",
        "sequence",
        "store",
        "zone",
        "status",
        "stock_state",
        "rider",
        "delivery_type",
        "distance_km",
        "eta_minutes",
        "estimated_ready_at",
        "estimated_delivery_at",
        "delivery_attempts",
        "picked_up_at",
        "out_for_delivery_at",
        "delivered_at",
        "failed_at",
        "failure_reason",
        "failure_note",
    )
    fieldsets = ((None, {"fields": SHOWN}), ("Delivery partner", {"fields": ("assign_to", "unassign", "reason")}))
    readonly_fields = SHOWN

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("assignments__partner__user")

    @admin.display(description="Delivery partner")
    def rider(self, obj) -> str:
        job = latest_delivery(obj)
        return f"{job.partner.user.full_name} ({job.get_status_display()})" if job else "—"

    def save_model(self, request, obj, form, change):
        data = form.cleaned_data
        partner, reason = data.get("assign_to"), data.get("reason", "")
        try:
            if data.get("unassign"):
                unassign_shipment(obj, actor=request.user, reason=reason)
                self.message_user(request, "The shipment is waiting for a delivery partner again.")
            elif partner is not None:
                has_rider = obj.assignments.filter(
                    kind=DeliveryAssignment.Kind.DELIVERY, status__in=DeliveryAssignment.ACTIVE_STATUSES
                ).exists()
                if has_rider:
                    reassign_shipment(obj, partner, actor=request.user, reason=reason)
                else:
                    assign_shipment(obj, partner, actor=request.user)
                self.message_user(request, f"Assigned to {partner.user.full_name}.")
        except ServiceError as exc:
            self.message_user(request, str(exc.detail), level=messages.ERROR)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DeliveryZone)
class DeliveryZoneAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "store",
        "radius_km",
        "pin_count",
        "fee",
        "free_delivery_from",
        "fast_delivery_enabled",
        "fast_cutoff",
        "is_active",
    )
    list_filter = ("is_active", "fast_delivery_enabled", "store")
    list_editable = ("fast_delivery_enabled", "is_active")
    search_fields = ("name", "store__name", "postal_codes")
    list_select_related = ("store",)
    fieldsets = (
        (None, {"fields": ("store", "name", "is_active")}),
        (
            "Area served",
            {
                "fields": ("radius_km", "postal_codes", "polygon"),
                "description": "An address is served if its PIN code is listed, or it lies within the radius of "
                "the store (and inside the polygon, when one is set).",
            },
        ),
        ("Delivery fee", {"fields": ("delivery_fee_override", "free_delivery_min_order")}),
        (
            "Fast delivery",
            {
                "fields": ("fast_delivery_enabled", "fast_delivery_max_minutes"),
                "description": "Fast delivery is offered only when the calculated delivery time is within the cutoff.",
            },
        ),
    )

    @admin.display(description="PIN codes")
    def pin_count(self, obj) -> int:
        return len(obj.postal_code_set)

    @admin.display(description="Fee")
    def fee(self, obj) -> str:
        return f"₹{FeeRule.for_zone(obj).fee}"

    @admin.display(description="Free from")
    def free_delivery_from(self, obj) -> str:
        return f"₹{FeeRule.for_zone(obj).free_min}"

    @admin.display(description="Fast cutoff (min)")
    def fast_cutoff(self, obj) -> int:
        return obj.fast_delivery_max_minutes or settings.FAST_DELIVERY_MAX_MINUTES


@admin.register(PinCode)
class PinCodeAdmin(admin.ModelAdmin):
    list_display = ("postal_code", "area", "city", "state", "latitude", "longitude", "is_active")
    list_filter = ("is_active", "city", "state")
    list_editable = ("is_active",)
    search_fields = ("postal_code", "area", "city")


@admin.register(GeocodeCache)
class GeocodeCacheAdmin(admin.ModelAdmin):
    """Answers from the geocoding provider. Delete a row to have that query looked up again."""

    list_display = ("query", "latitude", "longitude", "source", "created_at")
    list_filter = ("source",)
    search_fields = ("query", "display_name")
    readonly_fields = ("query", "latitude", "longitude", "display_name", "source", "created_at")

    def has_add_permission(self, request):
        return False
