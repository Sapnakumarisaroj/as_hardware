from django.core.management.base import BaseCommand

from apps.payments.consistency import find_issues


class Command(BaseCommand):
    help = "List payment/order/refund records that disagree. Read-only; exit code 1 if any issue is found."

    def handle(self, *args, **options):
        issues = find_issues()
        for issue in issues:
            self.stdout.write(
                f"[{issue['code']}] order={issue['order']} payment={issue['payment']}: {issue['message']}"
            )
        if issues:
            self.stderr.write(self.style.WARNING(f"{len(issues)} issue(s) found."))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("Payments consistent: no issues."))
