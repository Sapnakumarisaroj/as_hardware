from django.contrib import admin

from apps.delivery.models import DeliveryZone

from .models import Store, Warehouse


class DeliveryZoneInline(admin.StackedInline):
    model = DeliveryZone
    fields = (
        ("name", "is_active"),
        ("radius_km", "postal_codes"),
        ("delivery_fee_override", "free_delivery_min_order"),
        ("fast_delivery_enabled", "fast_delivery_max_minutes"),
        ("cod_enabled",),
    )
    extra = 0


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "kind",
        "city",
        "postal_code",
        "avg_prep_minutes",
        "own_riders",
        "has_location",
        "is_active",
        "accepts_orders",
        "cod_enabled",
    )
    list_filter = ("kind", "is_active", "accepts_orders", "cod_enabled", "city")
    list_editable = ("accepts_orders", "avg_prep_minutes", "own_riders")
    search_fields = ("name", "code", "city", "postal_code")
    exclude = ("is_deleted", "deleted_at")
    inlines = [DeliveryZoneInline]

    @admin.display(boolean=True, description="Map location")
    def has_location(self, obj) -> bool:
        return obj.latitude is not None and obj.longitude is not None


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    """Warehouses hold stock but never ship to customers, so they have no delivery settings."""

    list_display = ("name", "code", "city", "is_active")
    search_fields = ("name", "code", "city")
    exclude = (
        "kind",
        "is_deleted",
        "deleted_at",
        "accepts_orders",
        "avg_prep_minutes",
        "prep_minutes_per_item",
        "own_riders",
    )
