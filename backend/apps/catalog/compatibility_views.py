"""Compatibility API (Phase 21). Read-only for customers; the data behind it (specifications and the shop's product
links) is changed only by staff in the dashboard, and every change is audited.

- `POST /api/compatibility/check/`            {product_a, variant_a?, product_b, variant_b?} → verdict, reason, checks
- `GET  /api/products/{id}/compatibility/`    accessory groups: required, compatible, commonly used, alternatives
- `GET  /api/cart/compatibility/`             problems between the signed-in customer's cart lines, with replacements
- `POST /api/cart/items/{id}/replace/`        swap a cart line for a compatible product (checked like any cart line)
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import selectors
from .compatibility.service import CompatibilityService
from .serializers import ProductListSerializer


def cards(product_ids, request) -> dict[int, dict]:
    """Product cards from live catalogue rows (published, active), keyed by id."""
    rows = selectors.product_queryset().filter(pk__in=list(product_ids))
    return {p.pk: ProductListSerializer(p, context={"request": request}).data for p in rows}


def with_cards(result: dict, request) -> dict:
    found = cards(
        [result["product_a"]["id"], result["product_b"]["id"], *[o["product_id"] for o in result.get("options", [])]],
        request,
    )
    result["product_a"]["card"] = found.get(result["product_a"]["id"])
    result["product_b"]["card"] = found.get(result["product_b"]["id"])
    for option in result.get("options", []):
        option["product"] = found.get(option["product_id"])
    result["options"] = [o for o in result.get("options", []) if o.get("product")]
    return result


class CheckSerializer(serializers.Serializer):
    product_a = serializers.IntegerField(min_value=1)
    variant_a = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    product_b = serializers.IntegerField(min_value=1)
    variant_b = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class CompatibilityCheckView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "compatibility"

    @extend_schema(request=CheckSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = CheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        service = CompatibilityService()
        result = service.check_ids(data["product_a"], data["product_b"], data.get("variant_a"), data.get("variant_b"))
        payload = result.as_dict()
        payload["options"] = []
        if result.verdict != "COMPATIBLE":
            payload["options"] = service.compatible_options(
                result.product_a, result.variant_a, result.kinds[1], exclude={result.product_b.pk}
            )
        return Response(with_cards(payload, request))


class ProductCompatibilityView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(parameters=[OpenApiParameter("variant", int)], responses={200: OpenApiTypes.OBJECT})
    def get(self, request, product_id: int):
        raw = request.query_params.get("variant") or ""
        data = CompatibilityService().accessories(product_id, int(raw) if raw.isdigit() else None)
        ids = [row["product_id"] for rows in data["groups"].values() for row in rows]
        found = cards(ids, request)
        for name, rows in data["groups"].items():
            data["groups"][name] = [
                {**row, "product": found[row["product_id"]]} for row in rows if row["product_id"] in found
            ]
        return Response(data)


class CartCompatibilityView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        from apps.carts.models import CartItem

        items = list(CartItem.objects.filter(cart__user=request.user).select_related("variant__product"))
        problems = CompatibilityService().check_lines([{"key": item.pk, "variant": item.variant} for item in items])
        out = []
        for problem in problems:
            problem = with_cards(problem, request)
            problem["cart_item_ids"] = problem.pop("keys")
            out.append(problem)
        return Response({"problems": out})


class ReplaceSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=9999, required=False)


class CartItemReplaceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReplaceSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, item_id: int):
        from apps.carts import services as carts
        from apps.carts.views import _cart_response

        serializer = ReplaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        carts.replace_item(request.user, item_id, **serializer.validated_data)
        return _cart_response(request)
