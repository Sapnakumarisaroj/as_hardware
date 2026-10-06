"""WhatsApp Cloud API webhook: delivery receipts and messages customers send to the shop's number.

- Signature: `X-Hub-Signature-256: sha256=<HMAC of the raw body with WHATSAPP_APP_SECRET>`. Without a
  secret configured every POST is refused, so the endpoint does nothing until the owner sets one up.
- Receipts (`statuses`) update the delivery log: sent → delivered → read, or failed with Meta's reason.
- Messages (`messages`, text only) open or continue a WhatsApp support conversation, matched to the
  account with that phone number (or kept as a phone contact). "STOP" turns WhatsApp messages off for
  that account. Each message id is applied once (Meta redelivers).
"""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import services

logger = logging.getLogger(__name__)
STOP_WORDS = {"stop", "unsubscribe", "band karo", "बंद"}


def verify_subscription(params) -> str | None:
    token = settings.WHATSAPP_VERIFY_TOKEN
    if (
        params.get("hub.mode") == "subscribe"
        and token
        and hmac.compare_digest(params.get("hub.verify_token", ""), token)
    ):
        return params.get("hub.challenge", "")
    return None


def signature_ok(body: bytes, header: str) -> bool:
    secret = settings.WHATSAPP_APP_SECRET
    if not secret or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def process(body: bytes) -> dict:
    payload = json.loads(body or b"{}")
    receipts = messages = 0
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for item in value.get("statuses", []) or []:
                receipts += _receipt(item)
            for item in value.get("messages", []) or []:
                messages += _incoming(item)
    return {"receipts": receipts, "messages": messages}


def _when(raw) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(raw), tz=UTC)
    except (TypeError, ValueError):
        return None


def _receipt(item: dict) -> int:
    error = ""
    if item.get("errors"):
        first = item["errors"][0] or {}
        error = str(first.get("title") or first.get("message") or first.get("code") or "")
    return int(
        services.apply_receipt(
            str(item.get("id", "")), str(item.get("status", "")), error=error, at=_when(item.get("timestamp"))
        )
    )


def _incoming(item: dict) -> int:
    from django.contrib.auth import get_user_model

    from apps.accounts.models import CustomerProfile
    from apps.core.validators import normalize_phone
    from apps.support.models import SupportConversation, SupportMessage

    message_id = str(item.get("id", ""))
    text = ((item.get("text") or {}).get("body") or "").strip()
    phone = normalize_phone(str(item.get("from", "")))
    if not message_id or not phone:
        return 0
    if not text:
        text = f"[{item.get('type', 'message')} received on WhatsApp — open WhatsApp Manager to see it]"
    with transaction.atomic():
        if SupportMessage.objects.filter(channel_message_id=message_id).exists():
            return 0  # redelivery
        user = get_user_model().objects.filter(phone=phone, is_active=True).first()
        if user and text.lower() in STOP_WORDS:
            CustomerProfile.objects.filter(user=user).update(whatsapp_opt_in=False, updated_at=timezone.now())
        open_states = [SupportConversation.Status.OPEN, SupportConversation.Status.WAITING_CUSTOMER]
        conversation = (
            SupportConversation.objects.select_for_update()
            .filter(
                channel="whatsapp", status__in=open_states, **({"user": user} if user else {"contact_phone": phone})
            )
            .first()
        )
        if conversation is None:
            conversation = SupportConversation.objects.create(
                user=user, contact_phone=phone, channel="whatsapp", subject="WhatsApp message"
            )
        SupportMessage.objects.create(
            conversation=conversation,
            sender_type=SupportMessage.Sender.CUSTOMER,
            sender=user,
            body=text[:4000],
            channel_message_id=message_id,
        )
        conversation.status = SupportConversation.Status.OPEN
        conversation.last_message_at = timezone.now()
        conversation.save(update_fields=["status", "last_message_at", "updated_at"])
    return 1
