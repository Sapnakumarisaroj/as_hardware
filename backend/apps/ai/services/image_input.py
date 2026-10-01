"""Customer photos for image search (Phase 14): check, clean, scale down. Nothing is stored.

1. Size: refused above IMAGE_SEARCH_MAX_BYTES before Pillow reads anything.
2. Content: Pillow must open *and verify* it (a renamed PDF or a truncated file fails), the format must
   be JPEG, PNG or WebP whatever the file name or content type says, and the pixel count is capped so a
   tiny file can't expand into gigabytes (decompression bomb).
3. Cleaning: the phone's rotation is applied, transparency is flattened on white, and the picture is
   re-drawn as plain RGB, which drops EXIF (GPS position, device) and anything hidden in the file.
4. Scaled down to MAX_SIDE for the model; the SHA-256 of the cleaned pixels identifies the photo for
   the analysis cache (the same photo twice → one model call).
"""

import hashlib
import io
from dataclasses import dataclass

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import status

from apps.core.exceptions import ServiceError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PIXELS = 40_000_000  # 40 MP: more than any phone camera; a bigger "image" is suspicious
MIN_SIDE = 32
MAX_SIDE = 1024


class ImageInputError(ServiceError):
    default_code = "image_invalid"
    default_detail = "That file is not a photo we can read. Use a JPEG, PNG or WebP picture."


class ImageTooLarge(ImageInputError):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_code = "image_too_large"


@dataclass(frozen=True)
class CleanImage:
    image: Image.Image  # RGB, at most MAX_SIDE on the long side, no metadata
    sha256: str
    width: int  # of the original
    height: int
    format: str
    bytes: int

    def summary(self) -> dict:
        """What is kept about the photo (in the search history): no pixels, no metadata."""
        return {
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "bytes": self.bytes,
            "fingerprint": self.sha256[:16],
        }


def max_megabytes() -> int:
    return settings.IMAGE_SEARCH_MAX_BYTES // (1024 * 1024)


def clean_image(upload) -> CleanImage:
    if upload is None:
        raise ImageInputError("Choose or take a photo first.", code="image_required")
    size = getattr(upload, "size", None) or 0
    if size > settings.IMAGE_SEARCH_MAX_BYTES:
        raise ImageTooLarge(f"The photo is too large ({max_megabytes()} MB at most).")
    if size == 0:
        raise ImageInputError("The file is empty.", code="image_empty")
    try:
        upload.seek(0)
        with Image.open(upload) as probe:
            fmt = probe.format
            width, height = probe.size
            if fmt not in ALLOWED_FORMATS:
                raise ImageInputError("Use a JPEG, PNG or WebP photo.", code="image_unsupported")
            if width * height > MAX_PIXELS:
                raise ImageInputError("The picture has too many pixels.", code="image_too_many_pixels")
            if min(width, height) < MIN_SIDE:
                raise ImageInputError("The picture is too small to recognise anything.", code="image_too_small")
            probe.verify()  # truncated or disguised files fail here; the image must be reopened afterwards
        upload.seek(0)
        with Image.open(upload) as opened:
            opened.draft("RGB", (MAX_SIDE * 2, MAX_SIDE * 2))  # JPEG: decode at a reduced size, much faster
            image = ImageOps.exif_transpose(opened)
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            clean = Image.frombytes("RGB", image.size, image.tobytes())  # pixels only: no EXIF, ICC or text chunks
    except ImageInputError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ImageInputError() from exc
    digest = hashlib.sha256(clean.tobytes() + f"{clean.size}".encode()).hexdigest()
    return CleanImage(image=clean, sha256=digest, width=width, height=height, format=fmt, bytes=size)


def jpeg_bytes(image: Image.Image, quality: int = 85) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality)
    return out.getvalue()
