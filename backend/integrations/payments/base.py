"""Payment gateway interface. Business code depends only on this, never on a vendor SDK."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class PaymentIntent:
    provider: str
    provider_order_id: str
    amount: Decimal
    currency: str
    # Public data the frontend needs to open the checkout widget. Never secrets.
    client_payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    provider_payment_id: str | None = None
    method: str = "unknown"
    failure_reason: str = ""
    # The customer closed/abandoned the payment (not a decline). They may try again.
    cancelled: bool = False


@dataclass(frozen=True)
class RefundResult:
    success: bool
    provider_refund_id: str | None = None
    failure_reason: str = ""


class PaymentProvider(ABC):
    name: str
    is_test_mode: bool = False

    @abstractmethod
    def create_payment(self, *, reference: str, amount: Decimal, currency: str = "INR") -> PaymentIntent: ...

    @abstractmethod
    def verify_payment(self, *, provider_order_id: str, payload: dict) -> VerificationResult: ...

    @abstractmethod
    def refund(self, *, provider_payment_id: str, amount: Decimal) -> RefundResult: ...
