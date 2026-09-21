from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "channel", "event", "status", "provider", "read_at")
    list_filter = ("channel", "status", "event")
    search_fields = ("user__email", "title", "provider_message_id")
    list_select_related = ("user",)
    raw_id_fields = ("user",)
