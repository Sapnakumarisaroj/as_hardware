from .base import *  # noqa: F401,F403
from .base import REST_FRAMEWORK

DEBUG = False
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
ROUTING_PROVIDER = "haversine"

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
