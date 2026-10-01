from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
    label = "catalog"
    verbose_name = "Catalog"

    def ready(self):
        from . import signals  # noqa: F401  (registers the search index signal handlers)
