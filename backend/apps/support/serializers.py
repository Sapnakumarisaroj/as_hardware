from rest_framework import serializers

from .models import SupportConversation, SupportMessage


def product_ref(conversation) -> dict | None:
    """The product a conversation is about (product-page or WhatsApp enquiry), for links."""
    product = conversation.product if conversation.product_id else None
    return {"id": product.pk, "name": product.name, "slug": product.slug} if product else None


class SupportMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportMessage
        fields = ["id", "sender_type", "body", "attachments", "created_at"]
        read_only_fields = fields


class SupportConversationSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True, default=None)
    product = serializers.SerializerMethodField()

    class Meta:
        model = SupportConversation
        fields = ["id", "subject", "channel", "status", "order_number", "product", "last_message_at", "created_at"]
        read_only_fields = fields

    def get_product(self, obj) -> dict | None:
        return product_ref(obj)


class SupportConversationDetailSerializer(SupportConversationSerializer):
    messages = SupportMessageSerializer(many=True, read_only=True)

    class Meta(SupportConversationSerializer.Meta):
        fields = SupportConversationSerializer.Meta.fields + ["messages"]
        read_only_fields = fields


class StartConversationSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=150)
    message = serializers.CharField(max_length=4000)
    order_number = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")


class ProductEnquirySerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    message = serializers.CharField(max_length=2000)


class PostMessageSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=4000)
