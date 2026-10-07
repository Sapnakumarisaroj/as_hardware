"""Apply the owner's approved category tree (apps/catalog/taxonomy.py).

    python manage.py apply_taxonomy --dry-run   # list what would change, change nothing
    python manage.py apply_taxonomy

Creates or renames the approved categories, moves products of re-parented subcategories, and
archives (never deletes) every other category with its products. Safe to run again.
"""

from django.core.management.base import BaseCommand

from apps.catalog.taxonomy import apply_taxonomy


class Command(BaseCommand):
    help = "Create the approved categories and archive everything outside them (orders and history are kept)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report the changes without saving them.")

    def handle(self, *args, dry_run=False, **options):
        report = apply_taxonomy(dry_run=dry_run)
        for label, rows in (
            ("Categories created", report.created),
            ("Categories renamed or moved", report.updated),
            ("Products moved to their new parent category", report.moved_products),
            ("Categories archived", report.archived_categories),
            ("Products archived", report.archived_products),
            ("Rules and bundles switched off", report.switched_off),
        ):
            if rows:
                self.stdout.write(f"{label} ({len(rows)}): " + ", ".join(map(str, rows)))
        prefix = "Dry run, nothing saved: " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(prefix + report.summary()))
