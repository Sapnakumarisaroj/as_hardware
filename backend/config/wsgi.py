import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
application = get_wsgi_application()

from apps.catalog.semantic.embedders import warm_up_in_background  # noqa: E402  (needs Django set up)

warm_up_in_background()
