"""In-app support conversations. Customers see only their own; admins see all.
WhatsApp/call channels plug into the same models in Phase 20."""

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import NotFoundError
from apps.core.permissions import IsStaffRole, is_admin, managed_store_ids

from . import services
from .models import SupportConversation, SupportMessage
from .serializers import (
    PostMessageSerializer,
    ProductEnquirySerializer,
    StartConversationSerializer,
    SupportConversationDetailSerializer,
    SupportConversationSerializer,
    SupportMessageSerializer,
)


class SupportConversationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SupportConversation.objects.none()
        qs = SupportConversation.objects.select_related("order", "product").prefetch_related("messages")
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


class ProductEnquiryView(APIView):
    """ "Ask about this product": opens a support conversation linked to the product."""

    @extend_schema(request=ProductEnquirySerializer, responses={201: SupportConversationDetailSerializer})
    def post(self, request):
        serializer = ProductEnquirySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = services.start_product_enquiry(user=request.user, **serializer.validated_data)
        return Response(SupportConversationDetailSerializer(conversation).data, status=status.HTTP_201_CREATED)


class MessageAttachmentView(APIView):
    """Staff only: stream a photo/PDF a customer sent on WhatsApp (fetched from the provider).
    Store managers may open only conversations about their stores' orders, like the support inbox."""

    permission_classes = [IsStaffRole]

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    def get(self, request, message_id: int, index: int):
        qs = SupportMessage.objects.select_related("conversation__order")
        allowed = managed_store_ids(request.user)
        if allowed is not None:
            qs = qs.filter(conversation__order__store_id__in=allowed)
        message = qs.filter(pk=message_id).first()
        if message is None:
            raise NotFoundError("Attachment not found.")
        content, mime = services.attachment_file(message, index)
        response = HttpResponse(content, content_type=mime)
        response["Content-Disposition"] = "inline"
        response["Cache-Control"] = "private, max-age=300"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "sandbox; default-src 'none'"
        return response
