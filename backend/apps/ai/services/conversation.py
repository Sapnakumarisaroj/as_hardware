"""AIConversationService: the records of a customer's conversations with the assistant.

A conversation belongs to one user. Every message is stored as it was shown; an assistant
message keeps the product references it showed (`product_refs`) so the answer can be audited
and re-rendered from live catalogue rows, and the structured parts (`payload`).
"""

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import NotFoundError

from ..models import AIConversation, AIMessage
from .schemas import AssistantReply

MAX_MESSAGE_LENGTH = 1000
HISTORY_TURNS = 6


class AIConversationService:
    @staticmethod
    def for_user(user):
        return AIConversation.objects.filter(user=user, kind=AIConversation.Kind.ASSISTANT)

    def get(self, user, conversation_id) -> AIConversation:
        conversation = self.for_user(user).filter(pk=conversation_id).first()
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        return conversation

    def start(self, user, *, language: str = "en") -> AIConversation:
        return AIConversation.objects.create(user=user, kind=AIConversation.Kind.ASSISTANT, language=language)

    def history(self, conversation: AIConversation) -> list[dict]:
        """The last turns as chat messages (for the model's context)."""
        rows = conversation.messages.filter(role__in=(AIMessage.Role.USER, AIMessage.Role.ASSISTANT)).order_by(
            "-created_at", "-id"
        )[:HISTORY_TURNS]
        return [{"role": m.role, "content": m.content} for m in reversed(list(rows))]

    @transaction.atomic
    def record(self, conversation: AIConversation, text: str, reply: AssistantReply) -> tuple[AIMessage, AIMessage]:
        user_message = AIMessage.objects.create(conversation=conversation, role=AIMessage.Role.USER, content=text)
        assistant_message = AIMessage.objects.create(
            conversation=conversation,
            role=AIMessage.Role.ASSISTANT,
            content=reply.message,
            product_refs=reply.product_refs(),
            payload={
                "intent": reply.intent,
                "language": reply.language,
                "ai_mode": reply.ai_mode,
                "notice": reply.notice,
                "questions": reply.questions,
                "actions": reply.actions,
                "knowledge": reply.knowledge,
                "safety": reply.safety,
                "estimate": reply.estimate,
            },
            provider=reply.provider,
            model=reply.model,
            tokens_in=reply.tokens_in,
            tokens_out=reply.tokens_out,
        )
        changes = {"updated_at": timezone.now()}
        if not conversation.title:
            changes["title"] = text[:60].strip()
        if conversation.language != reply.language:
            changes["language"] = reply.language
        AIConversation.objects.filter(pk=conversation.pk).update(**changes)
        for key, value in changes.items():
            setattr(conversation, key, value)
        return user_message, assistant_message

    def clear(self, conversation: AIConversation) -> None:
        conversation.messages.all().delete()
        AIConversation.objects.filter(pk=conversation.pk).update(title="", updated_at=timezone.now())

    def delete(self, conversation: AIConversation) -> None:
        conversation.delete()
