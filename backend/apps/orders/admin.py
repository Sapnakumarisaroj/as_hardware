from django.contrib import admin, messages

from apps.core.exceptions import ServiceError

from . import returns, services
from .models import Order, OrderItem, OrderShipment, OrderStatus, OrderStatusHistory, ReturnItem, ReturnRequest
from .state_machine import RETURN_WORKFLOW_STATUSES, TRANSITIONS


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    fields = ("sku", "product_name", "variant_name", "unit_price", "quantity", "line_total")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class ShipmentInline(admin.TabularInline):
    model = OrderShipment
    fields = (
        "sequence",
        "store",
        "zone",
        "delivery_type",
        "distance_km",
        "prep_minutes",
        "wait_minutes",
        "travel_minutes",
        "eta_minutes",
        "estimated_delivery_at",
        "eta_source",
    )
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
        "delivery_type",
        "estimated_delivery_at",
        "created_at",
    )
    list_filter = ("status", "payment_status", "payment_method", "delivery_type", "store")
    search_fields = ("order_number", "user__email", "user__phone")
    date_hierarchy = "created_at"
    list_select_related = ("user", "store")
    inlines = [OrderItemInline, ShipmentInline, StatusHistoryInline]
    # Return statuses move only through the return request (see ReturnRequestAdmin).
    actions = [
        _transition_action(s)
        for s in sorted({t for targets in TRANSITIONS.values() for t in targets} - RETURN_WORKFLOW_STATUSES)
    ]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in Order._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReturnItemInline(admin.TabularInline):
    model = ReturnItem
    fields = ("order_item", "quantity", "refund_amount")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


def _return_action(name: str, label: str, run):
    def action(modeladmin, request, queryset):
        done = 0
        for ret in queryset:
            try:
                run(ret, request.user)
                done += 1
            except ServiceError as exc:
                modeladmin.message_user(request, f"{ret.return_number}: {exc.detail}", level=messages.WARNING)
        if done:
            modeladmin.message_user(request, f"{done} return(s) updated.")

    action.__name__ = name
    action.short_description = label
    return action


@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):
    """Read-only; decisions go through the returns service (stock, refund, order status, audit)."""

    list_display = (
        "return_number",
        "order",
        "user",
        "status",
        "reason",
        "refund_amount",
        "refund_method",
        "created_at",
    )
    list_filter = ("status", "reason", "refund_method", "order__store")
    search_fields = ("return_number", "order__order_number", "user__email")
    date_hierarchy = "created_at"
    list_select_related = ("order", "user")
    inlines = [ReturnItemInline]
    actions = [
        _return_action("approve", "Approve selected returns", lambda r, u: returns.approve_return(r, actor=u)),
        _return_action(
            "receive_restock",
            "Mark received — restock items and start refund",
            lambda r, u: returns.receive_return(r, actor=u, restock=True),
        ),
        _return_action(
            "receive_no_restock",
            "Mark received — damaged, do NOT restock (refund still starts)",
            lambda r, u: returns.receive_return(r, actor=u, restock=False),
        ),
        _return_action(
            "reject",
            "Reject selected returns (use the API to give a specific reason)",
            lambda r, u: returns.reject_return(r, actor=u, note="Rejected after review by the store."),
        ),
    ]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in ReturnRequest._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
