"""Photo search API (Phase 14).

POST a photo, get what it probably is and the real catalogue products that match. Anyone may search
(limited by the `image_search` rate); signed-in customers also get a history of their photo searches,
which only they can read or delete (someone else's id gives 404). Photos are never stored: the history
keeps the outcome and a fingerprint, not the picture.
"""

from django.conf import settings
from django.db.models import Prefetch
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import AIConversation, AIMessage
from .services.image_input import ImageTooLarge
from .services.image_search import ImageSearchService
from .views import product_cards

UPLOAD_OVERHEAD = 256 * 1024  # multipart boundaries and form fields around the file


def result_payload(payload: dict, refs: list[dict], context: dict, search_id: int | None) -> dict:
    return {"id": search_id, **payload, "products": product_cards(refs, context)}


class ImageSearchView(APIView):
    """GET: is photo search available (and limits). POST multipart `image`: identify and match."""

    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]
    throttle_scope = "image_search"

    def get_throttles(self):
        return [ScopedRateThrottle()] if self.request.method == "POST" else []

    @extend_schema(responses={200: None})
    def get(self, request):
        return Response(ImageSearchService().status())

    @extend_schema(
        request={
            "multipart/form-data": {"type": "object", "properties": {"image": {"type": "string", "format": "binary"}}}
        },
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        # Refuse an oversized body before Django parses (and writes to disk) the upload.
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > settings.IMAGE_SEARCH_MAX_BYTES + UPLOAD_OVERHEAD:
            raise ImageTooLarge(
                f"The photo is too large ({settings.IMAGE_SEARCH_MAX_BYTES // (1024 * 1024)} MB at most)."
            )
        outcome, conversation = ImageSearchService().search(request.FILES.get("image"), user=request.user)
        context = {"request": request}
        return Response(
            result_payload(outcome.payload(), outcome.product_refs, context, conversation.pk if conversation else None)
        )


class ImageSearchHistorySerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()
    percent = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = AIConversation
        fields = ["id", "title", "status", "label", "percent", "product_count", "created_at"]

    def _payload(self, obj) -> dict:
        messages = list(obj.messages.all())
        return (messages[0].payload if messages else {}) or {}

    def get_status(self, obj) -> str:
        return (obj.metadata or {}).get("status", "")

    def get_label(self, obj) -> str:
        return ((self._payload(obj).get("identification")) or {}).get("label", "")

    def get_percent(self, obj) -> int | None:
        return ((self._payload(obj).get("identification")) or {}).get("percent")

    def get_product_count(self, obj) -> int:
        messages = list(obj.messages.all())
        return len(messages[0].product_refs or []) if messages else 0


class ImageSearchHistoryViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """The signed-in customer's own photo searches (newest first)."""

    permission_classes = [IsAuthenticated]
    serializer_class = ImageSearchHistorySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AIConversation.objects.none()
        return (
            AIConversation.objects.filter(user=self.request.user, kind=AIConversation.Kind.IMAGE)
            .prefetch_related(Prefetch("messages", queryset=AIMessage.objects.filter(role=AIMessage.Role.ASSISTANT)))
            .order_by("-created_at", "-id")
        )

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def retrieve(self, request, pk=None):
        """The search as answered, with product cards rebuilt from the live catalogue."""
        conversation = self.get_object()
        message = next(iter(conversation.messages.all()), None)
        payload = (message.payload if message else {}) or {}
        refs = (message.product_refs if message else []) or []
        data = result_payload(payload, refs, {"request": request}, conversation.pk)
        data["created_at"] = conversation.created_at
        return Response(data)

    @extend_schema(request=None, responses={204: None})
    @action(detail=False, methods=["post"])
    def clear(self, request):
        """Delete every photo search of this customer."""
        self.get_queryset().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
