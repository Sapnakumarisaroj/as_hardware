"""Notifications (Phase 23): one row per message per channel, which is both the in-app inbox and the
delivery log. Settings an administrator can change (channels on/off, events per channel, the words)
and each person's own choices live next to it. See `services.py` for how a message is sent."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class Channel(models.TextChoices):
    IN_APP = "in_app", "In-app"
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"
    WHATSAPP = "whatsapp", "WhatsApp"
    PUSH = "push", "Push"


class Language(models.TextChoices):
    ENGLISH = "en", "English"
    HINDI = "hi", "Hindi"
    HINGLISH = "hi-latn", "Hinglish"


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
    # Same (user, channel, key) twice → the second is not created: one event never sends twice.
    dedupe_key = models.CharField(max_length=160, blank=True)
    language = models.CharField(max_length=10, choices=Language.choices, default=Language.ENGLISH)
    recipient = models.CharField(max_length=60, blank=True, help_text="Masked phone / email, for the log only.")
    template_name = models.CharField(max_length=80, blank=True, help_text="WhatsApp approved template used.")
    provider = models.CharField(max_length=30, blank=True)
    provider_message_id = models.CharField(max_length=120, blank=True, db_index=True)
    provider_status = models.CharField(max_length=20, blank=True, help_text="Latest delivery receipt.")
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "channel", "read_at"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["channel", "status", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "channel", "dedupe_key"],
                condition=~Q(dedupe_key=""),
                name="notification_once_per_key",
            )
        ]

    def __str__(self) -> str:
        return f"{self.channel}:{self.event} → {self.user_id}"


class NotificationPreference(TimeStampedModel):
    """A person's own choices. In-app messages are always kept (they are the account's history);
    WhatsApp is opt-in and stored on the profile (`CustomerProfile.whatsapp_opt_in`), where sign-up
    already asks for it."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_prefs")
    email = models.BooleanField(default=True)
    sms = models.BooleanField(default=False)
    muted_categories = models.JSONField(default=list, blank=True)

    def __str__(self) -> str:
        return f"Preferences<{self.user_id}>"


class ChannelSetting(models.Model):
    """Administrator switch for a whole channel. No row means the built-in default."""

    channel = models.CharField(max_length=10, choices=Channel.choices, unique=True)
    enabled = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.channel}: {'on' if self.enabled else 'off'}"


class EventSetting(models.Model):
    """Whether one event goes out on one channel. No row means the event's default (events.py)."""

    event = models.CharField(max_length=60)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    enabled = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "channel"], name="event_setting_once")]

    def __str__(self) -> str:
        return f"{self.event}/{self.channel}: {'on' if self.enabled else 'off'}"


class NotificationTemplate(TimeStampedModel):
    """The shop's own words for an event on a channel and language, replacing the built-in default.
    `provider_template` is the name of the matching template approved in WhatsApp Business."""

    event = models.CharField(max_length=60)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    language = models.CharField(max_length=10, choices=Language.choices, default=Language.ENGLISH)
    title = models.CharField(max_length=150, blank=True)
    body = models.TextField(max_length=2000)
    provider_template = models.CharField(max_length=80, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["event", "channel", "language"]
        constraints = [
            models.UniqueConstraint(fields=["event", "channel", "language"], name="notification_template_once")
        ]

    def __str__(self) -> str:
        return f"{self.event}/{self.channel}/{self.language}"
