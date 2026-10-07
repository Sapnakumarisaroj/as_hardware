from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import env

# A server's .env says DJANGO_ENV=production: refuse the development settings there (DEBUG would default to on,
# and `seed_demo_data` would run), e.g. a `python manage.py …` without DJANGO_SETTINGS_MODULE=config.settings.prod.
if env("DJANGO_ENV", default="development").lower() == "production":
    raise ImproperlyConfigured(
        "DJANGO_ENV=production but the development settings were loaded. "
        "Set DJANGO_SETTINGS_MODULE=config.settings.prod."
    )

DEBUG = env.bool("DJANGO_DEBUG", default=True)
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:5173", "http://127.0.0.1:5173"])
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
