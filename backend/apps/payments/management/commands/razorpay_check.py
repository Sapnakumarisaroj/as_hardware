"""Is the Razorpay integration configured, and in which mode? Secrets are never printed.

    python manage.py razorpay_check          # configuration only
    python manage.py razorpay_check --ping   # also one read-only authenticated call (GET /orders?count=1)

Exit code 1 when something needed is missing or the keys are rejected.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from integrations.payments import GatewayError
from integrations.payments.base import GatewayRejected


def mode(key_id: str) -> str:
    if not key_id:
        return "missing"
    if key_id.startswith("rzp_test_"):
        return "TEST mode"
    if key_id.startswith("rzp_live_"):
        return "LIVE mode (real money)"
    return "unrecognised key id"


class Command(BaseCommand):
    help = "Show the Razorpay configuration (no secrets) and optionally check the keys with a read-only call."

    def add_arguments(self, parser):
        parser.add_argument("--ping", action="store_true", help="Check the keys with GET /orders?count=1.")

    def handle(self, *args, ping=False, **options):
        key_id = settings.RAZORPAY_KEY_ID
        rows = [
            ("PAYMENT_PROVIDER", settings.PAYMENT_PROVIDER),
            ("RAZORPAY_KEY_ID", f"{key_id[:9]}… ({mode(key_id)})" if key_id else "missing"),
            ("RAZORPAY_KEY_SECRET", "set" if settings.RAZORPAY_KEY_SECRET else "missing"),
            ("RAZORPAY_WEBHOOK_SECRET", "set" if settings.RAZORPAY_WEBHOOK_SECRET else "missing (webhooks refused)"),
        ]
        for name, value in rows:
            self.stdout.write(f"{name:24} {value}")
        problems = []
        if settings.PAYMENT_PROVIDER != "razorpay":
            problems.append("PAYMENT_PROVIDER is not razorpay: checkout uses the "
                            f"'{settings.PAYMENT_PROVIDER}' provider.")  # fmt: skip
        if not (key_id and settings.RAZORPAY_KEY_SECRET):
            problems.append("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are both needed.")
        if ping and key_id and settings.RAZORPAY_KEY_SECRET:
            from integrations.payments.razorpay import RazorpayClient

            client = RazorpayClient(key_id, settings.RAZORPAY_KEY_SECRET, settings.RAZORPAY_API_BASE)
            try:
                client.request("GET", "/orders", params={"count": 1})
                self.stdout.write(self.style.SUCCESS("Razorpay accepted the keys (read-only check)."))
            except GatewayRejected as exc:
                problems.append(f"Razorpay rejected the keys: {exc}")
            except GatewayError as exc:
                problems.append(f"Could not reach Razorpay: {exc}")
        for problem in problems:
            self.stderr.write(self.style.WARNING(problem))
        if problems:
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(f"Razorpay configured in {mode(key_id)}."))
