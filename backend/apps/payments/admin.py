from django.contrib import admin

from .models import Payment, Refund


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


@admin.register(Refund)
class RefundAdmin(ReadOnlyAdmin):
    list_display = ("public_id", "payment", "amount", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("public_id", "payment__order__order_number", "provider_refund_id")
