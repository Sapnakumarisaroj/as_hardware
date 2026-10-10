"""Import the catalogue from a spreadsheet (apps/catalog/importer.py, docs/CATALOG_IMPORT.md).

    python manage.py import_catalog products.xlsx                   # dry run: check every row, save nothing
    python manage.py import_catalog products.xlsx --commit          # save, all or nothing
    python manage.py import_catalog products.xlsx --sheet Products  # a sheet other than the first

Exits with an error (and saves nothing) when any row is wrong; the errors are listed per row.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.importer import ImportFileError, import_file


class Command(BaseCommand):
    help = "Import products and variants from a .csv or .xlsx file (dry run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to a .csv or .xlsx file in the import columns.")
        parser.add_argument("--commit", action="store_true", help="Save the import (default: dry run).")
        parser.add_argument("--sheet", default=None, help="Excel sheet name (default: the first sheet).")
        parser.add_argument(
            "--allow-demo", action="store_true", help="Also update rows marked as demo data (normally refused)."
        )

    def handle(self, *args, file, commit=False, sheet=None, allow_demo=False, **options):
        path = Path(file)
        if not path.is_file():
            raise CommandError(f"No such file: {path}")
        try:
            report = import_file(path.read_bytes(), path.name, sheet=sheet, dry_run=not commit, allow_demo=allow_demo)
        except ImportFileError as exc:
            raise CommandError(str(exc.detail)) from exc
        for error in report.as_dict()["errors"]:
            where = f"row {error['row']}" if error["row"] else "file"
            column = f" [{error['column']}]" if error["column"] else ""
            sku = f" {error['sku']}:" if error["sku"] else ""
            self.stderr.write(f"{where}{column}{sku} {error['message']}")
        if not report.ok:
            raise CommandError(f"{len(report.errors)} error(s); nothing was saved.")
        counts = ", ".join(f"{key.replace('_', ' ')}: {value}" for key, value in report.counts.items())
        prefix = "Imported" if report.committed else "Dry run, nothing saved (add --commit to import)"
        self.stdout.write(self.style.SUCCESS(f"{prefix}. {counts}"))
