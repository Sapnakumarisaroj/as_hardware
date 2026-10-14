from .base import *  # noqa: F401,F403
from .base import REST_FRAMEWORK

DEBUG = False
OTP_MOCK_ALLOWED = True  # tests read the code from the mock SMS outbox
OTP_LOGIN_ENABLED = False  # the launch default; the OTP tests switch it on
# Fast hashing for tests only.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# Throttling is exercised by dedicated tests; keep default rates generous.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "anon": "1000/min",
        "user": "1000/min",
        "auth": "1000/min",
    },
}
FRONTEND_URL = "http://testserver-frontend"
# Proof-of-delivery photos written by tests go to a throwaway folder.
import tempfile as _tempfile  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

PRIVATE_MEDIA_ROOT = _Path(_tempfile.gettempdir()) / "boltrun_test_private_media"
# Never call OpenStreetMap services from tests (providers are exercised with fakes).
GEOCODING_PROVIDER = "none"
# Engine tests use their own stores and zones; city service-area tests switch the restriction on.
DELIVERY_RESTRICT_TO_SERVICE_AREAS = False
ROUTING_PROVIDER = "haversine"
# Tests pin one fixed fee rule (₹40 below ₹499), whatever the developer's .env sets: their amounts were written
# for it. The shop's own policy (free from ₹2,000, base.py) is tested in orders/tests/test_free_delivery_policy.py.
from decimal import Decimal as _Decimal  # noqa: E402

DELIVERY_FEE = _Decimal("40.00")
FREE_DELIVERY_MIN_ORDER = _Decimal("499.00")
# Never use the developer's real (test-mode) payment keys from .env: tests run on the mock provider, and the
# Razorpay tests set their own fake keys.
PAYMENT_PROVIDER = "mock"
RAZORPAY_KEY_ID = ""
RAZORPAY_KEY_SECRET = ""
RAZORPAY_WEBHOOK_SECRET = ""

# WhiteNoise isn't needed under the test client (and warns when staticfiles/ is absent).
from .base import MIDDLEWARE  # noqa: E402

MIDDLEWARE = [m for m in MIDDLEWARE if m != "whitenoise.middleware.WhiteNoiseMiddleware"]

# Concurrency tests (orders/tests/test_concurrency.py) run real threads. SQLite's default
# in-memory test database uses shared-cache locking, which fails at once instead of waiting,
# so tests use a temporary file database (created and destroyed by the test runner).
from .base import DATABASES, DB_VENDOR  # noqa: E402

if DB_VENDOR == "sqlite":
    import os
    import tempfile

    DATABASES["default"]["TEST"] = {"NAME": os.path.join(tempfile.gettempdir(), f"boltrun_test_{os.getpid()}.sqlite3")}

# Semantic search is off in tests unless a test switches it on (override_settings).
SEMANTIC_EMBEDDER = "none"
CATALOG_SEARCH_BACKEND = "apps.catalog.search.KeywordSearchBackend"
# Photo search tests use a fake provider; no model is ever loaded or called.
VISION_PROVIDER = "none"
# Voice tests use fake speech providers; Whisper is never loaded.
SPEECH_STT_PROVIDER = "none"
SPEECH_TTS_PROVIDER = "none"
