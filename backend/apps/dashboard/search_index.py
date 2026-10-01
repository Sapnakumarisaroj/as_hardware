"""Search index tools for administrators (Phase 13): status, rebuild, refresh one product, explain a query."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import selectors
from apps.catalog.models import Product
from apps.catalog.search import get_search_backend, normalize_query
from apps.catalog.semantic import index
from apps.catalog.semantic.backend import HybridSearchBackend
from apps.core.audit import record_audit
from apps.core.permissions import IsAdminRole


def _status_payload() -> dict:
    backend = get_search_backend()
    return {**index.status(), "search_backend": getattr(backend, "name", type(backend).__name__)}


class SearchIndexView(APIView):
    """Is the semantic index there, complete and current? Which embedder and backend are in use?"""

    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: None})
    def get(self, request):
        return Response(_status_payload())


class RebuildSerializer(serializers.Serializer):
    force = serializers.BooleanField(required=False, default=False)


class SearchIndexRebuildView(APIView):
    """Embed the products whose words changed (or every product with `force`). Runs now, so a very
    large catalogue with a local model should use `manage.py rebuild_search_index` instead."""

    permission_classes = [IsAdminRole]

    @extend_schema(request=RebuildSerializer, responses={200: None})
    def post(self, request):
        serializer = RebuildSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = index.sync_products(force=serializer.validated_data["force"])
        except RuntimeError as exc:
            return Response(
                {"error": {"code": "semantic_unavailable", "message": f"{exc} Keyword search keeps working."}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        record_audit(
            action="search.rebuild_index",
            actor=request.user,
            changes={**result.as_dict(), "force": serializer.validated_data["force"]},
            request=request,
        )
        return Response({"result": result.as_dict(), "status": _status_payload()})


class SearchIndexProductView(APIView):
    """Embed one product again (e.g. after editing it while the job queue is off)."""

    permission_classes = [IsAdminRole]

    @extend_schema(request=None, responses={200: None})
    def post(self, request, pk):
        if not Product.objects.filter(pk=pk).exists():
            return Response({"error": {"code": "not_found", "message": "Product not found."}}, status=404)
        try:
            index.sync_products([index._products().get(pk=pk)], force=True)
        except RuntimeError as exc:
            return Response(
                {"error": {"code": "semantic_unavailable", "message": f"{exc} Keyword search keeps working."}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"status": _status_payload()})


class SearchExplainView(APIView):
    """Every score behind the ranking of a query: keyword, related words, semantic, final."""

    permission_classes = [IsAdminRole]

    @extend_schema(parameters=[OpenApiParameter("q", str, required=True)], responses={200: None})
    def get(self, request):
        query = normalize_query(request.query_params.get("q"))
        if not query:
            return Response({"error": {"code": "validation_error", "message": "q is required."}}, status=400)
        return Response(HybridSearchBackend().analyse(selectors.product_queryset(), query))
