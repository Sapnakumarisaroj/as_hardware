from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ConflictError, NotFoundError, ServiceError
from apps.orders.models import Order

from .models import SupportConversation, SupportMessage


@transaction.atomic
def start_conversation(*, user, subject: str, message: str, order_number: str = "") -> SupportConversation:
    order = None
    if order_number:
        order = Order.objects.filter(order_number=order_number, user=user).first()
        if order is None:
            raise NotFoundError("Order not found.")
    conversation = SupportConversation.objects.create(
        user=user, subject=subject.strip(), order=order, channel="in_app", last_message_at=timezone.now()
    )
    SupportMessage.objects.create(
        conversation=conversation, sender_type=SupportMessage.Sender.CUSTOMER, sender=user, body=message.strip()
    )
    return conversation


@transaction.atomic
def start_product_enquiry(*, user, product_id: int, message: str) -> SupportConversation:
    """A signed-in customer's question about one product, from the product page."""
    from apps.catalog.models import Product

    product = Product.objects.filter(pk=product_id, is_active=True, is_published=True).first()
    if product is None:
        raise NotFoundError("Product not found.")
    conversation = SupportConversation.objects.create(
        user=user,
        subject=f"Question about {product.name}"[:150],
        product=product,
        channel="in_app",
        last_message_at=timezone.now(),
    )
    SupportMessage.objects.create(
        conversation=conversation, sender_type=SupportMessage.Sender.CUSTOMER, sender=user, body=message.strip()
    )
    return conversation


# --- Attachments (WhatsApp photos and documents) -------------------------------------------------

ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


class AttachmentUnavailable(ServiceError):
    status_code = 404
    default_code = "attachment_unavailable"
    default_detail = "This file can't be opened here."


def attachment_file(message: SupportMessage, index: int):
    """The bytes and type of one attachment, fetched from the messaging provider. Only the allowed
    types (JPEG, PNG, WebP, PDF) and up to WHATSAPP_MEDIA_MAX_BYTES are passed on."""
    from django.conf import settings

    from integrations.messaging import MessagingError, get_whatsapp_provider

    attachments = message.attachments if isinstance(message.attachments, list) else []
    if not 0 <= index < len(attachments) or not isinstance(attachments[index], dict):
        raise NotFoundError("Attachment not found.")
    attachment = attachments[index]
    declared = str(attachment.get("mime_type") or "").split(";")[0].strip().lower()
    if declared not in ALLOWED_MEDIA_TYPES or not attachment.get("media_id"):
        raise AttachmentUnavailable("This kind of file can't be opened here. Open it in WhatsApp Manager.")
    provider = get_whatsapp_provider()
    try:
        media = provider.fetch_media(str(attachment["media_id"]), max_bytes=settings.WHATSAPP_MEDIA_MAX_BYTES)
    except MessagingError as exc:
        raise AttachmentUnavailable(str(exc)) from exc
    if media is None:
        raise AttachmentUnavailable("The file is kept by WhatsApp; this messaging provider can't fetch it.")
    mime = media.mime_type or declared
    if mime not in ALLOWED_MEDIA_TYPES or len(media.content) > settings.WHATSAPP_MEDIA_MAX_BYTES:
        raise AttachmentUnavailable("This file can't be opened here. Open it in WhatsApp Manager.")
    return media.content, mime


@transaction.atomic
def post_message(conversation: SupportConversation, *, sender, sender_type: str, body: str) -> SupportMessage:
    conversation = SupportConversation.objects.select_for_update().get(pk=conversation.pk)
    if conversation.status == SupportConversation.Status.CLOSED:
        raise ConflictError("This conversation is closed. Please start a new one.", code="conversation_closed")
    message = SupportMessage.objects.create(
        conversation=conversation, sender_type=sender_type, sender=sender, body=body.strip()
    )
    conversation.last_message_at = message.created_at
    if sender_type == SupportMessage.Sender.CUSTOMER and conversation.status != SupportConversation.Status.OPEN:
        conversation.status = SupportConversation.Status.OPEN
    conversation.save(update_fields=["last_message_at", "status", "updated_at"])
    if sender_type == SupportMessage.Sender.AGENT and conversation.user_id:
        _tell_customer(conversation, message, sender)
    return message


def _tell_customer(conversation: SupportConversation, message: SupportMessage, agent) -> None:
    """A staff reply reaches the customer in the app, by email and (if they opted in) on WhatsApp."""
    from apps.notifications.services import notify

    text = message.body if len(message.body) <= 300 else message.body[:297].rstrip() + "…"
    notify(
        conversation.user,
        event="support.reply",
        context={
            "subject": conversation.subject or "your message",
            "agent_name": (getattr(agent, "full_name", "") or "").split(" ")[0] or "Our team",
            "message": text,
        },
        data={"conversation_id": conversation.pk},
        key=f"support:{message.pk}",
    )
