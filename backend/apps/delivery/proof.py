"""Proof-of-delivery photos (Phase 10).

Uploads are re-encoded before they are stored: the file is opened with Pillow (so it really is
an image), EXIF data is dropped (phones embed GPS position and device details), the picture is
scaled down and saved as JPEG under a random name in private storage (apps.core.storage).
"""

import io

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.core.exceptions import ServiceError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_SIDE = 1600
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ProofError(ServiceError):
    default_code = "proof_invalid"


def clean_photo(upload) -> ContentFile:
    if upload is None:
        raise ProofError("Choose a photo to upload.", code="proof_required")
    if upload.size > MAX_UPLOAD_BYTES:
        raise ProofError("The photo is too large (8 MB at most).", code="proof_too_large")
    try:
        upload.seek(0)
        image = Image.open(upload)
        image.verify()  # detects truncated or disguised files; the image must be reopened afterwards
        upload.seek(0)
        image = Image.open(upload)
        if image.format not in ALLOWED_FORMATS:
            raise ProofError("Upload a JPEG, PNG or WebP photo.")
        image = ImageOps.exif_transpose(image)  # keep the orientation, lose the metadata
        image = image.convert("RGB")
    except ProofError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ProofError("That file is not a photo we can read. Upload a JPEG, PNG or WebP picture.") from exc
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=82, optimize=True)
    return ContentFile(out.getvalue(), name="proof.jpg")
