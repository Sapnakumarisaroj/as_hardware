from django.contrib import admin
from django.utils import timezone

from .models import Coupon, CouponRedemption, Offer


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "discount_type",
        "value",
        "min_order_value",
        "used_count",
        "usage_limit",
        "starts_at",
        "ends_at",
        "is_active",
        "show_in_checkout",
    )
    list_filter = ("is_active", "show_in_checkout", "discount_type")
    list_editable = ("show_in_checkout",)
    search_fields = ("code", "description")
    filter_horizontal = ("products", "categories")
    readonly_fields = ("used_count",)


@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    list_display = ("coupon", "user", "order", "discount_amount", "created_at")
    search_fields = ("coupon__code", "user__email", "order__order_number")
    list_select_related = ("coupon", "user", "order")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    """Automatic offers. Targets empty = whole cart; lower priority number wins where offers overlap."""

    list_display = (
        "name",
        "discount_type",
        "value",
        "max_discount_amount",
        "min_order_value",
        "priority",
        "starts_at",
        "ends_at",
        "is_active",
        "is_live",
    )
    list_filter = ("is_active", "discount_type")
    list_editable = ("priority", "is_active")
    search_fields = ("name", "description")
    filter_horizontal = ("products", "categories")
    fieldsets = (
        (None, {"fields": ("name", "description", "is_active", "priority")}),
        ("Discount", {"fields": ("discount_type", "value", "max_discount_amount", "min_order_value")}),
        ("Schedule", {"fields": ("starts_at", "ends_at")}),
        (
            "Applies to",
            {
                "fields": ("products", "categories"),
                "description": "Leave both empty to apply to the whole cart. A category includes its subcategories.",
            },
        ),
    )

    @admin.display(boolean=True, description="Live now")
    def is_live(self, obj):
        now = timezone.now()
        return obj.is_active and obj.starts_at <= now and (obj.ends_at is None or obj.ends_at > now)
