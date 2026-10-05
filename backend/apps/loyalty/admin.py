from django.contrib import admin

from .models import CashbackRule, CreditAllocation, CreditEntry, LoyaltySettings, Referral, ReferralCode


@admin.register(LoyaltySettings)
class LoyaltySettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "credits_enabled", "max_order_share", "expiry_days", "referral_reward", "updated_at")
    readonly_fields = ("updated_at", "updated_by")

    def has_add_permission(self, request):
        return not LoyaltySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CashbackRule)
class CashbackRuleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "reward_type",
        "percent",
        "fixed_amount",
        "min_order_value",
        "first_order_only",
        "is_active",
    )
    list_filter = ("is_active", "reward_type", "first_order_only")
    filter_horizontal = ("categories",)
    autocomplete_fields = ("products",)


class AllocationInline(admin.TabularInline):
    model = CreditAllocation
    fk_name = "debit"
    fields = ("lot", "amount")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(CreditEntry)
class CreditEntryAdmin(admin.ModelAdmin):
    """The ledger is read only here: credits are added through the dashboard (promotional credit, with
    a reason and an audit entry) or by the system. Nothing is edited or deleted."""

    list_display = ("created_at", "user", "kind", "status", "amount", "expires_at", "order", "reference")
    list_filter = ("kind", "status")
    search_fields = ("user__email", "reference", "order__order_number")
    inlines = [AllocationInline]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ("referrer", "referee", "status", "rewarded_order", "created_at")
    list_filter = ("status",)
    readonly_fields = ("referrer", "referee", "status", "rewarded_order", "created_at")


@admin.register(ReferralCode)
class ReferralCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "user", "created_at")
    search_fields = ("code", "user__email")
    readonly_fields = ("code", "user", "created_at")
