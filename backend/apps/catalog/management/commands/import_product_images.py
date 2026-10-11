"""Attach product pictures from a folder, listed in a mapping sheet (apps/catalog/image_import.py).

    python manage.py import_product_images map.csv --root ../assets/as-hardware-images            # dry run
    python manage.py import_product_images map.csv --root ../assets/as-hardware-images --commit   # save

Exits with an error (and saves nothing) when any row is wrong; the errors are listed per row.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.image_import import import_images
from apps.catalog.importer import ImportFileError, read_table


class Command(BaseCommand):
    help = "Attach product pictures listed in a .csv/.xlsx mapping (dry run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Mapping sheet: product_sku, file, is_primary, alt_text, source_type, …")
        parser.add_argument("--root", required=True, help="Folder the 'file' paths are relative to.")
        parser.add_argument("--commit", action="store_true", help="Save the pictures (default: dry run).")

    def handle(self, *args, file, root, commit=False, **options):
        path, root_path = Path(file), Path(root)
        if not path.is_file():
            raise CommandError(f"No such file: {path}")
        if not root_path.is_dir():
            raise CommandError(f"No such folder: {root_path}")
        try:
            table = read_table(path.read_bytes(), path.name, check_header=False)
        except ImportFileError as exc:
            raise CommandError(str(exc.detail)) from exc
        report = import_images(table, root_path, dry_run=not commit)
        for error in report.errors:
            where = f"row {error['row']}" if error["row"] else "file"
            column = f" [{error['column']}]" if error["column"] else ""
            self.stderr.write(f"{where}{column} {error['message']}")
        if not report.ok:
            raise CommandError(f"{len(report.errors)} error(s); nothing was saved.")
        counts = ", ".join(f"{key.replace('_', ' ')}: {value}" for key, value in report.counts.items())
        prefix = "Imported" if report.committed else "Dry run, nothing saved (add --commit to import)"
        self.stdout.write(self.style.SUCCESS(f"{prefix}. {counts}"))
