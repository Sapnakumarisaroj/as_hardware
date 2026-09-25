from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import PaymentProvider
from .mock import MockPaymentProvider

ONLINE_PROVIDERS = ("mock", "razorpay")


def get_payment_provider(name: str | None = None) -> PaymentProvider:
    """The configured gateway, or a named one (existing payments keep the provider that created them)."""
    name = name or settings.PAYMENT_PROVIDER
    if name == "mock":
        return MockPaymentProvider()
    if name == "razorpay":
        from .razorpay import RazorpayPaymentProvider

        return RazorpayPaymentProvider()
    raise ImproperlyConfigured(f"Unknown PAYMENT_PROVIDER '{name}'.")
