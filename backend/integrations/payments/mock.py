"""Development-only gateway. Moves no money; outcomes are chosen explicitly by the caller.
Production settings refuse to start with this provider (see config/settings/prod.py).

Signatures are real HMACs (keyed by SECRET_KEY), so forged payloads fail exactly as with a
real gateway. Webhooks use the Razorpay body format, signed with `sign_mock_webhook`.
The mock keeps no state: it has nothing to reconcile, and refunds complete immediately.
"""

import hashlib
import hmac
import json
import secrets
from decimal import Decimal

from django.conf import settings

from .base import (
    GatewayPayment,
    InvalidSignature,
    PaymentIntent,
    PaymentProvider,
    RefundResult,
    VerificationResult,
    WebhookEvent,
    parse_razorpay_style_event,
)

WEBHOOK_SIGNATURE_HEADER = "X-Mock-Signature"


def _sign(provider_order_id: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), provider_order_id.encode(), hashlib.sha256).hexdigest()


def sign_mock_webhook(body: bytes) -> str:
    key = f"{settings.SECRET_KEY}:mock-webhook".encode()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def mock_webhook_body(event: str, **entities) -> bytes:
    """Build a Razorpay-format event body, e.g. mock_webhook_body("payment.captured", payment={...})."""
    payload = {name: {"entity": entity} for name, entity in entities.items()}
    return json.dumps({"entity": "event", "event": event, "payload": payload}).encode()


class MockPaymentProvider(PaymentProvider):
    name = "mock"
    is_test_mode = True

    def create_payment(
        self, *, reference: str, amount: Decimal, currency: str = "INR", customer: dict | None = None
    ) -> PaymentIntent:
        provider_order_id = f"mock_order_{secrets.token_hex(8)}"
        return PaymentIntent(
            provider=self.name,
            provider_order_id=provider_order_id,
            amount=amount,
            currency=currency,
            client_payload={
                "mock": True,
                "notice": "Development mock payment. No real money is charged.",
                "mock_signature": _sign(provider_order_id),
            },
        )

    def verify_payment(
        self, *, provider_order_id: str, payload: dict, expected_amount: Decimal | None = None
    ) -> VerificationResult:
        # The signature proves the payload refers to an intent this server created.
        if not hmac.compare_digest(str(payload.get("mock_signature", "")), _sign(provider_order_id)):
            return VerificationResult(success=False, failure_reason="Invalid mock signature.")
        outcome = payload.get("mock_outcome")
        if outcome == "cancelled":
            return VerificationResult(success=False, cancelled=True, failure_reason="Payment cancelled by customer.")
        if outcome == "pending":
            return VerificationResult(success=False, pending=True)
        if outcome != "success":
            return VerificationResult(success=False, failure_reason="Mock payment declined.")
        return VerificationResult(
            success=True,
            provider_payment_id=f"mock_pay_{secrets.token_hex(8)}",
            method=payload.get("method", "upi"),
            amount=expected_amount,
        )

    def fetch_order_payments(self, *, provider_order_id: str) -> list[GatewayPayment]:
        return []

    def capture(self, *, provider_payment_id: str, amount: Decimal, currency: str = "INR") -> GatewayPayment:
        return GatewayPayment(provider_payment_id=provider_payment_id, status="captured", amount=amount)

    def refund(self, *, provider_payment_id: str, amount: Decimal, reference: str) -> RefundResult:
        # Deterministic id per reference: repeating the call returns the same refund.
        refund_id = "mock_rfnd_" + hashlib.sha256(reference.encode()).hexdigest()[:16]
        return RefundResult(success=True, provider_refund_id=refund_id, status="processed")

    def fetch_refund(self, *, provider_payment_id: str, provider_refund_id: str) -> RefundResult:
        return RefundResult(success=True, provider_refund_id=provider_refund_id, status="processed")

    def parse_webhook(self, *, body: bytes, headers) -> WebhookEvent:
        signature = headers.get(WEBHOOK_SIGNATURE_HEADER, "")
        if not signature or not hmac.compare_digest(signature, sign_mock_webhook(body)):
            raise InvalidSignature("Invalid mock webhook signature.")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise InvalidSignature("Webhook body is not JSON.") from exc
        event_id = headers.get("X-Mock-Event-Id") or hashlib.sha256(body).hexdigest()
        return parse_razorpay_style_event(event_id, data)
