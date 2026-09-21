from django.contrib import admin

from apps.delivery.models import DeliveryZone

from .models import Store, Warehouse


class DeliveryZoneInline(admin.TabularInline):
    model = DeliveryZone
    fields = ("name", "radius_km", "fast_delivery_enabled", "delivery_fee_override", "is_active")
    extra = 0


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "kind", "city", "postal_code", "is_active", "accepts_orders")
    list_filter = ("kind", "is_active", "accepts_orders", "city")
    list_editable = ("accepts_orders",)
    search_fields = ("name", "code", "city", "postal_code")
    exclude = ("is_deleted", "deleted_at")
    inlines = [DeliveryZoneInline]


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "city", "is_active")
    search_fields = ("name", "code", "city")
    exclude = ("kind", "is_deleted", "deleted_at", "accepts_orders", "avg_prep_minutes")
