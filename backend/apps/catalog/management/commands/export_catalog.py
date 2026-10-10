"""Export the catalogue in the import columns (re-importable unchanged).

python manage.py export_catalog                          # catalogue.xlsx in the current folder
python manage.py export_catalog --output products.csv    # format from the extension
python manage.py export_catalog --template --output blank.xlsx
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.importer_export import export_rows, template, write_csv, write_xlsx


class Command(BaseCommand):
    help = "Export products and variants to .xlsx or .csv in the import columns."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="catalogue.xlsx", help="File to write (.xlsx or .csv).")
        parser.add_argument("--template", dest="blank", action="store_true", help="Write a blank template instead.")
        parser.add_argument("--include-demo", action="store_true", help="Also export demo products.")
        parser.add_argument("--include-deleted", action="store_true", help="Also export deleted products.")

    def handle(self, *args, output, blank=False, include_demo=False, include_deleted=False, **options):
        path = Path(output)
        fmt = path.suffix.lower().lstrip(".")
        if fmt not in ("csv", "xlsx"):
            raise CommandError("The output file must end in .xlsx or .csv.")
        if blank:
            content, count = template(fmt), 0
        else:
            rows = export_rows(include_demo=include_demo, include_deleted=include_deleted)
            content, count = (write_xlsx(rows) if fmt == "xlsx" else write_csv(rows)), len(rows)
        path.write_bytes(content)
        self.stdout.write(self.style.SUCCESS(f"Wrote {count} variant row(s) to {path}."))
