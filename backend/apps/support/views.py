"""In-app support conversations. Customers see only their own; admins see all.
WhatsApp/call channels plug into the same models in Phase 20."""

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.permissions import is_admin

from . import services
from .models import SupportConversation, SupportMessage
from .serializers import (
    PostMessageSerializer,
    StartConversationSerializer,
    SupportConversationDetailSerializer,
    SupportConversationSerializer,
    SupportMessageSerializer,
)


class SupportConversationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SupportConversation.objects.none()
        qs = SupportConversation.objects.select_related("order").prefetch_related("messages")
        return qs if is_admin(self.request.user) else qs.filter(user=self.request.user)

    def get_serializer_class(self):
        return SupportConversationSerializer if self.action == "list" else SupportConversationDetailSerializer

    @extend_schema(request=StartConversationSerializer, responses={201: SupportConversationDetailSerializer})
    def create(self, request):
        serializer = StartConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = services.start_conversation(user=request.user, **serializer.validated_data)
        return Response(SupportConversationDetailSerializer(conversation).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=PostMessageSerializer, responses={201: SupportMessageSerializer})
    @action(detail=True, methods=["post"])
    def messages(self, request, pk=None):
        conversation = self.get_object()
        serializer = PostMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        is_owner = conversation.user_id == request.user.id
        sender_type = SupportMessage.Sender.CUSTOMER if is_owner else SupportMessage.Sender.AGENT
        message = services.post_message(
            conversation, sender=request.user, sender_type=sender_type, body=serializer.validated_data["body"]
        )
        return Response(SupportMessageSerializer(message).data, status=status.HTTP_201_CREATED)
