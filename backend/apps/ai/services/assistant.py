"""HardwareAssistantService: one customer message in, one grounded, recorded answer out."""

import logging

from django.conf import settings

from integrations.llm import get_llm_provider

from . import vocabulary as V
from .conversation import AIConversationService
from .intent import IntentService
from .recommend import RecommendationService
from .retrieval import CatalogRetrievalService
from .schemas import LANGUAGES, AssistantReply, Intent, Understanding

logger = logging.getLogger(__name__)


class HardwareAssistantService:
    def __init__(self, provider=None):
        self.provider = provider or get_llm_provider()
        self.intents = IntentService(self.provider)
        self.catalog = CatalogRetrievalService()
        self.recommendations = RecommendationService(self.provider)
        self.conversations = AIConversationService()

    # --- Public -----------------------------------------------------------------------------------

    def status(self) -> dict:
        """What the page shows before the first message. Never exposes keys or URLs."""
        provider = self.provider
        return {
            "ai_mode": "llm" if provider.available else "basic",
            "provider": provider.name,
            "model": provider.model if provider.available else "",
            "languages": list(LANGUAGES),
            "suggested_prompts": V.SUGGESTED_PROMPTS,
            "greeting": {lang: V.text(lang, "greeting") for lang in LANGUAGES},
            "max_products": settings.AI_ASSISTANT_MAX_PRODUCTS,
        }

    def ask(self, conversation, text: str, *, language_hint: str = "") -> tuple[AssistantReply, object, object]:
        """Answer `text` inside `conversation`; returns the reply and the two stored messages."""
        history = self.conversations.history(conversation)
        reply = self.answer(text, history=history, language_hint=language_hint or conversation.language)
        user_message, assistant_message = self.conversations.record(conversation, text, reply)
        return reply, user_message, assistant_message

    def answer(self, text: str, *, history: list[dict] | None = None, language_hint: str = "") -> AssistantReply:
        """The whole pipeline without storage (also what a voice front end would call)."""
        understood = self.intents.understand(text, history=history, language_hint=language_hint)
        understood = self._carry_context(understood, history or [])
        matches, missing = [], []
        if not understood.needs_clarification:
            matches, missing = self._retrieve(understood)
        reply = self.recommendations.compose(understood, matches, missing)
        if understood.model_failed or reply.model_failed:
            # The configured model was needed and could not answer: the reply is the basic one, say so.
            reply.notice = V.text(understood.language, "notice_unavailable")
        return reply

    # --- Steps ------------------------------------------------------------------------------------

    def _retrieve(self, understood: Understanding):
        if understood.intent == Intent.BUDGET and understood.budget is not None and not understood.terms:
            return self.catalog.within_budget(understood.budget, language=understood.language), []
        if not understood.terms:
            return [], []
        matches, missing = self.catalog.find(understood.terms, budget=understood.budget, language=understood.language)
        if not matches and understood.budget is not None:
            # Nothing within the budget: show the matches anyway, the message says what fits.
            matches, missing = self.catalog.find(understood.terms, language=understood.language)
        return matches, missing

    @staticmethod
    def _carry_context(understood: Understanding, history: list[dict]) -> Understanding:
        """A short answer to our follow-up question ("walls, 12x15") inherits the previous topic."""
        if not history or len(understood.terms) >= 3 or understood.topics:
            return understood
        last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
        if not last_user:
            return understood
        from .intent import _search_words, _topics

        previous_topics = _topics(last_user)
        if not previous_topics:
            return understood
        understood.topics = previous_topics
        for key in previous_topics:
            for term in V.TOPICS[key].terms:
                if term not in understood.terms:
                    understood.terms.append(term)
        for term in _search_words(last_user)[0]:
            if term not in understood.terms:
                understood.terms.append(term)
        understood.needs_clarification = False
        understood.question = ""
        if understood.intent == Intent.PRODUCT_SEARCH:
            understood.intent = V.TOPICS[previous_topics[0]].intent
        return understood
