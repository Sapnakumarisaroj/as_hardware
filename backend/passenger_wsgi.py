"""Entry point for Phusion Passenger (cPanel "Setup Python App" / CloudLinux Python Selector).

Passenger imports `application` from this file. Settings come from environment
variables set in the control panel or from the `.env` file next to the project.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

from config.wsgi import application  # noqa: E402,F401
