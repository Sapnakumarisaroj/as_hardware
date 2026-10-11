"""Attach product pictures from a folder, listed in a mapping sheet (CSV or .xlsx), one row per picture.

    python manage.py import_product_images map.csv --root ../assets/as-hardware-images            # dry run
    python manage.py import_product_images map.csv --root ../assets/as-hardware-images --commit   # save

Columns: product_sku (required), file (path under --root, required), variant_sku, is_primary (yes/no),
alt_text, source_type (default "unverified"), image_type (photo/illustration), source_url, licence.

Rules:
- Safe to run again: a picture whose bytes are already one of that product's pictures is skipped.
- The same picture listed for two different products is refused (one of the matches is wrong).
- Files must be inside --root; nothing is downloaded.
- Pictures go through `services.add_product_image` (size/extension checks, the 12-picture limit, a single
  primary picture, and no unverified picture on a live product). All or nothing: one error saves nothing.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files import File
from django.db import transaction

from apps.core.exceptions import ServiceError

from . import services
from .importer import Table, _bool, _CellError
from .models import Product, ProductImage, ProductVariant, normalize_sku

COLUMNS = (
    "product_sku", "file", "variant_sku", "is_primary", "alt_text", "source_type", "image_type", "source_url",
    "licence",
)  # fmt: skip


@dataclass
class ImageImportReport:
    dry_run: bool
    committed: bool = False
    rows: list[dict] = field(default_factory=list)  # {row, product_sku, file, action}
    errors: list[dict] = field(default_factory=list)  # {row, column, message}

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def counts(self) -> dict:
        counts = {"added": 0, "already_there": 0}
        for row in self.rows:
            counts[row["action"]] += 1
        return counts


def _digest(file) -> str:
    sha = hashlib.sha256()
    for chunk in iter(lambda: file.read(65536), b""):
        sha.update(chunk)
    return sha.hexdigest()


def _existing_digests(product: Product) -> set[str]:
    digests = set()
    for image in product.images.all():
        try:
            with image.image.open("rb") as stored:
                digests.add(_digest(stored))
        except (FileNotFoundError, OSError):
            continue  # a missing file can't match; the dashboard shows it as broken
    return digests


def import_images(table: Table, root: Path, *, dry_run: bool = True) -> ImageImportReport:
    report = ImageImportReport(dry_run=dry_run)
    root = root.resolve()
    unknown = [c for c in table.columns if c not in COLUMNS]
    if unknown:
        report.errors.append({"row": None, "column": "", "message": f"Unknown column(s): {', '.join(unknown)}."})
        return report
    if missing := [c for c in ("product_sku", "file") if c not in table.columns]:
        report.errors.append({"row": None, "column": "", "message": f"Missing column(s): {', '.join(missing)}."})
        return report

    planned = []  # (row, product, variant, path, digest, fields)
    owner_of_digest: dict[str, tuple[str, int]] = {}
    for number, cells in table.rows:

        def err(column, message, number=number):
            report.errors.append({"row": number, "column": column, "message": message})

        sku = normalize_sku(cells.get("product_sku", ""))
        product = Product.all_objects.filter(sku=sku).first() if sku else None
        if product is None or product.is_deleted:
            err("product_sku", f"No product with SKU '{sku}'." if sku else "Enter the product SKU.")
            continue
        relative = cells.get("file", "")
        path = (root / relative).resolve()
        if not relative or not path.is_relative_to(root):
            err("file", "Give a file path inside the pictures folder.")
            continue
        if not path.is_file():
            err("file", f"No such file: {relative}")
            continue
        variant = None
        if variant_sku := normalize_sku(cells.get("variant_sku", "")):
            variant = ProductVariant.objects.filter(sku=variant_sku, product=product).first()
            if variant is None:
                err("variant_sku", f"{product.sku} has no variant {variant_sku}.")
                continue
        try:
            is_primary = _bool(cells["is_primary"]) if cells.get("is_primary") else False
        except _CellError as exc:
            err("is_primary", str(exc))
            continue
        source_type = cells.get("source_type") or ProductImage.SourceType.UNVERIFIED
        if source_type not in ProductImage.SourceType.values:
            err("source_type", f"Use one of: {', '.join(ProductImage.SourceType.values)}.")
            continue
        image_type = cells.get("image_type") or ProductImage.ImageType.PHOTO
        if image_type not in ProductImage.ImageType.values:
            err("image_type", f"Use one of: {', '.join(ProductImage.ImageType.values)}.")
            continue
        with path.open("rb") as handle:
            digest = _digest(handle)
        owner = owner_of_digest.setdefault(digest, (product.sku, number))
        if owner[0] != product.sku:
            err("file", f"The same picture is listed for {owner[0]} on row {owner[1]}: one of the matches is wrong.")
            continue
        fields = {
            "alt_text": cells.get("alt_text") or product.name,
            "is_primary": is_primary,
            "source_type": source_type,
            "image_type": image_type,
            "source_url": cells.get("source_url", ""),
            "licence": cells.get("licence", ""),
        }
        planned.append((number, product, variant, path, digest, fields))
    if not report.ok:
        return report

    digests: dict[int, set[str]] = {}
    added: dict[int, int] = {}  # product id → pictures this run would add
    saved: list[ProductImage] = []
    with transaction.atomic():
        for number, product, variant, path, digest, fields in planned:
            known = digests.setdefault(product.pk, _existing_digests(product))
            row = {"row": number, "product_sku": product.sku, "file": path.relative_to(root).as_posix()}
            if digest in known:
                report.rows.append({**row, "action": "already_there"})
                continue
            known.add(digest)
            if dry_run:  # check without writing files: a rollback can't remove stored files
                problem = _dry_run_problem(product, path, fields, added.get(product.pk, 0))
                if problem:
                    report.errors.append({"row": number, "column": "file", "message": problem})
                else:
                    added[product.pk] = added.get(product.pk, 0) + 1
                    report.rows.append({**row, "action": "added"})
                continue
            try:
                with path.open("rb") as handle:
                    image = services.add_product_image(product, File(handle, name=path.name), variant=variant, **fields)
                saved.append(image)
            except (ServiceError, DjangoValidationError) as exc:
                message = str(exc.detail) if isinstance(exc, ServiceError) else " ".join(exc.messages)
                report.errors.append({"row": number, "column": "file", "message": message})
                continue
            report.rows.append({**row, "action": "added"})
        report.committed = report.ok and not dry_run
        if not report.committed:
            transaction.set_rollback(True)
    if saved and not report.committed:
        for image in saved:
            image.image.storage.delete(image.image.name)
    return report


def _dry_run_problem(product: Product, path: Path, fields: dict, pending: int) -> str:
    """What `services.add_product_image` would refuse, checked without storing anything."""
    from apps.core.uploads import ALLOWED_IMAGE_EXTENSIONS

    if path.suffix.lower().lstrip(".") not in ALLOWED_IMAGE_EXTENSIONS:
        return f"Use a {', '.join(ALLOWED_IMAGE_EXTENSIONS)} picture."
    if path.stat().st_size > 5 * 1024 * 1024:
        return "The picture is larger than 5 MB."
    if product.images.count() + pending >= services.MAX_IMAGES_PER_PRODUCT:
        return f"A product can have at most {services.MAX_IMAGES_PER_PRODUCT} pictures."
    if product.is_published and fields["source_type"] == ProductImage.SourceType.UNVERIFIED:
        return "A live product can't show an unverified picture."
    return ""
