"""Base settings shared by every environment.

All secrets and environment-specific values come from environment variables
(optionally loaded from the repository-root `.env` file). Nothing sensitive is
hardcoded here.
"""

from datetime import timedelta
from decimal import Decimal
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
    "apps.catalog",
    "apps.stores",
    "apps.inventory",
    "apps.offers",
    "apps.carts",
    "apps.orders",
    "apps.payments",
    "apps.delivery",
    "apps.reviews",
    "apps.notifications",
    "apps.support",
    "apps.ai",
    "apps.dashboard",
    "apps.analytics",
    "apps.loyalty",
    "apps.shopping",
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
elif DB_VENDOR == "sqlite":
    # SQLite ignores SELECT … FOR UPDATE and locks the whole file instead. IMMEDIATE makes every
    # transaction take the write lock up front, so concurrent writers wait (up to `timeout`
    # seconds) instead of failing with "database is locked" halfway through (Phase 7).
    DATABASES["default"].setdefault("OPTIONS", {}).update({"transaction_mode": "IMMEDIATE", "timeout": 20})
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
    {"NAME": "apps.accounts.password_validation.LetterAndDigitValidator"},
]
# Password-reset links expire after this many seconds and become invalid once used
# (Django's token embeds the password hash, so a successful reset voids it).
PASSWORD_RESET_TIMEOUT = env.int("PASSWORD_RESET_TIMEOUT", default=3600)
LOGIN_MAX_FAILURES = env.int("LOGIN_MAX_FAILURES", default=5)
LOGIN_LOCKOUT_SECONDS = env.int("LOGIN_LOCKOUT_SECONDS", default=900)
# Public URL of the SPA, used to build links in emails (password reset).
FRONTEND_URL = (env("FRONTEND_URL", default="") or "http://localhost:5173").rstrip("/")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="") or "no-reply@localhost"

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
# Files that must NOT be web-served (proof-of-delivery photos). Keep this folder outside the
# document root; the API streams these files only to people allowed to see them.
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", default="") or BASE_DIR / "private_media")
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
        "apps.accounts.authentication.JWTAuthentication",
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
        "image_search": env("THROTTLE_IMAGE_SEARCH", default="10/min"),
        "voice": env("THROTTLE_VOICE", default="30/min"),
        "voice_audio": env("THROTTLE_VOICE_AUDIO", default="12/min"),
        "compatibility": env("THROTTLE_COMPATIBILITY", default="60/min"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "TOKEN_REFRESH_SERIALIZER": "apps.accounts.authentication.TokenRefreshSerializer",
    "AUTH_HEADER_TYPES": ("Bearer",),
    # Blank in .env must fall back too (an empty HMAC key would break every token).
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default="") or SECRET_KEY,
}

SPECTACULAR_SETTINGS = {
    "TITLE": f"{APP_NAME} API",
    "DESCRIPTION": "AI-powered hardware marketplace with fast delivery.",
    "VERSION": APP_VERSION,
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/",
    "ENUM_NAME_OVERRIDES": {
        "OrderStatusEnum": "apps.orders.models.OrderStatus",
        "OrderPaymentStatusEnum": "apps.orders.models.PaymentStatus",
        "PaymentRecordStatusEnum": "apps.payments.models.Payment.Status",
        "ReviewStatusEnum": "apps.reviews.models.Review.Status",
        "PreferredLanguageEnum": "apps.accounts.models.CustomerProfile.Language",
        "AILanguageEnum": "apps.ai.quantity_views.LANGUAGES",
        "NotificationChannelEnum": "apps.notifications.models.Channel",
        "MessageChannelEnum": "apps.notifications.serializers.MESSAGE_CHANNELS",
    },
}

# --- Business configuration -------------------------------------------------------
# Fast delivery is *offered* only when the calculated ETA is at most this (zones may set a lower/higher
# cutoff). It is a threshold, not a promise: customers see the calculated minutes.
FAST_DELIVERY_MAX_MINUTES = env.int("FAST_DELIVERY_MAX_MINUTES", default=60)
# Default fee rule; delivery zones can override both (Phase 9).
DELIVERY_FEE = Decimal(env.str("DELIVERY_FEE", default="") or "40.00")
FREE_DELIVERY_MIN_ORDER = Decimal(env.str("FREE_DELIVERY_MIN_ORDER", default="") or "499.00")

