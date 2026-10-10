"""Raise, route and deliver notifications (Phase 23).

    notify(order.user, event="order.confirmed", context={"order_number": ..., "amount": ...},
           data={"order_number": ...})

1. Nothing happens until the surrounding transaction commits: a rolled-back order never says "confirmed".
   A failure while routing or sending is logged and never reaches the code that raised the event.
2. Routing: the event's channels (events.py) → the administrator's switches (channel on/off, event per
   channel) → the person's choices (email/SMS on, WhatsApp opt-in, muted categories). In-app is the
   account's history and is always kept.
3. One `Notification` row per channel, unique per (person, channel, key), so the same event never sends
   twice (a retried webhook, a double click, two cron runs).
4. In-app rows are delivered by being written. Email, WhatsApp and SMS are sent by the
   `notifications.deliver` background job (core.jobs): temporary failures are retried with backoff up
   to `MAX_ATTEMPTS`, permanent ones fail at once; administrators can retry failed rows.
"""

import hashlib
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.core.jobs import enqueue
from integrations.messaging import (
    MessagingError,
    MessagingUnavailable,
    OutgoingMessage,
    get_sms_provider,
    get_whatsapp_provider,
    mask_phone,
    to_e164,
)

from . import templating
from .events import ALL_CHANNELS, CATEGORIES, EMAIL, EVENTS, IN_APP, SMS, WHATSAPP, Event, get_event
from .models import ChannelSetting, EventSetting, Notification, NotificationPreference, NotificationTemplate

logger = logging.getLogger(__name__)

DELIVER_JOB = "notifications.deliver"
MAX_ATTEMPTS = 5
CHANNEL_DEFAULTS = {IN_APP: True, EMAIL: True, WHATSAPP: True, SMS: False}  # SMS: no free provider
S = Notification.Status


# --- Raising an event ------------------------------------------------------------------------------


def notify(user, *, event: str, context: dict | None = None, data: dict | None = None, key: str = "") -> None:
    """Send `event` to `user` after the current transaction commits. `context` fills the message's
    variables; `data` is kept with the notification (deep links); `key` makes it unique (default: the
    event and its data, which is right for one-off events — pass a key when an event may rightly repeat)."""
    get_event(event)  # an unknown event is a programming error: fail in tests, not silently
    if user is None:
        return
    payload = {"event": event, "context": dict(context or {}), "data": dict(data or {}), "key": key}
    user_id = user.pk
    transaction.on_commit(lambda: _dispatch_safely(user_id, payload))


def notify_many(users, **kwargs) -> None:
    for user in {u.pk: u for u in users if u is not None}.values():
        notify(user, **kwargs)


def notify_order(order, event: str, *, data: dict | None = None, key: str = "", **context) -> None:
    """An order event for its customer; `order_number` is always a variable and part of the data."""
    base = {"order_number": order.order_number}
    notify(order.user, event=event, context={**base, **context}, data={**base, **(data or {})}, key=key)


def notify_order_staff(order, event: str, *, data: dict | None = None, key: str = "", **context) -> None:
    """The same for the people who run the order's stores (managers, else administrators)."""
    base = {"order_number": order.order_number}
    notify_many(
        staff_for_order(order), event=event, context={**base, **context}, data={**base, **(data or {})}, key=key
    )


