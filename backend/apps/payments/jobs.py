"""Background work for payments, run by `manage.py run_jobs` (and inline after commit in dev)."""

import logging
from datetime import timedelta

from django.utils import timezone

from apps.core.jobs import enqueue, job, periodic

from . import refunds, services
from .consistency import find_issues
from .models import Refund

logger = logging.getLogger(__name__)


@job(refunds.PROCESS_JOB)
def process_refund(refund_id: int):
    return refunds.process_refund(refund_id)


@periodic("payments.1_reconcile_open_payments")
def reconcile_open_payments():
    return services.reconcile_stale_payments()


@periodic("payments.2_expire_unpaid_orders")
def expire_unpaid_orders():
    return services.expire_unpaid_orders()


@periodic("payments.3_refunds")
def refunds_housekeeping():
    """Queue refunds that were never submitted; poll gateway refunds still pending."""
    queued = 0
    for refund in Refund.objects.filter(status=Refund.Status.PENDING, provider_refund_id__isnull=True).select_related(
        "payment"
    )[:200]:
        if not refund.is_manual:
            enqueue(refunds.PROCESS_JOB, {"refund_id": refund.pk}, dedupe_key=f"refund:{refund.pk}")
            queued += 1
    polled = 0
    stale = timezone.now() - timedelta(minutes=15)
    for refund in Refund.objects.filter(
        status=Refund.Status.PENDING, provider_refund_id__isnull=False, last_attempt_at__lt=stale
    )[:100]:
        try:
            refunds.sync_refund(refund.pk)
            polled += 1
        except Exception as exc:  # noqa: BLE001 — one refund must not stop the others
            logger.warning("Refund %s sync postponed: %s", refund.pk, exc)
    return f"queued {queued}, polled {polled}"


@periodic("payments.4_consistency")
def consistency_report():
    issues = find_issues()
    for issue in issues[:20]:
        logger.warning("Payment consistency issue: %s", issue)
    return f"{len(issues)} issue(s)"
