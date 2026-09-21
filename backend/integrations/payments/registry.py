from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import PaymentProvider
from .mock import MockPaymentProvider


def get_payment_provider(name: str | None = None) -> PaymentProvider:
    name = name or settings.PAYMENT_PROVIDER
    if name == "mock":
        return MockPaymentProvider()
    if name == "razorpay":
        # Optional production gateway; implemented in Phase 8 (needs RAZORPAY_* credentials).
        raise ImproperlyConfigured("The Razorpay provider is not implemented yet (Phase 8). Use PAYMENT_PROVIDER=mock.")
    raise ImproperlyConfigured(f"Unknown PAYMENT_PROVIDER '{name}'.")
