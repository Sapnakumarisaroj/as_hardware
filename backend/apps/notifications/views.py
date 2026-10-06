"""Notification API (Phase 23).

Everyone signed in (customers, staff, delivery partners; own notifications only):
- `GET  /api/notifications/?unread=1&category=`     in-app inbox, newest first
- `GET  /api/notifications/summary/`                unread count (the header bell)
- `POST /api/notifications/{id}/read/` · `{id}/unread/` · `POST /api/notifications/read-all/` (optional `ids`)
- `GET|PATCH /api/notifications/preferences/`       email / WhatsApp / SMS and muted categories

Administrators (every change audited):
- `GET  /api/admin/notifications/events/`                          events × channels, variables, words in use
- `PATCH /api/admin/notifications/events/{key}/{channel}/`         turn an event on/off for a channel
- `/api/admin/notifications/templates/`                            the shop's own words (validated)
- `POST /api/admin/notifications/preview/`                         render words with example values
- `GET  /api/admin/notifications/channels/` · `PATCH …/{channel}/` channel switches and provider status
- `GET  /api/admin/notifications/log/?status=&channel=&event=&q=`  delivery log; `{id}/retry/`, `retry-failed/`

WhatsApp Cloud API delivery receipts: `GET|POST /api/notifications/webhooks/whatsapp/` (signed, no login).
"""

import logging

from django.conf import settings
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.core.permissions import IsAdminRole
from integrations.messaging import get_sms_provider, get_whatsapp_provider, mask_phone

from . import services, templating, webhooks
from .events import ALL_CHANNELS, CATEGORIES, EMAIL, EVENTS, IN_APP, SMS, WHATSAPP
from .models import ChannelSetting, EventSetting, Notification, NotificationTemplate
from .serializers import (
    AdminNotificationSerializer,
    MarkReadSerializer,
    NotificationSerializer,
    PreferencesSerializer,
    PreviewSerializer,
    SwitchSerializer,
    TemplateSerializer,
    template_problems,
)

