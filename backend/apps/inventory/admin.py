from django import forms
from django.contrib import admin, messages
from django.db.models import F

from apps.core.admin import AdminRoleRequiredMixin
from apps.core.exceptions import ServiceError

from . import services
from .models import Inventory, StockMovement


class InventoryForm(forms.ModelForm):
    """Quantities are read-only; stock changes are booked as movements so the ledger stays complete.
    The movement is checked here, before anything is saved, so a bad entry is shown on the form
    instead of half-saving the row."""

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

    def clean(self):
        data = super().clean()
        movement_type, quantity = data.get("movement_type"), data.get("movement_quantity")
        reason = (data.get("movement_reason") or "").strip()
        if not movement_type:
            if quantity:
                self.add_error("movement_type", "Choose what kind of stock change this is.")
            return data
        if not quantity:
            self.add_error("movement_quantity", "Enter how many units changed (not zero).")
        elif movement_type != StockMovement.Type.ADJUSTMENT and quantity < 0:
            self.add_error("movement_quantity", "Use a positive number; only adjustments may be negative.")
        elif self.instance.pk and self.instance.available_quantity + quantity < 0:
            self.add_error(
                "movement_quantity",
                f"Only {self.instance.available_quantity} unit(s) available; stock can't go below 0.",
            )
        elif not self.instance.pk and quantity < 0:
            self.add_error("movement_quantity", "A new stock row starts at 0; it can't be adjusted below that.")
        if movement_type == StockMovement.Type.ADJUSTMENT and not reason:
            self.add_error("movement_reason", "Give a reason for a manual adjustment (e.g. stock count).")
        return data


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
class InventoryAdmin(AdminRoleRequiredMixin, admin.ModelAdmin):
    """Stock per (store, product option). Saving the form never overwrites quantities: only the
    optional stock movement changes them, through `inventory.services`, with the reserved quantity
    for placed orders left untouched."""

    form = InventoryForm
    list_display = ("variant", "store", "available_quantity", "reserved_quantity", "low_stock_threshold", "is_active")
    list_filter = (LowStockFilter, "store", "is_active")
    search_fields = ("variant__sku", "variant__product__name", "variant__product__sku", "store__code")
    readonly_fields = ("available_quantity", "reserved_quantity")
    autocomplete_fields = ("variant",)
    list_select_related = ("variant__product", "store")
    list_per_page = 50

    def get_readonly_fields(self, request, obj=None):
        # Re-pointing a stock row at another store or option would move its quantities and ledger with it.
        return (*self.readonly_fields, "store", "variant") if obj else self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False  # stock rows carry the movement ledger and reservations; switch off instead

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
class StockMovementAdmin(AdminRoleRequiredMixin, admin.ModelAdmin):
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
    list_per_page = 100

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
