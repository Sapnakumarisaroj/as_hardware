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
