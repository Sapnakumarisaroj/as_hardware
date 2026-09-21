from django.contrib import admin

from .models import DeliveryAssignment, DeliveryPartner, DeliveryStatusHistory, DeliveryZone


@admin.register(DeliveryPartner)
class DeliveryPartnerAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "vehicle_type", "home_store", "status", "is_verified", "is_active")
    list_filter = ("status", "is_verified", "is_active", "vehicle_type", "home_store")
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
    list_display = ("order", "partner", "status", "assigned_at", "picked_up_at", "delivered_at")
    list_filter = ("status",)
    search_fields = ("order__order_number", "partner__user__email")
    list_select_related = ("order", "partner__user")
    raw_id_fields = ("order", "partner")
    readonly_fields = ("otp_hash", "otp_verified_at")
    inlines = [DeliveryStatusHistoryInline]


@admin.register(DeliveryZone)
class DeliveryZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "store", "radius_km", "fast_delivery_enabled", "is_active")
    list_filter = ("is_active", "fast_delivery_enabled", "store")
    search_fields = ("name", "store__name")
