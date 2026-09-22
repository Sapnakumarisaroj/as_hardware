"""The signed-in user's saved AI conversations (read/delete). Creating conversations — i.e. the
assistant itself — arrives in Phase 12; there is no fake AI behind these endpoints."""

from rest_framework import mixins, serializers, viewsets

from .models import AIConversation, AIMessage


class AIMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIMessage
        fields = ["id", "role", "content", "product_refs", "created_at"]


class AIConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIConversation
        fields = ["id", "kind", "language", "title", "created_at", "updated_at"]


class AIConversationDetailSerializer(AIConversationSerializer):
    # Tool calls / token counts are internal and not exposed to customers.
    messages = serializers.SerializerMethodField()

    class Meta(AIConversationSerializer.Meta):
        fields = AIConversationSerializer.Meta.fields + ["messages"]

    def get_messages(self, obj) -> list[dict]:
        visible = [m for m in obj.messages.all() if m.role in (AIMessage.Role.USER, AIMessage.Role.ASSISTANT)]
        return AIMessageSerializer(visible, many=True).data


class AIConversationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AIConversation.objects.none()
        return AIConversation.objects.filter(user=self.request.user).prefetch_related("messages")

    def get_serializer_class(self):
        return AIConversationSerializer if self.action == "list" else AIConversationDetailSerializer
