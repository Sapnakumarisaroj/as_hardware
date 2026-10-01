from django.core.management.base import BaseCommand, CommandError

from apps.catalog.semantic import index


class Command(BaseCommand):
    help = "Build or refresh the semantic search index (only products whose text changed, unless --force)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Embed every product again.")
        parser.add_argument("--status", action="store_true", help="Only show the index status.")

    def handle(self, *args, **options):
        if not options["status"]:
            try:
                result = index.sync_products(force=options["force"])
            except RuntimeError as exc:
                raise CommandError(f"{exc} Keyword search keeps working.") from exc
            self.stdout.write(f"Embedded {result.embedded}, unchanged {result.unchanged}, removed {result.removed}.")
            for name in result.failed:
                self.stderr.write(f"Failed: {name}")
        info = index.status()
        embedder = info["embedder"]
        self.stdout.write(
            f"Embedder {embedder['key']} (available: {embedder['available']}); products {info['products']}, "
            f"indexed {info['indexed']}, missing {info['missing']}, stale {info['stale']}."
        )
