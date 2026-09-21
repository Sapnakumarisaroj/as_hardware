"""Multi-channel notification log. Delivery is performed by provider adapters (Phase 20);
in development they are mock/console providers that record — never fake — the send."""

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Channel(models.TextChoices):
    IN_APP = "in_app", "In-app"
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"
    WHATSAPP = "whatsapp", "WhatsApp"
    PUSH = "push", "Push"


class Notification(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped (opt-out / not configured)"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.IN_APP)
    event = models.CharField(max_length=60, help_text="e.g. order.confirmed, payment.captured")
    title = models.CharField(max_length=150)
    body = models.TextField(max_length=2000)
    data = models.JSONField(default=dict, blank=True, help_text="e.g. {'order_number': 'OD...'} for deep links.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    provider = models.CharField(max_length=30, blank=True)
    provider_message_id = models.CharField(max_length=120, blank=True)
    error = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "channel", "read_at"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.channel}:{self.event} → {self.user_id}"