logger = logging.getLogger(__name__)


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        rows = services.inbox(self.request.user)
        if self.request.query_params.get("unread") in ("1", "true"):
            rows = rows.filter(read_at__isnull=True)
        category = self.request.query_params.get("category")
        if category in CATEGORIES:
            rows = rows.filter(event__in=[e.key for e in EVENTS.values() if e.category == category])
        return rows

    @extend_schema(
        parameters=[
            OpenApiParameter("unread", OpenApiTypes.BOOL),
            OpenApiParameter("category", OpenApiTypes.STR, enum=list(CATEGORIES)),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def summary(self, request):
        return Response({"unread": services.unread_count(request.user)})

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        self._own(pk)
        services.mark_read(request.user, [int(pk)])
        return Response({"unread": services.unread_count(request.user)})

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def unread(self, request, pk=None):
        self._own(pk)
        services.mark_unread(request.user, int(pk))
        return Response({"unread": services.unread_count(request.user)})

    @extend_schema(request=MarkReadSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changed = services.mark_read(request.user, serializer.validated_data.get("ids"))
        return Response({"marked": changed, "unread": services.unread_count(request.user)})

    def _own(self, pk) -> Notification:
        try:
            return services.inbox(self.request.user).get(pk=int(pk))
        except (Notification.DoesNotExist, ValueError, TypeError):
            raise NotFound("Notification not found.") from None


def _preferences_payload(user) -> dict:
    prefs = services.preferences(user)
    profile = getattr(user, "profile", None)
    whatsapp_ready = services.channel_enabled(WHATSAPP) and get_whatsapp_provider().configured
    sms_ready = services.channel_enabled(SMS) and get_sms_provider().configured
    return {
        "email": prefs.email,
        "sms": prefs.sms,
        "whatsapp": bool(profile and profile.whatsapp_opt_in),
        "muted_categories": prefs.muted_categories or [],
        "has_email": bool(user.email),
        "phone": mask_phone(user.phone) if user.phone else "",
        "channels": {
            IN_APP: {"available": True, "always_on": True},
            EMAIL: {"available": services.channel_enabled(EMAIL) and bool(user.email)},
            WHATSAPP: {"available": whatsapp_ready, "needs_phone": not user.phone},
            SMS: {"available": sms_ready, "needs_phone": not user.phone},
        },
        "categories": [{"key": key, "label": label} for key, label in CATEGORIES.items()],
    }


class PreferencesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(_preferences_payload(request.user))

    @extend_schema(request=PreferencesSerializer, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request):
        serializer = PreferencesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        user = request.user
        if values.get("whatsapp") and not user.phone:
            raise ValidationError({"whatsapp": ["Add a mobile number to your account first."]})
        if values.get("sms") and not user.phone:
            raise ValidationError({"sms": ["Add a mobile number to your account first."]})
        prefs = services.preferences(user)
        for name in ("email", "sms"):
            if name in values:
                setattr(prefs, name, values[name])
        if "muted_categories" in values:
            prefs.muted_categories = sorted(set(values["muted_categories"]))
        prefs.save()
        if "whatsapp" in values:
            from apps.accounts.models import CustomerProfile

            profile, _ = CustomerProfile.objects.get_or_create(user=user)
            profile.whatsapp_opt_in = values["whatsapp"]
            profile.save(update_fields=["whatsapp_opt_in", "updated_at"])
            user.profile = profile
        return Response(_preferences_payload(user))


# --- Administration --------------------------------------------------------------------------------


class AdminEventsView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response({"results": services.event_catalogue(), "languages": ["en", "hi", "hi-latn"]})


class AdminEventChannelView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(request=SwitchSerializer, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request, key, channel):
        spec = EVENTS.get(key)
        if spec is None or channel not in spec.allowed:
            raise NotFound("No such event or channel.")
        serializer = SwitchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enabled = serializer.validated_data["enabled"]
        before = services.event_channels(spec)[channel]
        row, _ = EventSetting.objects.update_or_create(
            event=key, channel=channel, defaults={"enabled": enabled, "updated_by": request.user}
        )
        record_audit(
            action="notifications.event_channel",
            actor=request.user,
            target=row,
            changes={"event": key, "channel": channel, "before": before, "after": enabled},
            request=request,
        )
        return Response({"event": key, "channel": channel, "enabled": enabled})


class AdminTemplateViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminRole]
    serializer_class = TemplateSerializer
    pagination_class = None
    queryset = NotificationTemplate.objects.all()

    def perform_create(self, serializer):
        data = serializer.validated_data
        if NotificationTemplate.objects.filter(
            event=data["event"], channel=data["channel"], language=data["language"]
        ).exists():
            raise ValidationError(
                {"language": ["There are already words for this event, channel and language. Edit them instead."]}
            )
        row = serializer.save(updated_by=self.request.user)
        record_audit(
            action="notifications.template_create",
            actor=self.request.user,
            target=row,
            changes={"after": _template_state(row)},
            request=self.request,
        )

    def perform_update(self, serializer):
        before = _template_state(serializer.instance)
        clash = NotificationTemplate.objects.filter(
            event=serializer.validated_data.get("event", serializer.instance.event),
            channel=serializer.validated_data.get("channel", serializer.instance.channel),
            language=serializer.validated_data.get("language", serializer.instance.language),
        ).exclude(pk=serializer.instance.pk)
        if clash.exists():
            raise ValidationError({"language": ["There are already words for this event, channel and language."]})
        row = serializer.save(updated_by=self.request.user)
        record_audit(
            action="notifications.template_update",
            actor=self.request.user,
            target=row,
            changes={"before": before, "after": _template_state(row)},
            request=self.request,
        )

    def perform_destroy(self, instance):
        record_audit(
            action="notifications.template_delete",
            actor=self.request.user,
            target=instance,
            changes={"before": _template_state(instance)},
            request=self.request,
        )
        instance.delete()


def _template_state(row: NotificationTemplate) -> dict:
    return {k: getattr(row, k) for k in ("event", "channel", "language", "title", "body", "provider_template")}


class AdminPreviewView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(request=PreviewSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = PreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        spec = EVENTS[data["event"]]
        problems = template_problems(spec, data["channel"], data.get("title", ""), data["body"])
        values = {
            "customer_name": "Asha",
            "shop_name": settings.APP_NAME,
            "link": settings.FRONTEND_URL + "/account/orders/OD2610060001",
            **services.sample_context(spec),
        }
        if problems:
            return Response({"ok": False, "problems": problems, "title": "", "body": ""})
        title = templating.render(data.get("title") or spec.default_text(data["channel"])[0], values)
        return Response(
            {
                "ok": True,
                "problems": {},
                "title": title,
                "body": templating.render(data["body"], values),
                "parameters": [values.get(n, "") for n in templating.variables_in(data["body"])],
            }
        )


class AdminChannelsView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response({"results": services.provider_overview()})


class AdminChannelSwitchView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(request=SwitchSerializer, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request, channel):
        if channel not in ALL_CHANNELS:
            raise NotFound("No such channel.")
        serializer = SwitchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enabled = serializer.validated_data["enabled"]
        if channel == IN_APP and not enabled:
            raise ValidationError(
                {"enabled": ["In-app notifications are the account history and can't be turned off."]}
            )
        before = services.channel_enabled(channel)
        row, _ = ChannelSetting.objects.update_or_create(
            channel=channel, defaults={"enabled": enabled, "updated_by": request.user}
        )
        record_audit(
            action="notifications.channel",
            actor=request.user,
            target=row,
            changes={"channel": channel, "before": before, "after": enabled},
            request=request,
        )
        return Response({"channel": channel, "enabled": enabled})


class AdminLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminRole]
    serializer_class = AdminNotificationSerializer

    def get_queryset(self):
        rows = Notification.objects.select_related("user").order_by("-created_at", "-id")
        params = self.request.query_params
        if params.get("status") in Notification.Status.values:
            rows = rows.filter(status=params["status"])
        if params.get("channel") in ALL_CHANNELS:
            rows = rows.filter(channel=params["channel"])
        if params.get("event") in EVENTS:
            rows = rows.filter(event=params["event"])
        q = (params.get("q") or "").strip()
        if q:
            rows = rows.filter(Q(user__email__icontains=q) | Q(data__order_number=q) | Q(title__icontains=q))
        return rows

    @extend_schema(
        parameters=[
            OpenApiParameter("status", OpenApiTypes.STR, enum=list(Notification.Status.values)),
            OpenApiParameter("channel", OpenApiTypes.STR, enum=list(ALL_CHANNELS)),
            OpenApiParameter("event", OpenApiTypes.STR),
            OpenApiParameter("q", OpenApiTypes.STR, description="Customer email, order number or title"),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses={200: AdminNotificationSerializer})
    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        note = self.get_object()
        if not services.retry(note):
            raise ValidationError(
                {"detail": "Only failed or skipped email, WhatsApp and SMS messages can be sent again."}
            )
        record_audit(
            action="notifications.retry",
            actor=request.user,
            target=note,
            changes={"channel": note.channel},
            request=request,
        )
        note.refresh_from_db()
        return Response(AdminNotificationSerializer(note).data)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="retry-failed")
    def retry_failed(self, request):
        rows = Notification.objects.filter(status=Notification.Status.FAILED).exclude(channel=IN_APP)
        channel = request.data.get("channel") if isinstance(request.data, dict) else None
        if channel in ALL_CHANNELS:
            rows = rows.filter(channel=channel)
        count = sum(services.retry(note) for note in rows.order_by("-created_at")[:200])
        record_audit(
            action="notifications.retry_failed",
            actor=request.user,
            changes={"count": count, "channel": channel or "all"},
            request=request,
        )
        return Response({"retried": count})


class WhatsAppWebhookView(APIView):
    """Meta → server: delivery receipts and customer messages. The HMAC signature over the raw body
    (WHATSAPP_APP_SECRET) is the authentication; GET answers Meta's one-time verification."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(request=None, responses={200: OpenApiTypes.STR, 403: None})
    def get(self, request):
        challenge = webhooks.verify_subscription(request.query_params)
        if challenge is None:
            return Response({"detail": "Verification failed."}, status=status.HTTP_403_FORBIDDEN)
        from django.http import HttpResponse

        return HttpResponse(challenge, content_type="text/plain")

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT, 403: None})
    def post(self, request):
        body = request.body
        if not webhooks.signature_ok(body, request.headers.get("X-Hub-Signature-256", "")):
            return Response({"detail": "Bad signature."}, status=status.HTTP_403_FORBIDDEN)
        try:
            result = webhooks.process(body)
        except ValueError:
            return Response({"detail": "Not JSON."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)
