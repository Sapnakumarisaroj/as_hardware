from django.contrib import admin

from .models import Quote, QuoteItem


class QuoteItemInline(admin.TabularInline):
    model = QuoteItem
    extra = 0
    raw_id_fields = ("variant",)


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ("number", "user", "status", "valid_until", "created_at")
    list_filter = ("status",)
    search_fields = ("number", "user__email", "business_name", "gstin")
    raw_id_fields = ("user", "address", "quoted_by", "order")
    inlines = [QuoteItemInline]