# --- Delivery ETA engine (Phase 9, apps/delivery/eta.py) ---------------------------------
DELIVERY_AVG_SPEED_KMPH = env.float("DELIVERY_AVG_SPEED_KMPH", default=18.0)  # two-wheeler in city traffic
ROAD_DISTANCE_FACTOR = env.float("ROAD_DISTANCE_FACTOR", default=1.35)  # road km per straight-line km
DELIVERY_HANDOVER_MINUTES = env.int("DELIVERY_HANDOVER_MINUTES", default=4)  # parking, stairs, OTP
# A rider who is out on a delivery is expected back after about this long (queue estimate).
DELIVERY_RIDER_TURNAROUND_MINUTES = env.int("DELIVERY_RIDER_TURNAROUND_MINUTES", default=35)
# Standard (non-fast) deliveries are batched: extra time before dispatch, and the window shown.
STANDARD_DISPATCH_DELAY_MINUTES = env.int("STANDARD_DISPATCH_DELAY_MINUTES", default=120)
STANDARD_WINDOW_MINUTES = env.int("STANDARD_WINDOW_MINUTES", default=120)
FAST_WINDOW_MINUTES = env.int("FAST_WINDOW_MINUTES", default=15)
# When address and store share a PIN code but coordinates are missing, assume this distance.
SAME_PIN_DISTANCE_KM = env.float("SAME_PIN_DISTANCE_KM", default=2.0)
# Allow one order to ship from several stores when no single store has everything.
SPLIT_FULFILLMENT_ENABLED = env.bool("SPLIT_FULFILLMENT_ENABLED", default=True)
# A partner based elsewhere may take a shipment if currently within this distance of the store.
DELIVERY_PARTNER_PICKUP_RADIUS_KM = env.float("DELIVERY_PARTNER_PICKUP_RADIUS_KM", default=3.0)
MAX_SHIPMENTS_PER_ORDER = env.int("MAX_SHIPMENTS_PER_ORDER", default=3)

# --- Delivery partner workflow (Phase 10, apps/delivery/workflow.py) -----------------------
# The customer's delivery code: valid this long, locked after this many wrong tries, and a new
# one can be requested at most this often.
DELIVERY_OTP_TTL_MINUTES = env.int("DELIVERY_OTP_TTL_MINUTES", default=30)
DELIVERY_OTP_MAX_ATTEMPTS = env.int("DELIVERY_OTP_MAX_ATTEMPTS", default=5)
DELIVERY_OTP_RESEND_SECONDS = env.int("DELIVERY_OTP_RESEND_SECONDS", default=60)
# A photo is required to complete a delivery (the OTP is always required).
DELIVERY_PROOF_REQUIRED = env.bool("DELIVERY_PROOF_REQUIRED", default=False)
# What a partner earns per completed job: base + per km of the store → customer route.
DELIVERY_EARNING_BASE = Decimal(env.str("DELIVERY_EARNING_BASE", default="") or "25.00")
DELIVERY_EARNING_PER_KM = Decimal(env.str("DELIVERY_EARNING_PER_KM", default="") or "6.00")
DELIVERY_EARNING_FAILED_ATTEMPT = Decimal(env.str("DELIVERY_EARNING_FAILED_ATTEMPT", default="") or "0.00")

# --- Maps (Phase 9, integrations/maps). Offline by default; OpenStreetMap services are opt-in. ---
GEOCODING_PROVIDER = env("GEOCODING_PROVIDER", default="none")  # none | nominatim
ROUTING_PROVIDER = env("ROUTING_PROVIDER", default="haversine")  # haversine | osrm
NOMINATIM_BASE_URL = env("NOMINATIM_BASE_URL", default="https://nominatim.openstreetmap.org")
NOMINATIM_USER_AGENT = env("NOMINATIM_USER_AGENT", default="") or f"{APP_NAME}/0.1 (delivery ETA)"
OSRM_BASE_URL = env("OSRM_BASE_URL", default="https://router.project-osrm.org")
MAPS_TIMEOUT_SECONDS = env.float("MAPS_TIMEOUT_SECONDS", default=4.0)
ROUTE_CACHE_SECONDS = env.int("ROUTE_CACHE_SECONDS", default=24 * 3600)
# Days after delivery during which a customer may request a return (Phase 7).
RETURN_WINDOW_DAYS = env.int("RETURN_WINDOW_DAYS", default=7)

