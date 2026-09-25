"""Payment gateway interface. Business code depends only on this, never on a vendor SDK.

Trust model: the browser only *reports* that something happened. Every result the business code
acts on comes from the gateway itself — a verified checkout signature followed by a server-side
fetch of the payment, a signature-verified webhook, or a reconciliation fetch.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


class GatewayError(Exception):
    """Temporary failure (network, timeout, 5xx). Safe to retry: every call we retry is idempotent."""


class GatewayRejected(Exception):
    """The gateway refused the request (4xx: invalid amount, already refunded…). Retrying won't help."""


class InvalidSignature(Exception):
    """A checkout response or webhook whose HMAC signature does not match: treat as forged."""


@dataclass(frozen=True)
class PaymentIntent:
    provider: str
    provider_order_id: str
    amount: Decimal
    currency: str
    # Public data the frontend needs to open the checkout widget. Never secrets.
    client_payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GatewayPayment:
    """A payment as the gateway reports it."""

    provider_payment_id: str
    status: str  # created | authorized | captured | failed | refunded
    amount: Decimal
    provider_order_id: str = ""
    currency: str = "INR"
    method: str = "unknown"
    failure_reason: str = ""


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    provider_payment_id: str | None = None
    method: str = "unknown"
    failure_reason: str = ""
    # The customer closed/abandoned the payment (not a decline). They may try again.
    cancelled: bool = False
    # Genuine, but the gateway hasn't finished yet (e.g. UPI still processing). A webhook or
    # reconciliation completes it; nothing is marked failed.
    pending: bool = False
    amount: Decimal | None = None  # amount the gateway captured (checked against the order)


@dataclass(frozen=True)
class RefundResult:
    success: bool  # accepted by the gateway (pending or processed)
    provider_refund_id: str | None = None
    status: str = "pending"  # pending | processed | failed
    failure_reason: str = ""


@dataclass(frozen=True)
class WebhookEvent:
    """A signature-verified webhook, normalised. `data` is sanitised (no card/contact details)."""

    event_id: str
    event_type: str
    payment: GatewayPayment | None = None
    refund: "GatewayRefund | None" = None
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GatewayRefund:
    provider_refund_id: str
    provider_payment_id: str
    status: str  # pending | processed | failed
    amount: Decimal


class PaymentProvider(ABC):
    name: str
    is_test_mode: bool = False

    @abstractmethod
    def create_payment(
        self, *, reference: str, amount: Decimal, currency: str = "INR", customer: dict | None = None
    ) -> PaymentIntent: ...

    @abstractmethod
    def verify_payment(
        self, *, provider_order_id: str, payload: dict, expected_amount: Decimal | None = None
    ) -> VerificationResult:
        """Check what the browser reported, then confirm it with the gateway."""

    @abstractmethod
    def fetch_order_payments(self, *, provider_order_id: str) -> list[GatewayPayment]:
        """All payment attempts on a gateway order (for reconciliation)."""

    @abstractmethod
    def capture(self, *, provider_payment_id: str, amount: Decimal, currency: str = "INR") -> GatewayPayment: ...

    @abstractmethod
    def refund(self, *, provider_payment_id: str, amount: Decimal, reference: str) -> RefundResult:
        """Refund `amount`. Idempotent on `reference`: repeating a call (after a timeout) never refunds twice."""

    @abstractmethod
    def fetch_refund(self, *, provider_payment_id: str, provider_refund_id: str) -> RefundResult: ...

    @abstractmethod
    def parse_webhook(self, *, body: bytes, headers) -> WebhookEvent:
        """Verify the signature over the raw body and normalise the event. Raises InvalidSignature."""


def to_paise(amount: Decimal) -> int:
    return int((Decimal(amount) * 100).quantize(Decimal("1")))


def from_paise(value) -> Decimal:
    return (Decimal(int(value or 0)) / 100).quantize(Decimal("0.01"))


_ENTITY_FIELDS = {
    "id",
    "entity",
    "amount",
    "currency",
    "status",
    "order_id",
    "payment_id",
    "method",
    "captured",
    "amount_refunded",
    "refund_status",
    "error_code",
    "error_description",
    "error_reason",
    "speed_processed",
    "created_at",
}


def sanitize_entity(entity: dict | None) -> dict:
    """Keep only non-sensitive fields: never card, VPA, bank, wallet, email or phone details."""
    return {k: v for k, v in (entity or {}).items() if k in _ENTITY_FIELDS}


def parse_razorpay_style_event(event_id: str, data: dict) -> WebhookEvent:
    """Normalise a Razorpay-format event body (the mock gateway uses the same format)."""
    payload = data.get("payload") or {}
    payment_entity = (payload.get("payment") or {}).get("entity")
    refund_entity = (payload.get("refund") or {}).get("entity")
    order_entity = (payload.get("order") or {}).get("entity")
    payment = refund = None
    if payment_entity:
        payment = GatewayPayment(
            provider_payment_id=payment_entity.get("id", ""),
            status=payment_entity.get("status", ""),
            amount=from_paise(payment_entity.get("amount")),
            provider_order_id=payment_entity.get("order_id") or (order_entity or {}).get("id", ""),
            currency=payment_entity.get("currency", "INR"),
            method=payment_entity.get("method") or "unknown",
            failure_reason=payment_entity.get("error_description") or "",
        )
    if refund_entity:
        refund = GatewayRefund(
            provider_refund_id=refund_entity.get("id", ""),
            provider_payment_id=refund_entity.get("payment_id", ""),
            status=refund_entity.get("status", ""),
            amount=from_paise(refund_entity.get("amount")),
        )
    return WebhookEvent(
        event_id=event_id,
        event_type=str(data.get("event", "")),
        payment=payment,
        refund=refund,
        data={
            "event": data.get("event"),
            "payment": sanitize_entity(payment_entity),
            "refund": sanitize_entity(refund_entity),
            "order": sanitize_entity(order_entity),
        },
    )
