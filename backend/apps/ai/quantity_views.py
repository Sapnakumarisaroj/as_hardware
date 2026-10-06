"""Quantity AI API (Phase 20).

- `GET  /api/ai/quantity/?language=`      the calculators (with examples), whether the AI helper is on, the pack rule
- `POST /api/ai/quantity/`                a requirement and/or a calculator (+ answers, changes, PIN, coupon) →
                                          questions, assumptions, the breakdown and a priced, delivery-checked kit
- `POST /api/ai/quantity/add-to-cart/`    the result's lines into the cart (all or nothing; signed in)
- `POST /api/ai/quantity/save/`           the calculation saved as a project (signed in)

Anyone may calculate (rate `ai`). Nothing is stored by a calculation; prices, offers, stock and delivery come
from the shop's own engines on every request, and the cart checks every line again.
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .project_views import attach_cards, location_params
from .projects.builder import MAX_DESCRIPTION
from .projects.kit import MAX_ITEMS
from .projects.templates import CALCULATORS
from .quantity.service import QuantityAIService

LANGUAGES = ["en", "hi", "hinglish"]


class OverrideSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField(min_value=1, required=False)
    quantity = serializers.IntegerField(min_value=1, max_value=9999, required=False)
    included = serializers.BooleanField(required=False)


class EstimateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=MAX_DESCRIPTION, required=False, allow_blank=True, trim_whitespace=True)
    calculator = serializers.ChoiceField(choices=list(CALCULATORS), required=False)
    answers = serializers.DictField(required=False)
    language = serializers.ChoiceField(choices=LANGUAGES, required=False)
    overrides = serializers.DictField(child=OverrideSerializer(), required=False)
    coupon = serializers.CharField(max_length=40, required=False, allow_blank=True)
    postal_code = serializers.RegexField(r"^\d{6}$", required=False, allow_blank=True)
    address_id = serializers.IntegerField(min_value=1, required=False)

    def validate(self, attrs):
        if not attrs.get("text") and not attrs.get("calculator"):
            raise serializers.ValidationError("Describe what you need or choose a calculator.")
        if len(attrs.get("overrides") or {}) > MAX_ITEMS:
            raise serializers.ValidationError(f"At most {MAX_ITEMS} changes.")
        return attrs


class CartLineSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=9999)


class AddToCartSerializer(serializers.Serializer):
    lines = CartLineSerializer(many=True, allow_empty=False, max_length=MAX_ITEMS)


class QuantityView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "ai"

    def get_throttles(self):
        return [ScopedRateThrottle()] if self.request.method == "POST" else []

    @extend_schema(parameters=[OpenApiParameter("language", str)], responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        language = request.query_params.get("language", "en")
        return Response(QuantityAIService().status(language if language in LANGUAGES else "en"))

    @extend_schema(request=EstimateSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = EstimateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        location = location_params(request)
        result = QuantityAIService().estimate(
            text=data.get("text", ""),
            calculator=data.get("calculator", ""),
            answers=data.get("answers") or {},
            language=data.get("language", ""),
            user=request.user,
            postal_code=data.get("postal_code") or location["postal_code"],
            address_id=data.get("address_id") if request.user.is_authenticated else None,
            overrides=data.get("overrides") or {},
            coupon=data.get("coupon", ""),
        )
        attach_cards(result.get("kit"), request)
        return Response(result)


class QuantityAddToCartView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=AddToCartSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = AddToCartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(QuantityAIService.add_to_cart(request.user, serializer.validated_data["lines"]))


class QuantitySaveView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai"

    @extend_schema(request=EstimateSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = EstimateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = QuantityAIService().save(
            request.user,
            text=data.get("text", ""),
            calculator=data.get("calculator", ""),
            answers=data.get("answers") or {},
            language=data.get("language", ""),
            overrides=data.get("overrides") or {},
        )
        return Response({"project_id": project.pk, "path": f"/projects/{project.pk}"}, status=status.HTTP_201_CREATED)
