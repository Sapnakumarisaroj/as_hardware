from django import forms
from django.contrib import admin, messages
from django.db.models import F

from apps.core.exceptions import ServiceError

from . import services
from .models import Inventory, StockMovement


class InventoryForm(forms.ModelForm):
    """Quantities are read-only; stock changes are booked as movements so the ledger stays complete."""

    movement_type = forms.ChoiceField(
        required=False,
        choices=[("", "— no stock change —")]
        + [
            (t.value, t.label)
            for t in (StockMovement.Type.PURCHASE, StockMovement.Type.ADJUSTMENT, StockMovement.Type.RETURN)
        ],
    )
    movement_quantity = forms.IntegerField(required=False, help_text="Adjustments may be negative.")
    movement_reason = forms.CharField(required=False, max_length=255)

    class Meta:
        model = Inventory
        fields = ["store", "variant", "low_stock_threshold", "is_active"]


class LowStockFilter(admin.SimpleListFilter):
    title = "stock level"
    parameter_name = "stock"

    def lookups(self, request, model_admin):
        return [("low", "Low stock"), ("out", "Out of stock")]

    def queryset(self, request, queryset):
        if self.value() == "low":
            return queryset.filter(available_quantity__lte=F("low_stock_threshold"))
        if self.value() == "out":
            return queryset.filter(available_quantity=0)
        return queryset


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    form = InventoryForm
    list_display = ("variant", "store", "available_quantity", "reserved_quantity", "low_stock_threshold", "is_active")
    list_filter = (LowStockFilter, "store", "is_active")
    search_fields = ("variant__sku", "variant__product__name", "store__code")
    readonly_fields = ("available_quantity", "reserved_quantity")
    autocomplete_fields = ("variant",)
    list_select_related = ("variant__product", "store")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        movement_type = form.cleaned_data.get("movement_type")
        quantity = form.cleaned_data.get("movement_quantity")
        if movement_type and quantity:
            try:
                services.apply_movement(
                    obj,
                    movement_type,
                    quantity,
                    reason=form.cleaned_data.get("movement_reason", ""),
                    actor=request.user,
                )
            except ServiceError as exc:
                self.message_user(request, f"Stock not changed: {exc.detail}", level=messages.ERROR)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "inventory",
        "movement_type",
        "quantity",
        "available_after",
        "reserved_after",
        "reference_type",
        "reference_id",
        "created_by",
    )
    list_filter = ("movement_type", "inventory__store")
    search_fields = ("inventory__variant__sku", "reference_id", "reason")
    list_select_related = ("inventory__variant__product", "inventory__store", "created_by")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
