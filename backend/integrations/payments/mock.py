"""Development-only gateway. Moves no money; outcomes are chosen explicitly by the caller.
Production settings refuse to start with this provider (see config/settings/prod.py)."""

import hashlib
import hmac
import secrets
from decimal import Decimal

from django.conf import settings

from .base import PaymentIntent, PaymentProvider, RefundResult, VerificationResult


def _sign(provider_order_id: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), provider_order_id.encode(), hashlib.sha256).hexdigest()


class MockPaymentProvider(PaymentProvider):
    name = "mock"
    is_test_mode = True

    def create_payment(self, *, reference: str, amount: Decimal, currency: str = "INR") -> PaymentIntent:
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

    def verify_payment(self, *, provider_order_id: str, payload: dict) -> VerificationResult:
        # The signature proves the payload refers to an intent this server created.
        if not hmac.compare_digest(str(payload.get("mock_signature", "")), _sign(provider_order_id)):
            return VerificationResult(success=False, failure_reason="Invalid mock signature.")
        if payload.get("mock_outcome") != "success":
            return VerificationResult(success=False, failure_reason="Mock payment declined.")
        return VerificationResult(
            success=True, provider_payment_id=f"mock_pay_{secrets.token_hex(8)}", method=payload.get("method", "upi")
        )

    def refund(self, *, provider_payment_id: str, amount: Decimal) -> RefundResult:
        return RefundResult(success=True, provider_refund_id=f"mock_rfnd_{secrets.token_hex(8)}")
