import re
import uuid

from .logging import request_id_var

_VALID_ID = re.compile(r"^[A-Za-z0-9\-_.]{1,64}$")


class RequestIDMiddleware:
    """Attach a request ID (client-supplied if well-formed, else generated) to logs and responses."""

    header = "HTTP_X_REQUEST_ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get(self.header, "")
        rid = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = rid
        token = request_id_var.set(rid)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response["X-Request-ID"] = rid
        return response
