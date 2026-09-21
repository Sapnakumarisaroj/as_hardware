from django.contrib import admin

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
    )
    list_filter = ("is_active", "discount_type")
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
    list_display = ("name", "discount_type", "value", "priority", "starts_at", "ends_at", "is_active")
    list_filter = ("is_active", "discount_type")
    search_fields = ("name",)
    filter_horizontal = ("products", "categories")
