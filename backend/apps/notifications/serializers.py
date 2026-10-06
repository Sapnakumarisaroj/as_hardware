from rest_framework import serializers

from . import services, templating
from .events import CATEGORIES, EVENTS, IN_APP, WHATSAPP
from .models import Channel, Language, Notification, NotificationTemplate

# Channels a message can be written for (push is reserved for a later phase).
MESSAGE_CHANNELS = [value for value in Channel.values if value != Channel.PUSH]


class NotificationSerializer(serializers.ModelSerializer):
    """The person's own in-app notification. Internal fields (template variables, provider ids) stay out."""

    category = serializers.SerializerMethodField()
    link = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "event", "category", "title", "body", "link", "is_read", "read_at", "created_at"]

    def get_category(self, obj) -> str:
        spec = EVENTS.get(obj.event)
        return spec.category if spec else "orders"

    def get_link(self, obj) -> str:
        spec = EVENTS.get(obj.event)
        return services.link_for(spec, obj.data) if spec else ""

    def get_is_read(self, obj) -> bool:
        return obj.read_at is not None


class MarkReadSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, max_length=500)


class PreferencesSerializer(serializers.Serializer):
    email = serializers.BooleanField(required=False)
    sms = serializers.BooleanField(required=False)
    whatsapp = serializers.BooleanField(required=False)
    muted_categories = serializers.ListField(
        child=serializers.ChoiceField(choices=list(CATEGORIES)), required=False, max_length=len(CATEGORIES)
    )


class AdminNotificationSerializer(serializers.ModelSerializer):
    """Delivery log row. Phone numbers are masked when written; delivery codes are never stored."""

    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    can_retry = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "created_at",
            "user",
            "user_email",
            "user_name",
            "channel",
            "event",
            "language",
            "title",
            "body",
            "status",
            "provider",
            "provider_status",
            "template_name",
            "recipient",
            "attempts",
            "error",
            "sent_at",
            "delivered_at",
            "read_at",
            "can_retry",
        ]

    def get_can_retry(self, obj) -> bool:
        return obj.channel != IN_APP and obj.status in (Notification.Status.FAILED, Notification.Status.SKIPPED)


class TemplateSerializer(serializers.ModelSerializer):
    event = serializers.ChoiceField(choices=sorted(EVENTS))
    channel = serializers.ChoiceField(choices=MESSAGE_CHANNELS)
    language = serializers.ChoiceField(choices=Language.choices, default=Language.ENGLISH)
    provider_template = serializers.RegexField(
        r"^[a-z0-9_]*$",
        max_length=80,
        required=False,
        allow_blank=True,
        error_messages={"invalid": "Use lowercase letters, digits and _ (as in WhatsApp Manager)."},
    )

    class Meta:
        model = NotificationTemplate
        fields = ["id", "event", "channel", "language", "title", "body", "provider_template", "updated_at"]
        read_only_fields = ["updated_at"]

    def validate(self, attrs):
        event = attrs.get("event", getattr(self.instance, "event", None))
        channel = attrs.get("channel", getattr(self.instance, "channel", None))
        spec = EVENTS[event]
        if channel not in spec.allowed:
            raise serializers.ValidationError({"channel": f"“{spec.label}” can't be sent by {channel}."})
        errors = template_problems(
            spec,
            channel,
            attrs.get("title", getattr(self.instance, "title", "")),
            attrs.get("body", getattr(self.instance, "body", "")),
        )
        if errors:
            raise serializers.ValidationError(errors)
        if channel != WHATSAPP:
            attrs["provider_template"] = ""
        return attrs


def template_problems(spec, channel: str, title: str, body: str) -> dict:
    allowed = spec.all_variables
    errors = {}
    limit = templating.LIMITS.get(channel, templating.LIMITS["body"])
    if not (body or "").strip():
        errors["body"] = ["Write the message."]
    else:
        body_problems = templating.validate(body, allowed, limit=limit)
        if body_problems:
            errors["body"] = body_problems
    title_problems = templating.validate(title or "", allowed, limit=templating.LIMITS["title"])
    if title_problems:
        errors["title"] = title_problems
    return errors


class PreviewSerializer(serializers.Serializer):
    event = serializers.ChoiceField(choices=sorted(EVENTS))
    channel = serializers.ChoiceField(choices=MESSAGE_CHANNELS)
    title = serializers.CharField(required=False, allow_blank=True, max_length=300)
    body = serializers.CharField(max_length=4000)


class SwitchSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
