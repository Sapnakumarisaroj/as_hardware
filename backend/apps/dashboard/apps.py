from django.apps import AppConfig


class DashboardConfig(AppConfig):
    """Business dashboard APIs under /api/admin/ (Phase 11). No models of its own: it reads the
    other apps' data and calls their services, so there is one set of business rules."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dashboard"
