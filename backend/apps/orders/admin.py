from django.contrib import admin, messages

from apps.core.exceptions import ServiceError

from . import services
from .models import Order, OrderItem, OrderStatus, OrderStatusHistory
from .state_machine import TRANSITIONS


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    fields = ("sku", "product_name", "variant_name", "unit_price", "quantity", "line_total")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class StatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    fields = ("created_at", "from_status", "to_status", "changed_by", "note")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


def _transition_action(target: str):
    def action(modeladmin, request, queryset):
        done, failed = 0, 0
        for order in queryset:
            try:
                services.transition_order(order, target, actor=request.user, note="Changed in admin")
                done += 1
            except ServiceError as exc:
                failed += 1
                modeladmin.message_user(request, f"{order.order_number}: {exc.detail}", level=messages.WARNING)
        if done:
            modeladmin.message_user(request, f"{done} order(s) moved to {target}.")

    action.__name__ = f"mark_{target}"
    action.short_description = f"Move selected orders → {OrderStatus(target).label}"
    return action


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Orders are read-only except through validated status actions (no free-form status edits)."""

    list_display = (
        "order_number",
        "user",
        "status",
        "payment_method",
        "payment_status",
        "grand_total",
        "store",
        "created_at",
    )
    list_filter = ("status", "payment_status", "payment_method", "store")
    search_fields = ("order_number", "user__email", "user__phone")
    date_hierarchy = "created_at"
    list_select_related = ("user", "store")
    inlines = [OrderItemInline, StatusHistoryInline]
    actions = [_transition_action(s) for s in sorted({t for targets in TRANSITIONS.values() for t in targets})]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in Order._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
