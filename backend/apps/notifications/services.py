"""Record and deliver customer notifications with free, built-in channels.

- in_app: the Notification row *is* the delivery (shown in the app), so it is marked sent.
- email: sent through Django's configured EMAIL_BACKEND (console in development, the
  hosting mailbox's SMTP in production). A failure is recorded, never hidden.

Nothing is sent until the surrounding transaction commits, so a rolled-back order never
produces a "your order is confirmed" message. SMS/WhatsApp providers arrive in Phase 20.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import Channel, Notification

logger = logging.getLogger(__name__)

DEFAULT_CHANNELS = (Channel.IN_APP, Channel.EMAIL)


def notify(user, *, event: str, title: str, body: str, data: dict | None = None, channels=DEFAULT_CHANNELS) -> None:
    """Queue a notification for `user` on each channel, delivered after commit."""
    payload = {"event": event, "title": title[:150], "body": body[:2000], "data": data or {}}
    transaction.on_commit(lambda: _deliver(user, payload, tuple(channels)))


def _deliver(user, payload: dict, channels: tuple[str, ...]) -> None:
    for channel in channels:
        note = Notification.objects.create(user=user, channel=channel, **payload)
        if channel == Channel.IN_APP:
            _mark(note, Notification.Status.SENT, provider="in_app")
        elif channel == Channel.EMAIL:
            _send_email(user, note)
        else:
            _mark(note, Notification.Status.SKIPPED, provider="", error="Channel not configured.")


def _send_email(user, note: Notification) -> None:
    if not user.email:
        _mark(note, Notification.Status.SKIPPED, provider="django_email", error="No email address.")
        return
    try:
        send_mail(note.title, note.body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
    except Exception as exc:  # noqa: BLE001 - any backend failure is recorded, not raised to the customer
        logger.warning("Email notification %s failed: %s", note.pk, exc)
        _mark(note, Notification.Status.FAILED, provider="django_email", error=str(exc)[:255])
        return
    _mark(note, Notification.Status.SENT, provider="django_email")


def _mark(note: Notification, status: str, *, provider: str, error: str = "") -> None:
    note.status = status
    note.provider = provider
    note.error = error
    fields = ["status", "provider", "error", "updated_at"]
    if status == Notification.Status.SENT:
        note.sent_at = timezone.now()
        fields.append("sent_at")
    note.save(update_fields=fields)
