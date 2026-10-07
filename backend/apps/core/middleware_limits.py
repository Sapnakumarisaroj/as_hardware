"""Refuse oversized request bodies before Django parses them (Phase 25).

Django's DATA_UPLOAD_MAX_MEMORY_SIZE doesn't count file parts, so a multi-gigabyte multipart POST to any
endpoint would be streamed to temporary files before the view could refuse it. The largest legitimate
upload is a photo (8 MB); `MAX_REQUEST_BYTES` (default 12 MB) leaves room for the form around it. The web
server should also cap bodies (Apache `LimitRequestBody`); see DEPLOYMENT.md.
"""

from django.conf import settings
from django.http import JsonResponse


class RequestSizeLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > settings.MAX_REQUEST_BYTES:
            return JsonResponse(
                {"error": {"code": "request_too_large", "message": "The request is too large.", "details": {}}},
                status=413,
            )
        return self.get_response(request)
