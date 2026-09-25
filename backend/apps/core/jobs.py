"""Background jobs without Celery/Redis: a `core.Job` table drained by `manage.py run_jobs` (cron).

    @job("payments.process_refund")
    def process_refund(refund_id): ...

    enqueue("payments.process_refund", {"refund_id": 7}, dedupe_key="refund:7")

`BACKGROUND_JOBS_MODE=inline` (dev default) also runs the job right after the surrounding
transaction commits, so nothing waits for cron locally; a failure leaves the row queued for
`run_jobs` to retry. `cron` mode only queues. Handlers must be idempotent: a job can run again
after a crash between "work done" and "marked done".

Periodic maintenance (reconciliation, expiry…) registers with `@periodic` and runs on every
`run_jobs` invocation.
"""

import logging
from collections.abc import Callable
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.module_loading import autodiscover_modules

from .models import Job

logger = logging.getLogger(__name__)

_HANDLERS: dict[str, Callable[..., object]] = {}
_PERIODIC: dict[str, Callable[[], object]] = {}
_discovered = False
STALE_RUNNING_AFTER = timedelta(minutes=10)


def job(name: str):
    def register(func):
        _HANDLERS[name] = func
        return func

    return register


def periodic(name: str):
    def register(func):
        _PERIODIC[name] = func
        return func

    return register


def _discover() -> None:
    global _discovered
    if not _discovered:
        autodiscover_modules("jobs")  # imports <app>/jobs.py of every installed app
        _discovered = True


def enqueue(name: str, payload: dict | None = None, *, dedupe_key: str = "", delay: timedelta | None = None) -> Job:
    existing = (
        Job.objects.filter(dedupe_key=dedupe_key, status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).first()
        if dedupe_key
        else None
    )
    if existing:
        if settings.BACKGROUND_JOBS_MODE == "inline" and not delay and existing.status == Job.Status.QUEUED:
            transaction.on_commit(lambda: run_job(existing.pk))  # asked for again: run it now, not at next cron
        return existing
    created = Job.objects.create(
        name=name,
        payload=payload or {},
        dedupe_key=dedupe_key,
        run_after=timezone.now() + (delay or timedelta()),
    )
    if settings.BACKGROUND_JOBS_MODE == "inline" and not delay:
        transaction.on_commit(lambda: run_job(created.pk))
    return created


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(30 * 2 ** (attempts - 1), 3600))  # 30 s, 1 min, 2 min … max 1 h


def run_job(job_id: int) -> bool:
    """Claim and run one job. Returns True if this call ran it (successfully or not)."""
    _discover()
    now = timezone.now()
    claimed = Job.objects.filter(pk=job_id, status=Job.Status.QUEUED).update(
        status=Job.Status.RUNNING, locked_at=now, attempts=F("attempts") + 1
    )
    if not claimed:
        return False  # another worker has it, or it already finished
    row = Job.objects.get(pk=job_id)
    handler = _HANDLERS.get(row.name)
    try:
        if handler is None:
            raise LookupError(f"No handler registered for job '{row.name}'.")
        handler(**row.payload)
    except Exception as exc:  # noqa: BLE001 — every failure is recorded and retried
        logger.warning("Job %s #%s failed (attempt %s): %s", row.name, row.pk, row.attempts, exc)
        final = row.attempts >= row.max_attempts
        Job.objects.filter(pk=job_id).update(
            status=Job.Status.FAILED if final else Job.Status.QUEUED,
            last_error=f"{type(exc).__name__}: {exc}"[:2000],
            run_after=timezone.now() + _backoff(row.attempts),
            locked_at=None,
            finished_at=timezone.now() if final else None,
        )
        return True
    Job.objects.filter(pk=job_id).update(
        status=Job.Status.DONE, locked_at=None, finished_at=timezone.now(), last_error=""
    )
    return True


def run_due_jobs(*, limit: int = 100, deadline=None) -> int:
    """Run queued jobs whose time has come. Also re-queues jobs stuck in RUNNING (crashed worker)."""
    now = timezone.now()
    Job.objects.filter(status=Job.Status.RUNNING, locked_at__lt=now - STALE_RUNNING_AFTER).update(
        status=Job.Status.QUEUED, locked_at=None
    )
    ran = 0
    due = list(Job.objects.filter(status=Job.Status.QUEUED, run_after__lte=now).order_by("run_after", "id")[:limit])
    for row in due:
        if deadline and timezone.now() >= deadline:
            break
        ran += run_job(row.pk)
    return ran


def run_periodic() -> dict[str, str]:
    """Run every registered maintenance task; one failing task never stops the others."""
    _discover()
    results = {}
    for name, func in sorted(_PERIODIC.items()):
        try:
            results[name] = str(func())
        except Exception as exc:  # noqa: BLE001
            logger.exception("Periodic task %s failed", name)
            results[name] = f"error: {exc}"
    return results
