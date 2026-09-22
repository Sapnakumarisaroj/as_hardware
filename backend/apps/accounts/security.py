"""Per-account login failure limiting (complements DRF's per-IP `auth` throttle).

After LOGIN_MAX_FAILURES failed attempts for one email within LOGIN_LOCKOUT_SECONDS, further
attempts for that email are refused until the window expires. Counters live in Django's
cache (DB cache in production — no Redis needed). Only a hash of the email is used as key.
"""

import hashlib

from django.conf import settings
from django.core.cache import cache


def _key(email: str) -> str:
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]
    return f"login-fail:{digest}"


def is_locked_out(email: str) -> bool:
    return cache.get(_key(email), 0) >= settings.LOGIN_MAX_FAILURES


def register_failure(email: str) -> None:
    key = _key(email)
    try:
        cache.incr(key)
    except ValueError:  # key missing
        cache.set(key, 1, timeout=settings.LOGIN_LOCKOUT_SECONDS)


def clear_failures(email: str) -> None:
    cache.delete(_key(email))
