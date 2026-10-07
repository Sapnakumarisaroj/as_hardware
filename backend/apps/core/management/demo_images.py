"""DEVELOPMENT / DEMO product pictures, drawn locally with Pillow (no image service).

Each demo product gets two simple labelled PNGs (a "front" card and a "specs" card) so the
storefront's gallery, thumbnails and primary-image logic can be exercised. They are clearly
marked "DEMO IMAGE" and are stored through the normal ProductImage/ImageField path, so the
same code serves real uploads from local MEDIA_ROOT (or S3/Cloudinary later).
"""

import io
import textwrap

from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFont

SIZE = 640
PALETTE = {
    "plywood-mdf-hdhmr": ((243, 232, 214), (133, 94, 46)),
    "fevicol": ((254, 243, 199), (180, 83, 9)),
    "hinges-channels-handles": ((226, 232, 240), (51, 65, 85)),
    "kitchen-systems": ((224, 242, 254), (3, 105, 161)),
    "wardrobe-bed-fittings": ((237, 233, 254), (91, 33, 182)),
    "door-locks-hardware": ((254, 226, 226), (153, 27, 27)),
    "power-tools": ((236, 238, 241), (42, 46, 53)),
    "general-hardware": ((237, 231, 225), (120, 83, 54)),
    "safety": ((220, 252, 231), (21, 128, 61)),
    "glass-door-hardware": ((207, 250, 254), (14, 116, 144)),
}
DEFAULT_COLOURS = ((236, 238, 241), (75, 82, 92))


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _render(title: str, lines: list[str], background, accent) -> bytes:
    image = Image.new("RGB", (SIZE, SIZE), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, SIZE, 56], fill=accent)
    draw.text((24, 16), "DEMO IMAGE", font=_font(22), fill=(255, 255, 255))
    y = 150
    for line in textwrap.wrap(title, width=22)[:4]:
        draw.text((40, y), line, font=_font(40), fill=accent)
        y += 52
    y += 20
    for line in lines[:5]:
        draw.text((40, y), line, font=_font(26), fill=(75, 82, 92))
        y += 36
    draw.rectangle([0, SIZE - 12, SIZE, SIZE], fill=accent)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def ensure_demo_images(product, category_slug: str, variant_names: list[str], specs: list[tuple]) -> int:
    """Create the two demo images for a product that has none. Returns how many were created."""
    from apps.catalog.models import ProductImage

    if product.images.exists():
        return 0
    background, accent = PALETTE.get(category_slug, DEFAULT_COLOURS)
    options = [n for n in variant_names if n]
    front_lines = [f"{len(options)} options: " + ", ".join(options)[:40]] if len(options) > 1 else []
    spec_lines = [f"{name}: {value} {unit}".strip() for name, value, unit in specs]
    cards = [
        (_render(product.name, front_lines, background, accent), f"{product.name} (demo image)", True),
        (
            _render("Specifications", spec_lines, (255, 255, 255), accent),
            f"{product.name} specifications (demo)",
            False,
        ),
    ]
    for position, (content, alt, primary) in enumerate(cards):
        image = ProductImage(product=product, alt_text=alt[:200], is_primary=primary, sort_order=position)
        image.image.save(f"{product.sku.lower()}-{position + 1}.png", ContentFile(content), save=False)
        image.save()
    return len(cards)
