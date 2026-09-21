import logging

from django.conf import settings
from django.db import connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class HealthView(APIView):
    """Liveness + database readiness. Used by Docker healthchecks and the frontend status badge."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    @extend_schema(
        responses=inline_serializer(
            "Health",
            {
                "status": serializers.CharField(),
                "app": serializers.CharField(),
                "version": serializers.CharField(),
                "database": serializers.CharField(),
            },
        )
    )
    def get(self, request):
        db_status = "ok"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception:  # noqa: BLE001 - report, don't crash the health endpoint
            logger.exception("Database health check failed")
            db_status = "unavailable"
        healthy = db_status == "ok"
        return Response(
            {
                "status": "ok" if healthy else "degraded",
                "app": settings.APP_NAME,
                "version": settings.APP_VERSION,
                "database": db_status,
            },
            status=200 if healthy else 503,
        )
