from functools import lru_cache

from django.conf import settings

from .base import (
    MediaFile,
    MessagingError,
    MessagingProvider,
    MessagingUnavailable,
    OutgoingMessage,
    SendResult,
    mask_phone,
    to_e164,
)
from .providers import (
    OUTBOX,
    MetaWhatsAppProvider,
    MockSMSProvider,
    MockWhatsAppProvider,
    NoSMSProvider,
    NoWhatsAppProvider,
)


@lru_cache(maxsize=4)
def _whatsapp(name: str) -> MessagingProvider:
    if name == "mock":
        return MockWhatsAppProvider()
    if name == "meta":
        return MetaWhatsAppProvider(
            access_token=settings.WHATSAPP_ACCESS_TOKEN,
            phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID,
            api_version=settings.WHATSAPP_API_VERSION,
            timeout=settings.MESSAGING_TIMEOUT_SECONDS,
        )
    return NoWhatsAppProvider()  # "none" or an unknown name: a typo can't break the site


@lru_cache(maxsize=4)
def _sms(name: str) -> MessagingProvider:
    return MockSMSProvider() if name == "mock" else NoSMSProvider()


def get_whatsapp_provider() -> MessagingProvider:
    return _whatsapp(settings.WHATSAPP_PROVIDER)


def get_sms_provider() -> MessagingProvider:
    return _sms(settings.SMS_PROVIDER)


def reset_messaging_providers() -> None:
    _whatsapp.cache_clear()
    _sms.cache_clear()


__all__ = [
    "OUTBOX",
    "MediaFile",
    "MessagingError",
    "MessagingProvider",
    "MessagingUnavailable",
    "OutgoingMessage",
    "SendResult",
    "get_sms_provider",
    "get_whatsapp_provider",
    "mask_phone",
    "reset_messaging_providers",
    "to_e164",
]
