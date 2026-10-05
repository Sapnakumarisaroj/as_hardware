from django.contrib import admin, messages

from apps.core.exceptions import ServiceError
from integrations.payments import GatewayError

from . import refunds
from .models import Payment, PaymentSettings, Refund, WebhookEvent


class ReadOnlyAdmin(admin.ModelAdmin):
    """Money records are changed only by payment services, never by hand."""

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ("public_id", "order", "provider", "method", "amount", "status", "created_at")
    list_filter = ("provider", "status", "method")
    search_fields = ("public_id", "order__order_number", "provider_order_id", "provider_payment_id")
    list_select_related = ("order",)


def _refund_action(name: str, label: str, run):
    def action(modeladmin, request, queryset):
        for refund in queryset.select_related("payment"):
            try:
                outcome = run(refund, request.user)
                modeladmin.message_user(request, f"{refund.public_id}: {outcome}")
            except (ServiceError, GatewayError) as exc:
                modeladmin.message_user(request, f"{refund.public_id}: {exc}", level=messages.WARNING)

    action.__name__ = name
    action.short_description = label
    return action


@admin.register(Refund)
class RefundAdmin(ReadOnlyAdmin):
    """Manual (COD) refunds are recorded through the API (`mark-processed`) with the payment reference."""

    list_display = ("public_id", "payment", "amount", "status", "attempts", "provider_refund_id", "created_at")
    list_filter = ("status", "payment__provider")
    search_fields = ("public_id", "payment__order__order_number", "provider_refund_id", "manual_reference")
    list_select_related = ("payment",)
    actions = [
        _refund_action(
            "submit", "Submit pending refunds to the gateway now", lambda r, u: refunds.process_refund(r.pk)
        ),
        _refund_action("sync", "Check refund status with the gateway", lambda r, u: refunds.sync_refund(r.pk)),
        _refund_action("retry", "Retry failed gateway refunds", lambda r, u: refunds.retry_refund(r, actor=u).status),
    ]


@admin.register(WebhookEvent)
class WebhookEventAdmin(ReadOnlyAdmin):
    list_display = ("event_id", "provider", "event_type", "status", "deliveries", "created_at", "processed_at")
    list_filter = ("provider", "status", "event_type")
    search_fields = ("event_id", "note")


@admin.register(PaymentSettings)
class PaymentSettingsAdmin(admin.ModelAdmin):
    """One row: cash on delivery on/off and the largest order payable in cash."""

    list_display = ("__str__", "cod_enabled", "cod_max_order_value", "updated_at")
    readonly_fields = ("updated_at", "updated_by")

    def has_add_permission(self, request):
        return not PaymentSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
