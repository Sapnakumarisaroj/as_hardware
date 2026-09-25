"""The DB job queue behind `run_jobs` (Phase 8): claiming, retries with backoff, dedupe, crash recovery."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.core import jobs
from apps.core.models import Job

pytestmark = pytest.mark.django_db
calls: list = []


@jobs.job("test.record")
def _record(value):
    calls.append(value)


@jobs.job("test.flaky")
def _flaky():
    raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def _reset(settings):
    settings.BACKGROUND_JOBS_MODE = "cron"
    calls.clear()


def test_queued_job_runs_once():
    row = jobs.enqueue("test.record", {"value": 7})
    assert jobs.run_due_jobs() == 1 and calls == [7]
    row.refresh_from_db()
    assert row.status == "done" and row.attempts == 1 and row.finished_at
    assert jobs.run_job(row.pk) is False and calls == [7]  # already done: not claimed again


def test_failures_back_off_then_give_up():
    row = jobs.enqueue("test.flaky")
    jobs.run_due_jobs()
    row.refresh_from_db()
    assert row.status == "queued" and row.attempts == 1 and "boom" in row.last_error
    assert row.run_after > timezone.now()  # backoff: not due yet
    assert jobs.run_due_jobs() == 0
    for _ in range(row.max_attempts - 1):
        Job.objects.filter(pk=row.pk).update(run_after=timezone.now() - timedelta(seconds=1))
        jobs.run_due_jobs()
    row.refresh_from_db()
    assert row.status == "failed" and row.attempts == row.max_attempts


def test_dedupe_and_delay():
    first = jobs.enqueue("test.record", {"value": 1}, dedupe_key="k")
    assert jobs.enqueue("test.record", {"value": 2}, dedupe_key="k").pk == first.pk
    later = jobs.enqueue("test.record", {"value": 3}, delay=timedelta(minutes=5))
    jobs.run_due_jobs()
    assert calls == [1]
    later.refresh_from_db()
    assert later.status == "queued"
    assert jobs.enqueue("test.record", {"value": 4}, dedupe_key="k").pk != first.pk  # first is done now


def test_stuck_running_jobs_are_recovered_and_unknown_handlers_fail():
    stuck = Job.objects.create(name="test.record", payload={"value": 9}, status="running",
                               locked_at=timezone.now() - timedelta(hours=1))  # fmt: skip
    unknown = jobs.enqueue("test.nope")
    jobs.run_due_jobs()
    stuck.refresh_from_db()
    unknown.refresh_from_db()
    assert stuck.status == "done" and calls == [9]
    assert "No handler" in unknown.last_error


def test_inline_mode_runs_after_commit(settings, django_capture_on_commit_callbacks):
    settings.BACKGROUND_JOBS_MODE = "inline"
    with django_capture_on_commit_callbacks(execute=True):
        row = jobs.enqueue("test.record", {"value": 5})
    row.refresh_from_db()
    assert row.status == "done" and calls == [5]


def test_run_jobs_command_runs_periodic_tasks_and_the_queue():
    jobs.enqueue("test.record", {"value": 1})
    out = StringIO()
    call_command("run_jobs", stdout=out)
    text = out.getvalue()
    assert "payments.2_expire_unpaid_orders: 0" in text and "payments.4_consistency: 0 issue(s)" in text
    assert "Ran 1 job(s)." in text and calls == [1]
