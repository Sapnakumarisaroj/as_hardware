"""The AI hardware assistant API (Phase 12).

Conversations belong to the signed-in customer; nobody else can list, read, continue, clear
or delete them (404 for someone else's id). The assistant reads the catalogue; it has no
endpoint that could change prices, stock, orders or the cart. Adding to the cart is the
customer's action through the normal cart API.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.catalog.serializers import ProductListSerializer

from .models import AIConversation, AIMessage
from .services.assistant import HardwareAssistantService
from .services.conversation import MAX_MESSAGE_LENGTH, AIConversationService
from .services.retrieval import CatalogRetrievalService
from .services.schemas import LANGUAGES


def product_cards(refs: list[dict], context: dict) -> list[dict]:
    """Product cards for stored references, from live catalogue rows (prices and stock are never stale)."""
    if not refs:
        return []
    rows = context.setdefault("_rows", {})
    wanted = [r["product_id"] for r in refs if r["product_id"] not in rows]
    if wanted:
        rows.update(CatalogRetrievalService().products_by_id(wanted))
    out = []
    for ref in refs:
        product = rows.get(ref["product_id"])
        if product is None:
            continue  # no longer on sale: the card disappears, the text stays
        data = ProductListSerializer(product, context=context).data
        data["variant_id"] = ref.get("variant_id") or data.get("default_variant_id")
        data["reason"] = ref.get("reason", "")
        if "confidence" in ref:  # photo search: which identification led to this product
            data["match_label"] = ref.get("label", "")
            data["match_confidence"] = ref["confidence"]
        out.append(data)
    return out


class AIMessageSerializer(serializers.ModelSerializer):
    """A message as shown. Product cards are rebuilt from live catalogue rows each time."""

    products = serializers.SerializerMethodField()
    questions = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    intent = serializers.SerializerMethodField()
    ai_mode = serializers.SerializerMethodField()
    notice = serializers.SerializerMethodField()
    knowledge = serializers.SerializerMethodField()
    safety = serializers.SerializerMethodField()
    estimate = serializers.SerializerMethodField()

    class Meta:
        model = AIMessage
        fields = [
            "id",
            "role",
            "content",
            "created_at",
            "products",
            "questions",
            "actions",
            "intent",
            "ai_mode",
            "notice",
            "knowledge",
            "safety",
            "estimate",
        ]

    def _payload(self, obj, key, default):
        return (obj.payload or {}).get(key) or default

    def get_products(self, obj) -> list[dict]:
        return product_cards(obj.product_refs or [], self.context)

    def get_questions(self, obj) -> list[str]:
        return self._payload(obj, "questions", [])

    def get_actions(self, obj) -> list[dict]:
        return self._payload(obj, "actions", [])

    def get_intent(self, obj) -> str:
        return self._payload(obj, "intent", "")

    def get_ai_mode(self, obj) -> str:
        return self._payload(obj, "ai_mode", "")

    def get_notice(self, obj) -> str:
        return self._payload(obj, "notice", "")

    def get_knowledge(self, obj) -> list[dict]:
        return self._payload(obj, "knowledge", [])

    def get_safety(self, obj) -> list[str]:
        return self._payload(obj, "safety", [])

    def get_estimate(self, obj) -> dict | None:
        return self._payload(obj, "estimate", None)


class AIConversationSerializer(serializers.ModelSerializer):
    message_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = AIConversation
        fields = ["id", "kind", "language", "title", "message_count", "created_at", "updated_at"]


class AIConversationDetailSerializer(AIConversationSerializer):
    messages = serializers.SerializerMethodField()

    class Meta(AIConversationSerializer.Meta):
        fields = AIConversationSerializer.Meta.fields + ["messages"]

    def get_messages(self, obj) -> list[dict]:
        visible = [m for m in obj.messages.all() if m.role in (AIMessage.Role.USER, AIMessage.Role.ASSISTANT)]
        return AIMessageSerializer(visible, many=True, context=self.context).data


class AskSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=MAX_MESSAGE_LENGTH, trim_whitespace=True)
    language = serializers.ChoiceField(choices=LANGUAGES, required=False)


class StartSerializer(serializers.Serializer):
    message = serializers.CharField(
        max_length=MAX_MESSAGE_LENGTH, trim_whitespace=True, required=False, allow_blank=True
    )
    language = serializers.ChoiceField(choices=LANGUAGES, required=False)


class AssistantStatusView(APIView):
    """Basic or model-backed, suggested prompts, greeting. Public, so the page can render before login."""

    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(responses={200: None})
    def get(self, request):
        return Response(HardwareAssistantService().status())


class AIConversationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai"

    def get_throttles(self):
        # Reading history is cheap; only asking the assistant is limited by the `ai` rate.
        return super().get_throttles() if self.action in ("create", "messages") else []

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AIConversation.objects.none()
        qs = AIConversationService.for_user(self.request.user)
        if self.action == "list":
            from django.db.models import Count

            return qs.annotate(message_count=Count("messages")).order_by("-updated_at", "-id")
        return qs.prefetch_related("messages")

    def get_serializer_class(self):
        return AIConversationSerializer if self.action == "list" else AIConversationDetailSerializer

    def _detail(self, conversation, status_code=status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=conversation.pk)
        return Response(
            AIConversationDetailSerializer(fresh, context={"request": self.request}).data, status=status_code
        )

    @extend_schema(request=StartSerializer, responses={201: AIConversationDetailSerializer})
    def create(self, request):
        """Start a conversation; with `message`, the first answer is included."""
        serializer = StartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        service = AIConversationService()
        conversation = service.start(request.user, language=data.get("language") or "en")
        if data.get("message"):
            HardwareAssistantService().ask(conversation, data["message"], language_hint=data.get("language", ""))
        return self._detail(conversation, status.HTTP_201_CREATED)

    @extend_schema(request=AskSerializer, responses={201: None})
    @action(detail=True, methods=["post"])
    def messages(self, request, pk=None):
        """Ask the assistant. Returns the customer's message and the answer, with product cards."""
        conversation = self.get_object()
        serializer = AskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        _reply, user_message, assistant_message = HardwareAssistantService().ask(
            conversation, data["message"], language_hint=data.get("language", "")
        )
        context = {"request": request}
        return Response(
            {
                "conversation_id": conversation.pk,
                "title": AIConversation.objects.filter(pk=conversation.pk).values_list("title", flat=True).first(),
                "user_message": AIMessageSerializer(user_message, context=context).data,
                "assistant_message": AIMessageSerializer(assistant_message, context=context).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=None, responses=AIConversationDetailSerializer)
    @action(detail=True, methods=["post"])
    def clear(self, request, pk=None):
        """Remove every message but keep the conversation."""
        conversation = self.get_object()
        AIConversationService().clear(conversation)
        return self._detail(conversation)
