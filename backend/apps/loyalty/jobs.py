"""Periodic loyalty maintenance (Phase 17), run by `manage.py run_jobs`."""

from apps.core.jobs import periodic

from .ledger import expire_due, release_due


@periodic("loyalty.release_credits")
def release_credits():
    """Cashback and rewards whose return window has passed become usable."""
    return f"{release_due()} credited"


@periodic("loyalty.expire_credits")
def expire_credits():
    """What is left of credits past their expiry is written off with an expiry entry."""
    return f"{expire_due()} expired"