def staff_for_stores(store_ids) -> list:
    """Who hears about a store's orders: its active managers, or the administrators when it has none."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    managers = list(User.objects.filter(managed_stores__in=list(store_ids), is_active=True).distinct())
    if managers:
        return managers
    return list(User.objects.filter(Q(role="admin") | Q(is_superuser=True), is_active=True))


def staff_for_order(order) -> list:
    store_ids = set(order.shipments.values_list("store_id", flat=True))
    if order.store_id:
        store_ids.add(order.store_id)
    return staff_for_stores(store_ids)


def _dispatch_safely(user_id: int, payload: dict) -> None:
    try:
        dispatch(user_id, **payload)
    except Exception:  # noqa: BLE001 — a notification must never break the action that raised it
        logger.exception("Notification %s for user %s could not be routed", payload.get("event"), user_id)


def dispatch(user_id: int, *, event: str, context: dict, data: dict, key: str = "") -> list[Notification]:
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(pk=user_id, is_active=True).select_related("profile").first()
    if user is None:
        return []
    spec = get_event(event)
    key = key or _default_key(event, data)
    language = _language(user)
    created = []
    for channel in channels_for(user, spec):
        title, body, template_name = compose(spec, channel, language, user, context, data)
        variables = {k: v for k, v in context.items() if k not in spec.secret}
        try:
            with transaction.atomic():
                note = Notification.objects.create(
                    user=user,
                    channel=channel,
                    event=event,
                    title=title[:150],
                    body=body[:2000],
                    data={**data, "_vars": _jsonable(variables)},
                    dedupe_key=key[:160],
                    language=language,
                    template_name=template_name,
                    status=S.SENT if channel == IN_APP else S.PENDING,
                    provider="in_app" if channel == IN_APP else "",
                    sent_at=timezone.now() if channel == IN_APP else None,
                )
        except IntegrityError:
            continue  # already sent for this key: a duplicate event
        created.append(note)
        if channel != IN_APP:
            enqueue(DELIVER_JOB, {"notification_id": note.pk}, dedupe_key=f"notification:{note.pk}")
    return created


def _default_key(event: str, data: dict) -> str:
    raw = json.dumps(data, sort_keys=True, default=str)
    return f"{event}:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


def _jsonable(values: dict) -> dict:
    return {k: v if isinstance(v, (int, float, bool)) or v is None else str(v) for k, v in values.items()}


def _language(user) -> str:
    profile = getattr(user, "profile", None)
    return getattr(profile, "preferred_language", "") or "en"


# --- Routing ---------------------------------------------------------------------------------------


def channel_enabled(channel: str) -> bool:
    row = ChannelSetting.objects.filter(channel=channel).first()
    return row.enabled if row else CHANNEL_DEFAULTS.get(channel, False)


def event_channels(spec: Event) -> dict[str, bool]:
    """Each allowed channel of an event: on or off (the administrator's setting, else the default)."""
    rows = dict(EventSetting.objects.filter(event=spec.key).values_list("channel", "enabled"))
    return {ch: rows.get(ch, ch in spec.channels) for ch in spec.allowed}


def preferences(user) -> NotificationPreference:
    prefs, _ = NotificationPreference.objects.get_or_create(user=user)
    return prefs


def wants(user, channel: str, spec: Event, prefs: NotificationPreference | None = None) -> bool:
    """The person's own choice. In-app is always kept; muted categories never stop critical events."""
    if channel == IN_APP:
        return True
    prefs = prefs or preferences(user)
    if not spec.critical and spec.category in (prefs.muted_categories or []):
        return False
    if channel == EMAIL:
        return prefs.email
    if channel == SMS:
        return prefs.sms
    if channel == WHATSAPP:
        profile = getattr(user, "profile", None)
        return bool(profile and profile.whatsapp_opt_in)
    return False


def channels_for(user, spec: Event) -> list[str]:
    prefs = preferences(user)
    switched_on = event_channels(spec)
    return [ch for ch in ALL_CHANNELS if switched_on.get(ch) and channel_enabled(ch) and wants(user, ch, spec, prefs)]


# --- Words -----------------------------------------------------------------------------------------


def link_for(spec: Event, data: dict) -> str:
    """The app path the notification opens, or "" when the data doesn't name one."""
    if not spec.link:
        return ""
    try:
        return templating.render(spec.link, data)
    except templating.TemplateError:
        return ""


def common_context(user, spec: Event, data: dict) -> dict:
    path = link_for(spec, data)
    first = (getattr(user, "full_name", "") or "").split(" ")[0]
    return {
        "customer_name": first or "there",
        "shop_name": settings.APP_NAME,
        "link": settings.FRONTEND_URL + (path or "/"),
    }


def template_for(spec: Event, channel: str, language: str) -> NotificationTemplate | None:
    rows = {
        row.language: row
        for row in NotificationTemplate.objects.filter(event=spec.key, channel=channel, language__in=[language, "en"])
    }
    return rows.get(language) or rows.get("en")


def compose(spec: Event, channel: str, language: str, user, context: dict, data: dict, *, reveal: dict | None = None):
    """(title, body, WhatsApp template name). The shop's template when it renders, else the default words.
    Secret variables are masked unless their values are passed in `reveal` (only at the moment of sending)."""
    values = {**common_context(user, spec, data), **context, **(reveal or {})}
    secret, show = spec.secret, reveal is not None
    custom = template_for(spec, channel, language)
    default_title, default_body = spec.default_text(channel)
    if custom is not None:
        try:
            return (
                templating.render(custom.title or default_title, values, secret=secret, reveal=show),
                templating.render(custom.body, values, secret=secret, reveal=show),
                custom.provider_template or spec.whatsapp_template,
            )
        except templating.TemplateError as exc:
            logger.warning("Template %s/%s/%s can't be used (%s); default words sent", spec.key, channel, language, exc)
    try:
        return (
            templating.render(default_title, values, secret=secret, reveal=show),
            templating.render(default_body, values, secret=secret, reveal=show),
            spec.whatsapp_template,
        )
    except templating.TemplateError as exc:
        logger.error("Event %s is missing a variable (%s)", spec.key, exc)
        return spec.label, "", spec.whatsapp_template


def whatsapp_parameters(spec: Event, channel: str, language: str, values: dict) -> list[str]:
    """Body parameters for an approved WhatsApp template: the message's variables, in order of appearance."""
    custom = template_for(spec, channel, language)
    text = custom.body if custom is not None else spec.default_text(channel)[1]
    return [str(values.get(name, "")) for name in templating.variables_in(text)]


# --- Delivery (background job) --------------------------------------------------------------------


def _secret_values(note: Notification, spec: Event) -> dict | None:
    """Values that are never stored, looked up again when sending. None: the message is no longer valid."""
    if "otp" in spec.secret:
        from apps.delivery import otp
        from apps.delivery.models import DeliveryAssignment

        assignment = DeliveryAssignment.objects.filter(pk=note.data.get("assignment_id")).first()
        code = otp.code_for_customer(assignment) if assignment else None
        return {"otp": code} if code else None
    return {}


def _mark(note: Notification, status: str, *, error: str = "", **fields) -> None:
    note.status, note.error = status, error[:255]
    for name, value in fields.items():
        setattr(note, name, value)
    if status == S.SENT and not note.sent_at:
        note.sent_at = timezone.now()
    note.save()


def deliver(notification_id: int) -> str:
    """Send one pending email/WhatsApp/SMS notification. Raises on a temporary failure so the job queue
    retries it with backoff; every other outcome is written on the row."""
    with transaction.atomic():
        note = (
            Notification.objects.select_for_update()
            .select_related("user", "user__profile")
            .filter(pk=notification_id)
            .first()
        )
        if note is None or note.status != S.PENDING:
            return "skipped"
        note.attempts += 1
        note.save(update_fields=["attempts", "updated_at"])
    spec = EVENTS.get(note.event)
    if spec is None:
        _mark(note, S.FAILED, error="Unknown event.")
        return S.FAILED
    if not note.user.is_active:
        _mark(note, S.SKIPPED, error="Account inactive.")
        return S.SKIPPED
    try:
        if note.channel == EMAIL:
            return _send_email(note, spec)
        if note.channel in (WHATSAPP, SMS):
            return _send_message(note, spec)
        _mark(note, S.SKIPPED, error="Channel not available.")
        return S.SKIPPED
    except MessagingUnavailable as exc:
        _mark(note, S.SKIPPED, error=str(exc))
        return S.SKIPPED
    except Exception as exc:  # noqa: BLE001 — recorded here; retried by the job queue when temporary
        retryable = getattr(exc, "retryable", not isinstance(exc, MessagingError))
        final = not retryable or note.attempts >= MAX_ATTEMPTS
        _mark(note, S.FAILED if final else S.PENDING, error=f"{exc}"[:255])
        if final:
            logger.warning("Notification %s (%s) failed: %s", note.pk, note.channel, exc)
            return S.FAILED
        raise


def _send_email(note: Notification, spec: Event) -> str:
    email = note.user.email
    if not email:
        _mark(note, S.SKIPPED, error="No email address.")
        return S.SKIPPED
    link = common_context(note.user, spec, note.data)["link"] if spec.link else ""
    body = note.body + (f"\n\n{link}" if link else "")
    send_mail(note.title, body, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
    _mark(note, S.SENT, provider="django_email", recipient=_mask_email(email))
    return S.SENT


def _send_message(note: Notification, spec: Event) -> str:
    user = note.user
    if note.channel == WHATSAPP and not wants(user, WHATSAPP, spec):
        _mark(note, S.SKIPPED, error="The customer turned WhatsApp off.")
        return S.SKIPPED
    if not user.phone:
        _mark(note, S.SKIPPED, error="No phone number on the account.")
        return S.SKIPPED
    provider = get_whatsapp_provider() if note.channel == WHATSAPP else get_sms_provider()
    if not provider.configured:
        raise MessagingUnavailable(f"No {note.get_channel_display()} provider is configured.")
    reveal = _secret_values(note, spec)
    if reveal is None:
        _mark(note, S.SKIPPED, error="No longer valid (the delivery code changed or was used).")
        return S.SKIPPED
    context = {k: v for k, v in note.data.get("_vars", {}).items()}
    _title, text, template = compose(spec, note.channel, note.language, user, context, note.data, reveal=reveal)
    values = {**common_context(user, spec, note.data), **context, **reveal}
    to = to_e164(user.phone, settings.PHONE_COUNTRY_CODE)
    result = provider.send(
        OutgoingMessage(
            to=to,
            text=text,
            template=template if note.channel == WHATSAPP else "",
            language=note.language.split("-")[0],
            parameters=whatsapp_parameters(spec, note.channel, note.language, values)
            if note.channel == WHATSAPP
            else [],
            reference=f"n{note.pk}",
        )
    )
    _mark(
        note,
        S.SENT,
        provider=provider.name,
        provider_message_id=result.message_id,
        provider_status=result.status,
        recipient=mask_phone(to),
        template_name=template if note.channel == WHATSAPP else "",
    )
    return S.SENT


def _mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}•••@{domain}" if domain else "•••"


# --- Inbox -----------------------------------------------------------------------------------------


def inbox(user):
    return Notification.objects.filter(user=user, channel=IN_APP)


def unread_count(user) -> int:
    return inbox(user).filter(read_at__isnull=True).count()


def mark_read(user, ids=None) -> int:
    """Mark the given in-app notifications (or all of them) read. Only the person's own."""
    rows = inbox(user).filter(read_at__isnull=True)
    if ids is not None:
        rows = rows.filter(pk__in=ids)
    return rows.update(read_at=timezone.now(), updated_at=timezone.now())


def mark_unread(user, notification_id: int) -> int:
    return inbox(user).filter(pk=notification_id).update(read_at=None, updated_at=timezone.now())


# --- Administration --------------------------------------------------------------------------------


def retry(note: Notification) -> bool:
    """Send a failed (or skipped) email/WhatsApp/SMS notification again."""
    if note.channel == IN_APP or note.status not in (S.FAILED, S.SKIPPED):
        return False
    updated = Notification.objects.filter(pk=note.pk, status__in=[S.FAILED, S.SKIPPED]).update(
        status=S.PENDING, attempts=0, error="", updated_at=timezone.now()
    )
    if updated:
        enqueue(DELIVER_JOB, {"notification_id": note.pk}, dedupe_key=f"notification:{note.pk}")
    return bool(updated)


def apply_receipt(provider_message_id: str, status: str, *, error: str = "", at=None) -> bool:
    """A delivery receipt from the provider (sent → delivered → read, or failed)."""
    note = Notification.objects.filter(provider_message_id=provider_message_id).first()
    if note is None:
        return False
    order = ["queued", "sent", "delivered", "read"]
    fields = {}
    if status == "failed":
        fields = {"status": S.FAILED, "provider_status": "failed", "error": (error or "Not delivered.")[:255]}
    elif status in order and (
        note.provider_status not in order or order.index(status) > order.index(note.provider_status)
    ):
        fields = {"provider_status": status}
        if status in ("delivered", "read") and not note.delivered_at:
            fields["delivered_at"] = at or timezone.now()
    if fields:
        Notification.objects.filter(pk=note.pk).update(**fields, updated_at=timezone.now())
    return True


def provider_overview() -> list[dict]:
    """Per channel: switched on?, which provider, is it real?, and the last 24 hours of the log."""
    since = timezone.now() - timedelta(hours=24)
    counts = {
        (row["channel"], row["status"]): row["n"]
        for row in Notification.objects.filter(created_at__gte=since)
        .values("channel", "status")
        .annotate(n=Count("id"))
    }
    last = {
        row["channel"]: row["at"]
        for row in Notification.objects.filter(status=S.SENT).values("channel").annotate(at=Max("sent_at"))
    }
    providers = {
        IN_APP: {"provider": "in_app", "configured": True, "mock": False, "live": True},
        EMAIL: _email_status(),
        WHATSAPP: get_whatsapp_provider().status(),
        SMS: get_sms_provider().status(),
    }
    rows = []
    for channel in ALL_CHANNELS:
        last_failure = Notification.objects.filter(channel=channel, status=S.FAILED).order_by("-updated_at").first()
        rows.append(
            {
                "channel": channel,
                "enabled": channel_enabled(channel),
                **providers[channel],
                "last_24h": {status: counts.get((channel, status), 0) for status in S.values},
                "last_sent_at": last.get(channel),
                "last_error": last_failure.error if last_failure else "",
            }
        )
    return rows


def _email_status() -> dict:
    backend = settings.EMAIL_BACKEND.rsplit(".", 1)[0].rsplit(".", 1)[-1]  # smtp | console | locmem | …
    live = backend == "smtp"
    return {"provider": f"django_email ({backend})", "configured": True, "mock": not live, "live": live}


def event_catalogue() -> list[dict]:
    """Every event with its channels (on/off), variables and the words in use for each channel."""
    settings_rows = {(r.event, r.channel): r.enabled for r in EventSetting.objects.all()}
    templates: dict[tuple[str, str], list[NotificationTemplate]] = {}
    for row in NotificationTemplate.objects.all():
        templates.setdefault((row.event, row.channel), []).append(row)
    out = []
    for spec in EVENTS.values():
        channels = []
        for ch in spec.allowed:
            title, body = spec.default_text(ch)
            channels.append(
                {
                    "channel": ch,
                    "enabled": settings_rows.get((spec.key, ch), ch in spec.channels),
                    "default_enabled": ch in spec.channels,
                    "default_title": title,
                    "default_body": body,
                    "default_provider_template": spec.whatsapp_template if ch == WHATSAPP else "",
                    "templates": [
                        {
                            "id": t.pk,
                            "language": t.language,
                            "title": t.title,
                            "body": t.body,
                            "provider_template": t.provider_template,
                            "updated_at": t.updated_at,
                        }
                        for t in templates.get((spec.key, ch), [])
                    ],
                }
            )
        out.append(
            {
                "key": spec.key,
                "label": spec.label,
                "category": spec.category,
                "category_label": CATEGORIES.get(spec.category, spec.category),
                "audience": spec.audience,
                "critical": spec.critical,
                "variables": list(spec.all_variables),
                "secret_variables": list(spec.secret),
                "channels": channels,
            }
        )
    return out


def sample_context(spec: Event) -> dict:
    """Example values for a preview: each variable shown as itself, so the admin sees the layout."""
    examples = {
        "order_number": "OD2610060001",
        "amount": "1,250.00",
        "otp": "••••••",
        "rider_name": "Ravi",
        "store_name": "Main Store",
        "item_count": "3",
        "return_number": "RT2610060001",
        "quote_number": "QT2610060001",
        "valid_until": "16 Oct 2026",
        "lines": "4",
        "available": "3",
        "threshold": "5",
    }
    return {name: examples.get(name, f"[{name}]") for name in spec.variables}


# --- Delays (periodic) -----------------------------------------------------------------------------


def tell_about_delays(now=None) -> int:
    """Active orders past their delivery estimate get one "running late" message (and their staff)."""
    from django.db.models import Exists, OuterRef

    from apps.orders.models import Order, OrderStatus

    now = now or timezone.now()
    cutoff = now - timedelta(minutes=settings.DELIVERY_DELAY_NOTICE_MINUTES)
    active = [
        OrderStatus.CONFIRMED,
        OrderStatus.PROCESSING,
        OrderStatus.PACKED,
        OrderStatus.ASSIGNED,
        OrderStatus.PICKED_UP,
        OrderStatus.OUT_FOR_DELIVERY,
    ]
    told = Notification.objects.filter(
        event="delivery.delayed", user_id=OuterRef("user_id"), data__order_number=OuterRef("order_number")
    )
    late = (
        Order.objects.filter(status__in=active, estimated_delivery_at__lt=cutoff)
        .exclude(Exists(told))
        .select_related("user")[:200]
    )
    count = 0
    for order in late:
        with transaction.atomic():
            data = {"order_number": order.order_number}
            notify(order.user, event="delivery.delayed", context=data, data=data, key=f"delayed:{order.order_number}")
            notify_many(
                staff_for_order(order),
                event="staff.delivery_delayed",
                context=data,
                data=data,
                key=f"delayed:{order.order_number}",
            )
        count += 1
    return count