# --- Provider selection (implemented from Phase 8 onwards) ------------------------------
# Every external service sits behind an interface; these choose the implementation.
PAYMENT_PROVIDER = env("PAYMENT_PROVIDER", default="mock")  # mock | razorpay
# Razorpay (Phase 8). The key id is public (sent to Checkout); the key and webhook secrets never leave the server.
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", default="")
RAZORPAY_API_BASE = env("RAZORPAY_API_BASE", default="https://api.razorpay.com/v1")
# Unpaid online orders are cancelled (stock released) after this many minutes, once the gateway
# confirms nothing was paid. `run_jobs` also asks the gateway about attempts left open this long.
PAYMENT_EXPIRY_MINUTES = env.int("PAYMENT_EXPIRY_MINUTES", default=30)
PAYMENT_RECONCILE_AFTER_MINUTES = env.int("PAYMENT_RECONCILE_AFTER_MINUTES", default=10)
# Notifications (Phase 23). WhatsApp: mock (records, sends nothing) | meta (WhatsApp Cloud API, needs the
# owner's WhatsApp Business account, approved templates; Meta bills per conversation) | none.
# SMS: mock | none (a paid gateway is one provider class in integrations/messaging; none ships).
WHATSAPP_PROVIDER = env("WHATSAPP_PROVIDER", default="mock")
SMS_PROVIDER = env("SMS_PROVIDER", default="mock")
WHATSAPP_ACCESS_TOKEN = env("WHATSAPP_ACCESS_TOKEN", default="")
WHATSAPP_PHONE_NUMBER_ID = env("WHATSAPP_PHONE_NUMBER_ID", default="")
WHATSAPP_API_VERSION = env("WHATSAPP_API_VERSION", default="v21.0")
WHATSAPP_APP_SECRET = env("WHATSAPP_APP_SECRET", default="")  # checks the signature of delivery receipts
WHATSAPP_VERIFY_TOKEN = env("WHATSAPP_VERIFY_TOKEN", default="")  # Meta's one-time webhook verification
MESSAGING_TIMEOUT_SECONDS = env.float("MESSAGING_TIMEOUT_SECONDS", default=10)
PHONE_COUNTRY_CODE = env("PHONE_COUNTRY_CODE", default="91")  # stored phones are 10 digits
# Active orders this many minutes past their estimated delivery get one "running late" message.
DELIVERY_DELAY_NOTICE_MINUTES = env.int("DELIVERY_DELAY_NOTICE_MINUTES", default=15)
LLM_PROVIDER = env("LLM_PROVIDER", default="none")  # none | ollama | openai_compatible | anthropic
OLLAMA_BASE_URL = env("OLLAMA_BASE_URL", default="http://localhost:11434")
OLLAMA_KEEP_ALIVE = env("OLLAMA_KEEP_ALIVE", default="30m")  # keep the model loaded between questions
LLM_MODEL = env("LLM_MODEL", default="")
OPENAI_COMPATIBLE_BASE_URL = env("OPENAI_COMPATIBLE_BASE_URL", default="")
OPENAI_COMPATIBLE_API_KEY = env("OPENAI_COMPATIBLE_API_KEY", default="")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
# A slow local model must never hang a request: after this the assistant answers in basic mode.
LLM_TIMEOUT_SECONDS = env.float("LLM_TIMEOUT_SECONDS", default=45)
AI_ASSISTANT_MAX_PRODUCTS = env.int("AI_ASSISTANT_MAX_PRODUCTS", default=6)
BACKGROUND_JOBS_MODE = env("BACKGROUND_JOBS_MODE", default="inline")  # inline | cron (DB queue)
# Product search backend (dotted path). The portable keyword backend works on every database;
# Phase 13 adds a semantic/hybrid backend with the same interface.
CATALOG_SEARCH_BACKEND = env(
    "CATALOG_SEARCH_BACKEND", default="apps.catalog.semantic.backend.HybridSearchBackend"
)  # hybrid falls back to the plain KeywordSearchBackend whenever the semantic parts can't run
# Semantic search (Phase 13): none | hashing | sentence_transformers. `hashing` needs nothing extra;
# `sentence_transformers` needs requirements/semantic.txt and a one-time model download.
SEMANTIC_EMBEDDER = env("SEMANTIC_EMBEDDER", default="hashing")
SEMANTIC_MODEL = env("SEMANTIC_MODEL", default="paraphrase-multilingual-MiniLM-L12-v2")
SEMANTIC_MODEL_LOCAL_ONLY = env.bool("SEMANTIC_MODEL_LOCAL_ONLY", default=False)  # never download at runtime
# Photo search (Phase 14): none | clip (local open-source CLIP, needs requirements/semantic.txt) | ollama |
# openai_compatible | anthropic. Off by default like the LLM; photos are checked, analysed and thrown away.
VISION_PROVIDER = env("VISION_PROVIDER", default="none")
VISION_MODEL = env("VISION_MODEL", default="")  # clip: clip-ViT-B-32 · ollama: qwen2.5vl:3b · anthropic: haiku
VISION_MODEL_LOCAL_ONLY = env.bool("VISION_MODEL_LOCAL_ONLY", default=False)  # clip: never download at runtime
VISION_TIMEOUT_SECONDS = env.float("VISION_TIMEOUT_SECONDS", default=60)
IMAGE_SEARCH_MAX_BYTES = env.int("IMAGE_SEARCH_MAX_BYTES", default=8 * 1024 * 1024)
IMAGE_SEARCH_MAX_PRODUCTS = env.int("IMAGE_SEARCH_MAX_PRODUCTS", default=8)
IMAGE_SEARCH_CACHE_SECONDS = env.int("IMAGE_SEARCH_CACHE_SECONDS", default=24 * 3600)  # same photo → same analysis
# Voice shopping (Phase 18). The browser listens and speaks by default (free, nothing installed); a server
# provider is a fallback for browsers without speech recognition. STT: none | faster_whisper (local open-source
# Whisper, requirements/speech.txt, VPS) | openai_compatible. TTS: none | openai_compatible.
SPEECH_STT_PROVIDER = env("SPEECH_STT_PROVIDER", default="none")
SPEECH_STT_MODEL = env("SPEECH_STT_MODEL", default="")  # faster_whisper: small (default) | base · API: whisper-1
SPEECH_TTS_PROVIDER = env("SPEECH_TTS_PROVIDER", default="none")
SPEECH_TTS_MODEL = env("SPEECH_TTS_MODEL", default="")
SPEECH_TTS_VOICE = env("SPEECH_TTS_VOICE", default="alloy")
SPEECH_TTS_VOICE_HI = env("SPEECH_TTS_VOICE_HI", default="") or SPEECH_TTS_VOICE
SPEECH_BASE_URL = env("SPEECH_BASE_URL", default="")  # blank: OPENAI_COMPATIBLE_BASE_URL
SPEECH_API_KEY = env("SPEECH_API_KEY", default="")  # blank: OPENAI_COMPATIBLE_API_KEY
SPEECH_MODEL_LOCAL_ONLY = env.bool("SPEECH_MODEL_LOCAL_ONLY", default=False)  # faster_whisper: never download
SPEECH_TIMEOUT_SECONDS = env.float("SPEECH_TIMEOUT_SECONDS", default=30)
VOICE_MAX_AUDIO_BYTES = env.int("VOICE_MAX_AUDIO_BYTES", default=2 * 1024 * 1024)
VOICE_MAX_AUDIO_SECONDS = env.int("VOICE_MAX_AUDIO_SECONDS", default=20)
VOICE_MAX_SPEAK_CHARS = env.int("VOICE_MAX_SPEAK_CHARS", default=400)
QUANTITY_PACK_RULE = env("QUANTITY_PACK_RULE", default="lowest_cost")  # lowest_cost | fewest_packs (Phase 20)
VOICE_MAX_LINES = env.int("VOICE_MAX_LINES", default=5)  # items in one spoken order ("cement and pipes and …")

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
