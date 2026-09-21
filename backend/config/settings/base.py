"""Base settings shared by every environment.

All secrets and environment-specific values come from environment variables
(optionally loaded from the repository-root `.env` file). Nothing sensitive is
hardcoded here.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
REPO_ROOT = BASE_DIR.parent

env = environ.Env()
# First match wins: $ENV_FILE, backend/.env (shared hosting uploads only backend/), repo-root .env (local dev).
# Real environment variables (e.g. set in the hosting control panel) always take precedence.
for _env_file in (env.str("ENV_FILE", default=""), BASE_DIR / ".env", REPO_ROOT / ".env"):
    if _env_file and Path(_env_file).is_file():
        environ.Env.read_env(str(_env_file))
        break

APP_NAME = env("APP_NAME", default="BoltRun")
APP_VERSION = env("APP_VERSION", default="0.1.0")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
    # Local
    "apps.core",
    "apps.accounts",
]

MIDDLEWARE = [
    "apps.core.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database -----------------------------------------------------------------
# Vendor-neutral: PostgreSQL (preferred), MySQL/MariaDB (common on shared hosting)
# or SQLite (local fallback). Selected purely by DATABASE_URL, e.g.
#   postgres://user:pass@host:5432/db
#   mysql://user:pass@host:3306/db
#   sqlite:////absolute/path/db.sqlite3
_database_url = env("DATABASE_URL", default="") or f"sqlite:///{(BASE_DIR / 'db.sqlite3').as_posix()}"
DATABASES = {"default": env.db_url_config(_database_url)}
DB_VENDOR = {
    "django.db.backends.postgresql": "postgresql",
    "django.db.backends.mysql": "mysql",
    "django.db.backends.sqlite3": "sqlite",
}.get(DATABASES["default"]["ENGINE"], "other")

DATABASES["default"]["ATOMIC_REQUESTS"] = False
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60 if DB_VENDOR != "sqlite" else 0)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
if DB_VENDOR == "mysql":
    # PyMySQL is pure Python: installs on shared hosting without a C compiler.
    import pymysql

    pymysql.install_as_MySQLdb()
    DATABASES["default"].setdefault("OPTIONS", {}).update(
        {"charset": "utf8mb4", "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"}
    )
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth ---------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- I18N ---------------------------------------------------------------------
LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# --- Static / media -------------------------------------------------------------
# On shared hosting, point STATIC_ROOT/MEDIA_ROOT at web-served folders (see docs/DEPLOYMENT.md).
# Blank values in .env fall back to the defaults.
STATIC_URL = env("STATIC_URL", default="") or "static/"
STATIC_ROOT = Path(env("STATIC_ROOT", default="") or BASE_DIR / "staticfiles")
MEDIA_URL = env("MEDIA_URL", default="") or "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default="") or BASE_DIR / "media")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# --- CORS / CSRF ----------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_EXPOSE_HEADERS = ["X-Request-ID"]
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# --- DRF ------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", default="60/min"),
        "user": env("THROTTLE_USER", default="240/min"),
        "auth": env("THROTTLE_AUTH", default="10/min"),
        "ai": env("THROTTLE_AI", default="30/min"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default=SECRET_KEY),
}

SPECTACULAR_SETTINGS = {
    "TITLE": f"{APP_NAME} API",
    "DESCRIPTION": "AI-powered hardware marketplace with fast delivery.",
    "VERSION": APP_VERSION,
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/",
}

# --- Business configuration -------------------------------------------------------
FAST_DELIVERY_MAX_MINUTES = env.int("FAST_DELIVERY_MAX_MINUTES", default=60)

# --- Provider selection (implemented from Phase 8 onwards) ------------------------------
# Every external service sits behind an interface; these choose the implementation.
PAYMENT_PROVIDER = env("PAYMENT_PROVIDER", default="mock")  # mock | razorpay
WHATSAPP_PROVIDER = env("WHATSAPP_PROVIDER", default="mock")  # mock | meta
SMS_PROVIDER = env("SMS_PROVIDER", default="mock")  # mock | msg91 | twilio
MAPS_PROVIDER = env("MAPS_PROVIDER", default="osm")  # osm (Nominatim + haversine) | google
LLM_PROVIDER = env("LLM_PROVIDER", default="none")  # none | ollama | openai_compatible | anthropic
OLLAMA_BASE_URL = env("OLLAMA_BASE_URL", default="http://localhost:11434")
LLM_MODEL = env("LLM_MODEL", default="")
BACKGROUND_JOBS_MODE = env("BACKGROUND_JOBS_MODE", default="inline")  # inline | cron (DB queue)

# --- Logging --------------------------------------------------------------------
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.core.logging.RequestIDFilter"}},
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s [%(name)s] [rid=%(request_id)s] %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
    },
}
