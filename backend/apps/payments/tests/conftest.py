"""Test doubles for the payment gateway.

`gateway` swaps the configured provider for `FakeGateway`, a scriptable stand-in named "razorpay":
tests decide what the gateway reports (verification, attempts on an order, refund outcomes,
outages) and can inspect every call made to it. Webhooks are signed like the mock gateway's.
"""

import hashlib
import itertools
from decimal import Decimal

import pytest

from apps.core.testing import create_address, create_product, create_store
from integrations.payments import GatewayPayment, PaymentIntent, RefundResult, VerificationResult
from integrations.payments.mock import MockPaymentProvider

_seq = itertools.count(1)


class FakeGateway(MockPaymentProvider):
    name = "razorpay"
    is_test_mode = True

    def __init__(self):
        self.verify_result: VerificationResult | Exception | None = None
        self.order_payments: dict[str, list[GatewayPayment] | Exception] = {}
        self.refund_outcomes: list[RefundResult | Exception] = []
        self.refund_calls: list[tuple[str, Decimal, str]] = []
        self.fetch_refund_result: RefundResult | None = None
        self.captures: list[str] = []
        self._refunds_by_reference: dict[str, RefundResult] = {}

    def create_payment(self, *, reference, amount, currency="INR", customer=None):
        oid = f"order_fake_{next(_seq)}"
        return PaymentIntent(
            provider=self.name,
            provider_order_id=oid,
            amount=amount,
            currency=currency,
            client_payload={"razorpay": True, "key_id": "rzp_test_fake", "order_id": oid},
        )

    def verify_payment(self, *, provider_order_id, payload, expected_amount=None):
        result = self.verify_result or VerificationResult(
            success=True, provider_payment_id=f"pay_fake_{next(_seq)}", method="upi", amount=expected_amount
        )
        if isinstance(result, Exception):
            raise result
        return result

    def fetch_order_payments(self, *, provider_order_id):
        result = self.order_payments.get(provider_order_id, [])
        if isinstance(result, Exception):
            raise result
        return result

    def capture(self, *, provider_payment_id, amount, currency="INR"):
        self.captures.append(provider_payment_id)
        return GatewayPayment(provider_payment_id=provider_payment_id, status="captured", amount=amount)

    def refund(self, *, provider_payment_id, amount, reference):
        self.refund_calls.append((provider_payment_id, amount, reference))
        if reference in self._refunds_by_reference:  # idempotent, like the real gateway lookup
            return self._refunds_by_reference[reference]
        outcome = (
            self.refund_outcomes.pop(0)
            if self.refund_outcomes
            else RefundResult(True, f"rfnd_{hashlib.sha256(reference.encode()).hexdigest()[:10]}", "processed")
        )
        if isinstance(outcome, Exception):
            raise outcome
        self._refunds_by_reference[reference] = outcome
        return outcome

    def fetch_refund(self, *, provider_payment_id, provider_refund_id):
        return self.fetch_refund_result or RefundResult(True, provider_refund_id, "processed")


@pytest.fixture
def gateway(settings, monkeypatch):
    settings.PAYMENT_PROVIDER = "razorpay"
    fake = FakeGateway()
    for module in (
        "integrations.payments",
        "apps.payments.services",
        "apps.payments.refunds",
        "apps.orders.services",
    ):
        monkeypatch.setattr(f"{module}.get_payment_provider", lambda name=None: fake)
    return fake


@pytest.fixture
def shop(user):
    store = create_store()
    _, tape = create_product(name="PTFE Tape", price="70.00", mrp="100.00", stock=50, store=store, gst_rate="5.00")
    _, drill = create_product(name="Drill", price="3000.00", mrp="3500.00", stock=10, store=store)
    return {"store": store, "tape": tape, "drill": drill, "address": create_address(user)}
