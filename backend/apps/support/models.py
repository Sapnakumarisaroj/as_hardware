from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.notifications.models import Channel


class SupportConversation(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        WAITING_CUSTOMER = "waiting_customer", "Waiting for customer"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="support_conversations"
    )
    # For WhatsApp/SMS contacts who have no account yet.
    contact_phone = models.CharField(max_length=15, blank=True, db_index=True)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.IN_APP)
    subject = models.CharField(max_length=150, blank=True)
    order = models.ForeignKey(
        "orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="support_conversations"
    )
    # Product enquiries (from the product page or WhatsApp) point at what was asked about.
    product = models.ForeignKey(
        "catalog.Product", null=True, blank=True, on_delete=models.SET_NULL, related_name="enquiries"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_conversations",
    )
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        indexes = [models.Index(fields=["status", "channel"]), models.Index(fields=["user", "-created_at"])]

    def __str__(self) -> str:
        return f"#{self.pk} {self.subject or self.channel} ({self.status})"


class SupportMessage(models.Model):
    class Sender(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        AGENT = "agent", "Support agent"
        BOT = "bot", "Assistant bot"
        SYSTEM = "system", "System"

    conversation = models.ForeignKey(SupportConversation, on_delete=models.CASCADE, related_name="messages")
    sender_type = models.CharField(max_length=10, choices=Sender.choices)
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField(max_length=4000)
    attachments = models.JSONField(default=list, blank=True)
    channel_message_id = models.CharField(max_length=120, blank=True, help_text="e.g. WhatsApp message id (dedupe).")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["conversation", "created_at"]), models.Index(fields=["channel_message_id"])]

    def __str__(self) -> str:
        return f"{self.sender_type}: {self.body[:40]}"
