"""Drain the background job queue and run periodic maintenance. Meant for cron, e.g. every 5 minutes:

    */5 * * * *  cd ~/app/backend && ./venv/bin/python manage.py run_jobs --max-seconds 240

Safe to run concurrently: jobs are claimed atomically, and periodic tasks are idempotent.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.jobs import run_due_jobs, run_periodic


class Command(BaseCommand):
    help = "Run due background jobs, then periodic maintenance (payment reconciliation, expiry, refunds)."

    def add_arguments(self, parser):
        parser.add_argument("--max-seconds", type=int, default=240, help="Stop starting new jobs after this long.")
        parser.add_argument("--limit", type=int, default=200, help="Maximum jobs per run.")
        parser.add_argument("--no-periodic", action="store_true", help="Only drain the queue.")

    def handle(self, *args, **options):
        deadline = timezone.now() + timedelta(seconds=options["max_seconds"])
        if not options["no_periodic"]:
            for name, result in run_periodic().items():
                self.stdout.write(f"{name}: {result}")
        # Periodic tasks may enqueue jobs (e.g. refunds to submit); drain afterwards.
        ran = run_due_jobs(limit=options["limit"], deadline=deadline)
        self.stdout.write(self.style.SUCCESS(f"Ran {ran} job(s)."))
