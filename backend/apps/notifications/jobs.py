"""Background work for notifications, run by `manage.py run_jobs` (and inline after commit in dev)."""

from apps.core.jobs import job, periodic

from . import services


@job(services.DELIVER_JOB)
def deliver_notification(notification_id: int):
    return services.deliver(notification_id)


@periodic("notifications.1_delivery_delays")
def delivery_delays():
    return f"{services.tell_about_delays()} late order(s) told"
