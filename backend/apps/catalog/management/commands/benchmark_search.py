# ruff: noqa: E501
from django.core.management.base import BaseCommand

from apps.catalog.semantic import benchmark


class Command(BaseCommand):
    help = "Compare keyword search with hybrid (semantic) search on labelled queries over the current catalogue."

    def add_arguments(self, parser):
        parser.add_argument("--set", choices=sorted(benchmark.SETS), default="main", help="Which labelled queries.")
        parser.add_argument("--verbose", action="store_true", help="Show the top results of every query.")

    def _write(self, text: str) -> None:
        try:
            self.stdout.write(text)
        except UnicodeEncodeError:  # e.g. Hindi queries on a Windows cp1252 console
            self.stdout.write(text.encode("ascii", "backslashreplace").decode("ascii"))

    def handle(self, *args, **options):
        report = benchmark.run(benchmark.SETS[options["set"]])
        for row in report["queries"]:
            ranks = "  ".join(f"{m} {row[m + '_rank'] or '-':>2}" for m in ("keyword", "related", "hybrid"))
            self._write(f"{row['query'][:52]:52} {ranks}")
            if options["verbose"]:
                for m in ("keyword", "related", "hybrid"):
                    self._write(f"    {m}: {row[m + '_top']}")
        for name in ("keyword", "related", "hybrid"):
            m = report[name]
            self.stdout.write(
                f"{name:8} hit@1 {m['hit1']:.0%}  hit@3 {m['hit3']:.0%}  hit@5 {m['hit5']:.0%}  MRR {m['mrr']:.3f}  found {m['found']}/{m['total']}"
            )
