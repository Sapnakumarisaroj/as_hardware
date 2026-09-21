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
    "DEFAULT_THROTTLE_RATES": {**REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "anon": "1000/min", "user": "1000/min"},
}

# WhiteNoise isn't needed under the test client (and warns when staticfiles/ is absent).
from .base import MIDDLEWARE  # noqa: E402

MIDDLEWARE = [m for m in MIDDLEWARE if m != "whitenoise.middleware.WhiteNoiseMiddleware"]
