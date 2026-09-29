"""Private file storage: files that must never be reachable by URL.

Product images live under MEDIA_ROOT, which the web server publishes. Proof-of-delivery photos
show a customer's door, face or signature, so they are kept under PRIVATE_MEDIA_ROOT (outside
every web-served folder) and only streamed by API views that check who is asking.
"""

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    def __init__(self, **kwargs):
        kwargs.setdefault("location", settings.PRIVATE_MEDIA_ROOT)
        kwargs["base_url"] = None
        super().__init__(**kwargs)

    def url(self, name):
        raise ValueError("Private files have no URL; they are served through authenticated API views.")


def private_storage() -> PrivateStorage:
    """Callable for `FileField(storage=…)`: resolved at runtime, so migrations stay portable."""
    return PrivateStorage()
