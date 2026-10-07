"""Consistent error envelope for every API error.

{"error": {"code": "...", "message": "...", "details": {...}}, "request_id": "..."}
"""

import logging

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .logging import request_id_var

logger = logging.getLogger(__name__)


class ServiceError(exceptions.APIException):
    """Raised by service-layer code for business-rule violations (e.g. out of stock)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The request could not be completed."
    default_code = "service_error"

    def __init__(self, message: str | None = None, code: str | None = None, details: dict | None = None):
        self.error_code = code or self.default_code
        super().__init__(detail=message or self.default_detail, code=self.error_code)
        self.details = details or {}


class NotFoundError(ServiceError):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Not found."
    default_code = "not_found"


class ConflictError(ServiceError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state."
    default_code = "conflict"


def _envelope(code: str, message: str, details, status_code: int) -> Response:
    return Response(
        {"error": {"code": code, "message": message, "details": details}, "request_id": request_id_var.get()},
        status=status_code,
    )


def api_exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):  # model validators (image size/format…) are input errors
        exc = exceptions.ValidationError(exc.message_dict if hasattr(exc, "error_dict") else exc.messages)
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        # Unhandled exception: log with traceback, never leak internals to the client.
        logger.exception("Unhandled API error", exc_info=exc)
        return _envelope("server_error", "An unexpected error occurred.", {}, status.HTTP_500_INTERNAL_SERVER_ERROR)

    if isinstance(exc, ServiceError):
        return _envelope(exc.error_code, str(exc.detail), exc.details, response.status_code)

    if isinstance(exc, exceptions.ValidationError):
        return _envelope("validation_error", "Invalid input.", response.data, response.status_code)

    detail = getattr(exc, "detail", "Error")
    code = exc.get_codes() if hasattr(exc, "get_codes") else "error"
    if isinstance(exc, exceptions.Throttled):
        code = "throttled"
    return _envelope(str(code), str(detail), {}, response.status_code)
