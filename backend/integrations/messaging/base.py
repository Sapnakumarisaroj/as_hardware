"""WhatsApp and SMS behind one small interface (Phase 23).

The shop never needs a messaging account to work: the default providers are mocks that record what
*would* have been sent (in the delivery log, never pretending it reached a phone), and in-app + email
notifications carry every message anyway. A real provider is switched on with settings only:

- WhatsApp: `meta` (WhatsApp Cloud API, pre-approved templates; Meta bills per conversation, so it needs
  the owner's own WhatsApp Business account and approval before use);
- SMS: architecture only. `mock` and `none` ship; a paid gateway (MSG91, Twilio…) is one class here.

A provider only delivers text. Which event fires, who receives it, what the words are and whether the
customer opted in is decided by `apps.notifications`.
"""

from dataclasses import dataclass, field


class MessagingError(Exception):
    """The provider refused or failed. `retryable` errors (timeouts, 5xx, rate limits) are tried again
    with backoff; the others (invalid number, template not approved) fail at once."""

    def __init__(self, message: str, *, retryable: bool = False, code: str = ""):
        super().__init__(message)
        self.retryable = retryable
        self.code = code


class MessagingUnavailable(MessagingError):
    """The channel is not configured (provider `none`, credentials missing)."""


@dataclass(frozen=True)
class OutgoingMessage:
    to: str  # E.164 without "+", e.g. "919812345678"
    text: str  # the rendered message (mock providers and SMS send this)
    template: str = ""  # WhatsApp: the approved template name
    language: str = "en"
    parameters: list[str] = field(default_factory=list)  # WhatsApp: template body parameters, in order
    reference: str = ""  # our id, for the provider's logs


@dataclass(frozen=True)
class SendResult:
    message_id: str
    status: str = "sent"  # sent | queued (provider accepted it; delivery receipts may follow)


@dataclass(frozen=True)
class MediaFile:
    """A photo or document a customer sent (WhatsApp keeps it; we fetch it only when staff open it)."""

    content: bytes
    mime_type: str


class MessagingProvider:
    name = "none"
    channel = ""
    is_mock = False

    @property
    def configured(self) -> bool:
        return False

    def send(self, message: OutgoingMessage) -> SendResult:
        raise MessagingUnavailable(f"No {self.channel or 'messaging'} provider is configured.")

    def send_text(self, to: str, text: str, *, reference: str = "") -> SendResult:
        """A free-form reply. WhatsApp allows it only within 24 hours of the customer's last message
        (the caller checks the window); outside it only approved templates may be sent."""
        raise MessagingUnavailable(f"No {self.channel or 'messaging'} provider is configured.")

    def fetch_media(self, media_id: str, *, max_bytes: int) -> MediaFile | None:
        """The bytes of an incoming attachment, or None when this provider can't fetch it (mocks).
        Raises MessagingError when the provider refuses or the file is larger than `max_bytes`."""
        return None

    def status(self) -> dict:
        """What the admin's provider screen shows. Never includes a secret."""
        return {
            "provider": self.name,
            "configured": self.configured,
            "mock": self.is_mock,
            "live": self.configured and not self.is_mock,
        }


def to_e164(phone: str, country_code: str) -> str:
    """Stored phones are 10 digits (core.validators.normalize_phone); providers want the country code."""
    digits = "".join(ch for ch in phone or "" if ch.isdigit())
    if len(digits) == 10:
        return country_code + digits
    return digits


def mask_phone(phone: str) -> str:
    """ "919812345678" → "+91 98•••••678". What logs and admin screens show instead of the number."""
    digits = "".join(ch for ch in phone or "" if ch.isdigit())
    if len(digits) < 6:
        return "•" * len(digits)
    local = digits[-10:]
    prefix = digits[: len(digits) - len(local)]
    return f"{'+' + prefix + ' ' if prefix else ''}{local[:2]}{'•' * (len(local) - 5)}{local[-3:]}"
