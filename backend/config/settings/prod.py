from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import PAYMENT_PROVIDER, env

DEBUG = False

# Mock payments must never silently run in production.
if PAYMENT_PROVIDER == "mock" and not env.bool("ALLOW_MOCK_PAYMENTS_IN_PROD", default=False):
    raise ImproperlyConfigured(
        "PAYMENT_PROVIDER=mock in production. Set PAYMENT_PROVIDER=razorpay (COD works regardless), "
        "or explicitly set ALLOW_MOCK_PAYMENTS_IN_PROD=true for a staging site."
    )

# Shared hosting has no Redis: a DB cache keeps throttling consistent across Passenger processes.
# One-time setup: `python manage.py createcachetable`.
CACHES = {
    "default": {
        "BACKEND": env("CACHE_BACKEND", default="django.core.cache.backends.db.DatabaseCache"),
        "LOCATION": env("CACHE_LOCATION", default="django_cache"),
    }
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@example.com")
