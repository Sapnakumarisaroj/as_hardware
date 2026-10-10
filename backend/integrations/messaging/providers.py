"""Messaging providers: mocks for development (the default) and the WhatsApp Cloud API."""

import hashlib
import json
import logging
import urllib.error
import urllib.request
from collections import deque

from .base import (
    MediaFile,
    MessagingError,
    MessagingProvider,
    MessagingUnavailable,
    OutgoingMessage,
    SendResult,
    mask_phone,
)

logger = logging.getLogger(__name__)

# What the mocks "sent", newest last (tests and the dev shell read it). Bounded, process-local.
OUTBOX: deque[dict] = deque(maxlen=200)


class _MockProvider(MessagingProvider):
    """Sends nothing. Records the message so development and tests can see it.

    Numbers ending in 0000 behave like a number that can't receive messages (permanent failure) and
    numbers ending in 9999 like a provider outage (temporary failure, retried), so the failure screens
    can be tried without a real account.
    """

    is_mock = True

    @property
    def configured(self) -> bool:
        return True

    def send(self, message: OutgoingMessage) -> SendResult:
        if message.to.endswith("0000"):
            raise MessagingError("Mock: this number can't receive messages.", code="invalid_recipient")
        if message.to.endswith("9999"):
            raise MessagingError("Mock: provider temporarily unavailable.", retryable=True, code="unavailable")
        digest = hashlib.sha256(f"{self.channel}:{message.reference}:{message.to}".encode()).hexdigest()[:20]
        OUTBOX.append({"channel": self.channel, **message.__dict__})
        logger.info(
            "Mock %s to %s (%s): %s",
            self.channel,
            mask_phone(message.to),
            message.template or "text",
            message.reference,
        )
        return SendResult(message_id=f"mock-{self.channel}-{digest}")

    def send_text(self, to: str, text: str, *, reference: str = "") -> SendResult:
        return self.send(OutgoingMessage(to=to, text=text, reference=reference))


class MockWhatsAppProvider(_MockProvider):
    name = "mock"
    channel = "whatsapp"


class MockSMSProvider(_MockProvider):
    name = "mock"
    channel = "sms"


class NoWhatsAppProvider(MessagingProvider):
    name = "none"
    channel = "whatsapp"


class NoSMSProvider(MessagingProvider):
    name = "none"
    channel = "sms"


class MetaWhatsAppProvider(MessagingProvider):
    """WhatsApp Cloud API (graph.facebook.com). Business-initiated messages must use templates that
    Meta has approved for the account; their body parameters are filled in order."""

    name = "meta"
    channel = "whatsapp"

    def __init__(self, *, access_token: str, phone_number_id: str, api_version: str, timeout: float):
        self._token = access_token
        self.phone_number_id = phone_number_id
        self.api_version = api_version
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._token and self.phone_number_id)

    def status(self) -> dict:
        return {**super().status(), "phone_number_id": self.phone_number_id[-4:].rjust(len(self.phone_number_id), "•")}

    def send(self, message: OutgoingMessage) -> SendResult:
        if not self.configured:
            raise MessagingUnavailable("WhatsApp Cloud API credentials are not set.")
        if not message.template:
            raise MessagingError("No approved WhatsApp template is set for this message.", code="template_missing")
        body = {
            "messaging_product": "whatsapp",
            "to": message.to,
            "type": "template",
            "template": {
                "name": message.template,
                "language": {"code": message.language or "en"},
                "components": [
                    {"type": "body", "parameters": [{"type": "text", "text": p} for p in message.parameters]}
                ]
                if message.parameters
                else [],
            },
        }
        data = self._post(f"/{self.phone_number_id}/messages", body)
        try:
            return SendResult(message_id=data["messages"][0]["id"], status="queued")
        except (KeyError, IndexError, TypeError) as exc:
            raise MessagingError("WhatsApp answered without a message id.", retryable=True) from exc

    def send_text(self, to: str, text: str, *, reference: str = "") -> SendResult:
        """A session (free-form) message: only valid within 24 hours of the customer's last message."""
        if not self.configured:
            raise MessagingUnavailable("WhatsApp Cloud API credentials are not set.")
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text[:4096], "preview_url": True},
        }
        data = self._post(f"/{self.phone_number_id}/messages", body)
        try:
            return SendResult(message_id=data["messages"][0]["id"], status="queued")
        except (KeyError, IndexError, TypeError) as exc:
            raise MessagingError("WhatsApp answered without a message id.", retryable=True) from exc

    def fetch_media(self, media_id: str, *, max_bytes: int) -> MediaFile | None:
        """GET /{media-id} gives a short-lived URL; that URL needs the same bearer token."""
        if not self.configured:
            raise MessagingUnavailable("WhatsApp Cloud API credentials are not set.")
        meta = self._request(f"https://graph.facebook.com/{self.api_version}/{media_id}")
        url, mime = str(meta.get("url") or ""), str(meta.get("mime_type") or "")
        if not url.startswith("https://"):
            raise MessagingError("WhatsApp did not return a download link for this file.", code="media_missing")
        size = int(meta.get("file_size") or 0)
        if size > max_bytes:
            raise MessagingError("This file is too large to open here.", code="media_too_large")
        content = self._request(url, raw=True, max_bytes=max_bytes)
        return MediaFile(content=content, mime_type=mime.split(";")[0].strip().lower())

    def _request(self, url: str, *, raw: bool = False, max_bytes: int = 0):
        req = urllib.request.Request(url, method="GET")  # noqa: S310 — https only (checked by the caller)
        req.add_header("Authorization", f"Bearer {self._token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:  # noqa: S310
                if not raw:
                    return json.loads(res.read() or b"{}")
                content = res.read(max_bytes + 1)
                if len(content) > max_bytes:
                    raise MessagingError("This file is too large to open here.", code="media_too_large")
                return content
        except urllib.error.HTTPError as err:
            raise MessagingError(f"WhatsApp: HTTP {err.code}", retryable=err.code >= 500, code=str(err.code)) from err
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            raise MessagingError(f"Could not reach WhatsApp: {err}", retryable=True, code="network") from err

    def _post(self, path: str, body: dict) -> dict:
        url = f"https://graph.facebook.com/{self.api_version}{path}"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")  # noqa: S310 — fixed https host
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:  # noqa: S310 — fixed https host
                return json.loads(res.read() or b"{}")
        except urllib.error.HTTPError as err:
            try:
                error = json.loads(err.read() or b"{}").get("error", {})
            except ValueError:
                error = {}
            detail = str(error.get("message") or f"HTTP {err.code}")[:200]
            retryable = err.code >= 500 or err.code == 429 or error.get("code") in (4, 80007, 130429, 131000, 131016)
            raise MessagingError(
                f"WhatsApp: {detail}", retryable=retryable, code=str(error.get("code", err.code))
            ) from err
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            raise MessagingError(f"Could not reach WhatsApp: {err}", retryable=True, code="network") from err
