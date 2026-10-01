import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
application = get_wsgi_application()

from apps.ai.services.vision_kinds import all_kinds  # noqa: E402
from apps.catalog.semantic.embedders import warm_up_in_background  # noqa: E402  (needs Django set up)
from integrations.vision import warm_up_in_background as warm_up_vision  # noqa: E402

warm_up_in_background()
warm_up_vision(all_kinds)
