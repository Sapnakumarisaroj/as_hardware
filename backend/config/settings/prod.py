from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import (
    ALLOWED_HOSTS,
    DB_VENDOR,
    PAYMENT_PROVIDER,
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET,
    SECRET_KEY,
    SPECTACULAR_SETTINGS,
    env,
)

DEBUG = False  # never read from the environment in production
OTP_MOCK_ALLOWED = False  # a mock SMS never "sends" a sign-in code in production

# A short, example or Django-generated "insecure" key signs sessions, JWTs, reset links and delivery codes.
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("django-insecure") or "change-me" in SECRET_KEY.lower():
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is too weak for production: use at least 50 random characters "
        '(python -c "import secrets; print(secrets.token_urlsafe(64))").'
    )
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set DJANGO_ALLOWED_HOSTS to the site's own host names (no '*') in production.")
# A missing DATABASE_URL would otherwise fall back to a SQLite file inside the app (lost with the container).
# ALLOW_SQLITE_IN_PROD is only for steps that never touch the shop's data, e.g. collectstatic in the image build.
if DB_VENDOR not in ("postgresql", "mysql") and not env.bool("ALLOW_SQLITE_IN_PROD", default=False):
    raise ImproperlyConfigured(
        "Production needs DATABASE_URL=postgres://… (or mysql://…); SQLite is refused. On the VPS it is set by "
        "docker-compose.prod.yml from POSTGRES_* in .env."
    )

# Mock payments must never silently run in production.
if PAYMENT_PROVIDER == "mock" and not env.bool("ALLOW_MOCK_PAYMENTS_IN_PROD", default=False):
    raise ImproperlyConfigured(
        "PAYMENT_PROVIDER=mock in production. Set PAYMENT_PROVIDER=razorpay, or PAYMENT_PROVIDER=none for a "
        "cash-on-delivery-only shop; ALLOW_MOCK_PAYMENTS_IN_PROD=true is only for a staging site (anyone could "
        "confirm an online order without paying)."
    )
if PAYMENT_PROVIDER == "razorpay" and not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET):
    raise ImproperlyConfigured(
        "PAYMENT_PROVIDER=razorpay needs RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET."
    )

# Shared hosting has no Redis: a DB cache keeps throttling consistent across Passenger processes.
# One-time setup: `python manage.py createcachetable`.
CACHES = {
    "default": {
        "BACKEND": env("CACHE_BACKEND", default="django.core.cache.backends.db.DatabaseCache"),
        "LOCATION": env("CACHE_LOCATION", default="django_cache"),
    }
}

# The schema lists every staff and rider endpoint: administrators only in production.
SPECTACULAR_SETTINGS = {**SPECTACULAR_SETTINGS, "SERVE_PERMISSIONS": ["apps.core.permissions.IsAdminRole"]}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
# Preload/subdomains commit every subdomain to HTTPS for a long time: switch off if one still serves plain HTTP.
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=True)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True  # only the Django admin uses CSRF, through its form token
X_FRAME_OPTIONS = "DENY"

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
