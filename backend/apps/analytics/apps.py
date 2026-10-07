from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    """Business reports and the business assistant under /api/admin/ (Phase 24). Read-only over the
    other apps' data; its only table is the assistant's question history."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.analytics"
