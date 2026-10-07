"""Voice shopping API (Phase 18).

- `GET  /api/ai/voice/`             languages, examples, whether the server can listen/speak (public)
- `POST /api/ai/voice/command/`     a transcript → what was understood, priced cart lines to confirm,
                                    products, a page to open or the assistant's answer, and the text to speak
- `POST /api/ai/voice/transcribe/`  a recording → words (only when the owner switched on server recognition)
- `POST /api/ai/voice/speak/`       words → audio (only when the owner switched on a server voice)
- `/api/ai/voice-sessions/`         the signed-in customer's own voice history (list, read, delete, clear)

Anyone may use voice (limited by the `voice` and `voice_audio` rates). Nothing here writes the cart or an
order: the browser adds confirmed lines through the cart API, which prices them again. Recordings are
checked, transcribed and thrown away.
"""

from django.conf import settings
from django.db.models import Count, Prefetch
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import AIConversation, AIMessage
from .services.schemas import LANGUAGES
from .services.voice import MAX_TRANSCRIPT_LENGTH, AudioTooLarge, VoiceShoppingService
from .views import product_cards

UPLOAD_OVERHEAD = 64 * 1024


def voice_payload(payload: dict, refs_context: dict) -> dict:
    """The stored/computed answer with product cards rebuilt from live catalogue rows."""
    data = dict(payload)
    lines = []
    for line in payload.get("lines") or []:
        line = dict(line)
        cards = product_cards(
            [{"product_id": line["product_id"], "variant_id": line.get("variant_id"), "reason": ""}]
            if line.get("product_id")
            else [],
            refs_context,
        )
        line["product"] = cards[0] if cards else None
        line["alternatives"] = product_cards(line.get("alternatives") or [], refs_context)
        lines.append(line)
    data["lines"] = lines
    return data


class PendingLineSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=9999)
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)


class VoiceCommandSerializer(serializers.Serializer):
    transcript = serializers.CharField(max_length=MAX_TRANSCRIPT_LENGTH, trim_whitespace=True)
    language = serializers.ChoiceField(choices=LANGUAGES, required=False)
    conversation_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    postal_code = serializers.RegexField(r"^\d{6}$", required=False, allow_blank=True)
    # The lines shown and waiting for "yes" (or a new quantity). The server prices them again.
    pending = PendingLineSerializer(many=True, required=False)

    def validate_pending(self, value):
        if len(value) > settings.VOICE_MAX_LINES:
            raise serializers.ValidationError(f"At most {settings.VOICE_MAX_LINES} items at a time.")
        return value


class SpeakSerializer(serializers.Serializer):
    text = serializers.CharField(trim_whitespace=True)
    language = serializers.ChoiceField(choices=LANGUAGES, required=False)

    def validate_text(self, value):
        if len(value) > settings.VOICE_MAX_SPEAK_CHARS:
            raise serializers.ValidationError(f"At most {settings.VOICE_MAX_SPEAK_CHARS} characters.")
        return value


class VoiceStatusView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(VoiceShoppingService().status())


class VoiceCommandView(APIView):
    permission_classes = [AllowAny]

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "voice"

    @extend_schema(request=VoiceCommandSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = VoiceCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        service = VoiceShoppingService()
        reply = service.command(
            data["transcript"],
            language=data.get("language", ""),
            pending=data.get("pending") or [],
            user=request.user,
            postal_code=data.get("postal_code") or "",
        )
        conversation = service.record(request.user, data.get("conversation_id"), reply)
        context = {"request": request}
        body = voice_payload(reply.payload(), context)
        body["products"] = product_cards(reply.products, context)
        body["conversation_id"] = conversation.pk if conversation else None
        return Response(body)


class VoiceTranscribeView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "voice_audio"

    @extend_schema(
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {"audio": {"type": "string", "format": "binary"}, "language": {"type": "string"}},
            }
        },
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        # Refuse an oversized body before Django parses (and writes to disk) the upload.
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > settings.VOICE_MAX_AUDIO_BYTES + UPLOAD_OVERHEAD:
            raise AudioTooLarge(f"The recording is too long ({settings.VOICE_MAX_AUDIO_BYTES // 1024} KB at most).")
        language = request.data.get("language") or ""
        language = language if language in LANGUAGES else ""
        return Response(VoiceShoppingService().transcribe(request.FILES.get("audio"), language=language))


class VoiceSpeakView(APIView):
    # Signed-in only: with a paid speech provider this would otherwise be a free public text-to-speech service.
    # Visitors hear answers through the browser's own voice (the page falls back to it).
    permission_classes = [IsAuthenticated]

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "voice_audio"

    @extend_schema(request=SpeakSerializer, responses={(200, "audio/mpeg"): OpenApiTypes.BINARY})
    def post(self, request):
        serializer = SpeakSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        audio = VoiceShoppingService().speak(
            serializer.validated_data["text"], language=serializer.validated_data.get("language", "")
        )
        response = HttpResponse(audio.data, content_type=audio.content_type)
        response["Cache-Control"] = "no-store"
        return response


class VoiceSessionSerializer(serializers.ModelSerializer):
    turns = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = AIConversation
        fields = ["id", "title", "language", "turns", "created_at", "updated_at"]


class VoiceSessionViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """The signed-in customer's own voice sessions (newest first). Someone else's id gives 404."""

    permission_classes = [IsAuthenticated]
    serializer_class = VoiceSessionSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AIConversation.objects.none()
        qs = AIConversation.objects.filter(user=self.request.user, kind=AIConversation.Kind.VOICE)
        if self.action == "list":
            return qs.annotate(turns=Count("messages") / 2).order_by("-updated_at", "-id")
        return qs.prefetch_related(Prefetch("messages", queryset=AIMessage.objects.order_by("created_at", "id")))

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def retrieve(self, request, pk=None):
        """What was said and answered, turn by turn (the words only; product cards are not rebuilt)."""
        conversation = self.get_object()
        turns, said = [], None
        for message in conversation.messages.all():
            if message.role == AIMessage.Role.USER:
                said = message
            elif message.role == AIMessage.Role.ASSISTANT and said is not None:
                payload = message.payload or {}
                turns.append(
                    {
                        "transcript": said.content,
                        "reply": message.content,
                        "intent": payload.get("intent", ""),
                        "language": payload.get("language", ""),
                        "created_at": said.created_at,
                    }
                )
                said = None
        return Response({**VoiceSessionSerializer(conversation).data, "turns": turns})

    @extend_schema(request=None, responses={204: None})
    @action(detail=False, methods=["post"])
    def clear(self, request):
        """Delete every voice session of this customer."""
        self.get_queryset().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
