from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ConflictError, NotFoundError
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
    return message
