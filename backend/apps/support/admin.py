from django.contrib import admin

from .models import SupportConversation, SupportMessage


class SupportMessageInline(admin.TabularInline):
    model = SupportMessage
    fields = ("created_at", "sender_type", "sender", "body")
    readonly_fields = ("created_at",)
    raw_id_fields = ("sender",)
    extra = 1


@admin.register(SupportConversation)
class SupportConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "user", "contact_phone", "channel", "status", "assigned_to", "last_message_at")
    list_filter = ("status", "channel")
    search_fields = ("subject", "user__email", "contact_phone", "order__order_number")
    raw_id_fields = ("user", "order", "assigned_to")
    inlines = [SupportMessageInline]
