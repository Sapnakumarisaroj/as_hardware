"""`upload_to` callables that store files under random, non-guessable names.

Plain module-level functions (not closures) so migrations can serialize them.
"""

import os
import uuid

from django.utils import timezone

ALLOWED_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp"]


def _random_path(prefix: str, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"{prefix}/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


def product_image_path(instance, filename: str) -> str:
    return _random_path("products", filename)


def category_image_path(instance, filename: str) -> str:
    return _random_path("categories", filename)


def brand_logo_path(instance, filename: str) -> str:
    return _random_path("brands", filename)


def avatar_path(instance, filename: str) -> str:
    return _random_path("avatars", filename)


def delivery_proof_path(instance, filename: str) -> str:
    return _random_path("delivery-proofs", filename)
