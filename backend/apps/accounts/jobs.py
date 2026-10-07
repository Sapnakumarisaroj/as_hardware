"""Account emails sent outside the request (Phase 25), run by `manage.py run_jobs` (inline after commit in dev)."""

from apps.core.jobs import job

from . import auth_services


@job(auth_services.RESET_EMAIL_JOB)
def password_reset_email(user_id: int):
    return auth_services.send_password_reset_email(user_id)


@job(auth_services.EMAIL_CHANGED_JOB)
def email_changed_notice(old_email: str, new_email: str, name: str = ""):
    return auth_services.send_email_changed_notice(old_email, new_email, name)
