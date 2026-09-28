from django.conf import settings
from django.contrib import admin

from .fulfillment import FeeRule
from .models import DeliveryAssignment, DeliveryPartner, DeliveryStatusHistory, DeliveryZone, GeocodeCache, PinCode


@admin.register(DeliveryPartner)
class DeliveryPartnerAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "phone",
        "vehicle_type",
        "home_store",
        "status",
        "max_active_assignments",
        "is_verified",
        "is_active",
    )
    list_filter = ("status", "is_verified", "is_active", "vehicle_type", "home_store")
    list_editable = ("max_active_assignments",)
    search_fields = ("user__email", "user__full_name", "phone", "vehicle_number")
    list_select_related = ("user", "home_store")
    raw_id_fields = ("user",)


class DeliveryStatusHistoryInline(admin.TabularInline):
    model = DeliveryStatusHistory
    fields = ("created_at", "from_status", "to_status", "note")
    readonly_fields = fields
    extra = 0
    can_delete = False


@admin.register(DeliveryAssignment)
class DeliveryAssignmentAdmin(admin.ModelAdmin):
    """Assignments are created through apps.delivery.assignment (staff API), which checks the
    order status, rider capacity and duplicates; the admin only shows them."""

    list_display = ("order", "shipment", "partner", "status", "assigned_at", "picked_up_at", "delivered_at")
    list_filter = ("status",)
    search_fields = ("order__order_number", "partner__user__email")
    list_select_related = ("order", "shipment", "partner__user")
    raw_id_fields = ("order", "shipment", "partner")
    readonly_fields = ("order", "shipment", "partner", "status", "otp_hash", "otp_verified_at")
    inlines = [DeliveryStatusHistoryInline]

    def has_add_permission(self, request):
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
