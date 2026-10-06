from django.contrib import admin

from .models import ChannelSetting, EventSetting, Notification, NotificationPreference, NotificationTemplate


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "channel", "event", "status", "provider", "recipient", "attempts", "read_at")
    list_filter = ("channel", "status", "event")
    search_fields = ("user__email", "title", "provider_message_id")
    list_select_related = ("user",)
    raw_id_fields = ("user",)
    readonly_fields = (
        "dedupe_key",
        "provider_message_id",
        "provider_status",
        "recipient",
        "attempts",
        "sent_at",
        "delivered_at",
    )


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ("event", "channel", "language", "provider_template", "updated_at")
    list_filter = ("channel", "language")
    search_fields = ("event", "body")


admin.site.register(ChannelSetting)
admin.site.register(EventSetting)
admin.site.register(NotificationPreference)
