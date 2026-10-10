"""RecommendationService: turn what was understood and what was found into an answer.

The answer is assembled from parts that are each grounded:
- the topic summary / general knowledge (fixed text, marked as general),
- the safety note (fixed text),
- the products (database rows, with a reason per product),
- the budget arithmetic (Decimal, done here, never by a model),
- a quantity estimate for painting (a formula, labelled as an estimate).

With a model configured, the model writes two of the parts and nothing else: the sentences that
recommend the products found (it may name only those products and may not write numbers of its
own), and an explanation when a general question has no entry in the knowledge base (marked as
general information, no products). Anything that fails these checks is dropped and the fixed
text stands. Product cards are built from the rows regardless of what the model wrote.
"""

import json
import logging
import math
import re
from decimal import Decimal
from urllib.parse import quote

from integrations.llm import ChatOptions, LLMError, LLMUnavailable, get_llm_provider

from ..quantity import formulas
from . import grounding
from . import vocabulary as V
from .schemas import AssistantReply, Intent, ProductMatch, Understanding

logger = logging.getLogger(__name__)


_LLM_RECOMMEND = """You are the assistant of an Indian hardware shop. The customer asked something and the shop
found these products for it. Write 1 to 3 short, friendly sentences recommending them, in the language given
("en" = English, "hi" = Hindi in Devanagari script, "hinglish" = Hindi written in Latin letters).
Rules: mention products by their exact names from the list and nothing else; never write prices, stock,
delivery times or numbers that are not part of a product name; no markdown, no lists.
Reply with ONE JSON object: {"message": "..."}"""

_LLM_EXPLAIN = """You are the assistant of an Indian hardware shop. Answer the customer's general hardware question in
2 to 4 plain sentences in the language given ("en" English, "hi" Hindi in Devanagari, "hinglish" Hindi in Latin
letters). Give general knowledge only: do not name products, brands, prices or availability. If the work is
dangerous (electrical, gas, structural), say a qualified professional should do it. If you are not sure, say so.
Reply with ONE JSON object: {"message": "..."}"""


def rupees(value: Decimal) -> str:
    return f"₹{value:,.0f}" if value == value.to_integral() else f"₹{value:,.2f}"


def paint_estimate(dimensions: tuple[float, float], language: str) -> dict:
    length, width = dimensions
    # The Quantity AI formulas (Phase 20): one door and one window taken off, two coats, labelled defaults.
    walls = formulas.wall_area(length, width)
    area = walls.amount
    litres = math.ceil(round(formulas.paint_litres(area).amount, 6))
    primer = math.ceil(round(formulas.primer_litres(area).amount, 6))
    return {
        "kind": "paint",
        "length_ft": length,
        "width_ft": width,
        "height_ft": formulas.WALL_HEIGHT_FT,
        "wall_area_sqft": round(area),
        "emulsion_litres": litres,
        "primer_litres": primer,
        "is_estimate": True,
        "calculator_path": f"/quantity?q={quote(f'paint for a {_num(length)}x{_num(width)} room')}",
        "text": V.text(
            language,
            "estimate_paint",
            length=_num(length),
            width=_num(width),
            height=formulas.WALL_HEIGHT_FT,
            area=round(area),
            litres=litres,
            primer=primer,
        ),
    }


def _num(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def _mentions_money(text: str) -> bool:
    """₹, "Rs.", "INR", "500/-", "rupaye", "कीमत", "price"… (Devanagari digits included): see `grounding`."""
    return grounding.mentions_money(text) or bool(re.search(r"\bprice", text, re.IGNORECASE))


class RecommendationService:
    def __init__(self, provider=None):
        self.provider = provider or get_llm_provider()

    def compose(self, understood: Understanding, matches: list[ProductMatch], missing: list[str]) -> AssistantReply:
        lang = understood.language
        reply = AssistantReply(intent=understood.intent, language=lang, products=matches)
        parts: list[str] = []
        intro = ""

        # 1. What the job needs (fixed, general text)
        for key in understood.topics[:2]:
            topic = V.TOPICS[key]
            parts.append(topic.summary.get(lang) or topic.summary["en"])
        for key in understood.concepts[:2]:
            concept = V.KNOWLEDGE[key]
            reply.knowledge.append({"title": concept.title, "text": concept.text, "source": "knowledge_base"})
        if reply.knowledge:
            parts.append(V.text(lang, "knowledge"))
            parts.extend(f"{k['title']}: {k['text']}" for k in reply.knowledge)

        # 2. A quantity estimate, when sizes were given for painting
        if understood.dimensions and ("painting" in understood.topics or understood.intent == Intent.QUANTITY):
            reply.estimate = paint_estimate(understood.dimensions, lang)
            parts.append(f"{reply.estimate['text']} {V.text(lang, 'estimate_label')}")
        elif understood.intent == Intent.QUANTITY and not understood.dimensions:
            parts.append(V.text(lang, "quantity"))
        if understood.intent == Intent.COMPATIBILITY and not matches:
            parts.append(V.text(lang, "compat"))

        # 3. The products, and the budget arithmetic
        none_line = ""
        if understood.needs_clarification and understood.question:
            parts.append(understood.question)
            reply.questions.append(understood.question)
        elif matches:
            if understood.budget is not None:
                intro = V.text(lang, "found_budget", budget=rupees(understood.budget))
                parts.append(intro)
                if understood.intent != Intent.BUDGET:
                    self._budget_lines(understood, matches, parts)
            else:
                intro = V.text(lang, "found")
                parts.append(intro)
            if missing and understood.intent in (Intent.PROJECT_HELP, Intent.REPAIR_HELP):
                parts.append(V.text(lang, "partial", missing=", ".join(missing[:4])))
            if understood.question:  # e.g. "what are you looking for within ₹1,000?"
                parts.append(understood.question)
                reply.questions.append(understood.question)
        elif understood.intent != Intent.GENERAL_HARDWARE_QUESTION or not reply.knowledge:
            terms = ", ".join(understood.terms[:4])
            none_line = V.text(lang, "none_terms", terms=terms) if terms else V.text(lang, "none")
            parts.append(none_line)

        # 4. Safety (fixed text; always last, always kept)
        for key in understood.safety[:2]:
            note = V.SAFETY_TEXT[key]
            reply.safety.append(note.get(lang) or note["en"])
        parts.extend(reply.safety)

        reply.message = "\n\n".join(p for p in parts if p)
        reply.actions = self._actions(matches, lang)
        if self.provider.available:
            self._with_model(reply, understood, matches, parts, intro=intro, none_line=none_line)
        return reply

    # --- basic mode pieces ---------------------------------------------------------------------------

    def _budget_lines(self, understood: Understanding, matches: list[ProductMatch], parts: list[str]) -> None:
        """One item per search word, cheapest first, as long as they add up within the budget."""
        budget = understood.budget
        assert budget is not None
        chosen: list[ProductMatch] = []
        total = Decimal("0")
        for term in dict.fromkeys(m.term for m in matches):
            candidates = sorted((m for m in matches if m.term == term), key=lambda m: m.price)
            if candidates and total + candidates[0].price <= budget:
                chosen.append(candidates[0])
                total += candidates[0].price
        for match in chosen:
            match.reason = f"{match.reason} · {V.text(understood.language, 'reason_budget')}"
        if len(chosen) > 1:
            parts.append(V.text(understood.language, "kit_total", total=rupees(total), budget=rupees(budget)))

    @staticmethod
    def _actions(matches: list[ProductMatch], lang: str) -> list[dict]:
        if not matches:
            return []
        actions = [
            {"type": "add_to_cart", "variant_id": m.variant_id, "product_id": m.product.pk, "quantity": 1}
            for m in matches
        ]
        if len(matches) > 1:
            actions.append(
                {"type": "add_all", "label": V.text(lang, "add_all"), "variant_ids": [m.variant_id for m in matches]}
            )
        return actions

    # --- model pieces --------------------------------------------------------------------------------

    def _with_model(self, reply, understood, matches, parts, *, intro: str, none_line: str) -> None:
        """Where a model helps: the recommendation sentences, and explanations we have no text for."""
        replacement = None
        if matches and intro and intro in parts:
            replacement = self._recommendation_text(reply, understood, matches)
            if replacement:
                parts[parts.index(intro)] = replacement
        elif understood.intent == Intent.GENERAL_HARDWARE_QUESTION and not reply.knowledge and not matches:
            replacement = self._explanation(reply, understood)
            if replacement:
                if none_line in parts:
                    parts.remove(none_line)
                parts.insert(0, f"{V.text(understood.language, 'knowledge')}\n\n{replacement}")
                reply.knowledge.append({"title": "", "text": replacement, "source": "model"})
        if replacement:
            reply.message = "\n\n".join(p for p in parts if p)
            reply.ai_mode = "llm"

    def _ask_model(self, reply: AssistantReply, system: str, prompt: dict, *, max_tokens: int) -> str | None:
        try:
            out = self.provider.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                ChatOptions(json=True, max_tokens=max_tokens, temperature=0.4),
            )
            message = out.json().get("message")
        except (LLMUnavailable, LLMError) as exc:
            logger.info("LLM answer skipped: %s", exc)
            reply.model_failed = True
            return None
        except Exception:
            logger.exception("LLM answer failed")
            reply.model_failed = True
            return None
        if not isinstance(message, str) or len(message.strip()) < 10 or _mentions_money(message):
            return None
        reply.provider, reply.model = out.provider, out.model
        reply.tokens_in += out.tokens_in
        reply.tokens_out += out.tokens_out
        return message.strip()[:1200]

    def _recommendation_text(self, reply, understood: Understanding, matches: list[ProductMatch]) -> str | None:
        """The model may only talk about the listed products, by name, without numbers of its own."""
        names = [m.product.name for m in matches]
        prompt = {
            "language": understood.language,
            "customer_asked_about": understood.intent.replace("_", " ").lower(),
            "products": [{"name": m.product.name, "why": m.reason} for m in matches],
        }
        message = self._ask_model(reply, _LLM_RECOMMEND, prompt, max_tokens=220)
        if message is None:
            return None
        lowered = message.lower()
        if not any(name.lower() in lowered for name in names):
            return None  # it did not talk about what we found
        if grounding.ungrounded_numbers(message, " ".join(names)):
            return None  # a number that is not part of a product name: an invented spec, id or price
        return message

    def _explanation(self, reply, understood: Understanding) -> str | None:
        """General knowledge in the model's words: no money, and no number the customer didn't say (a model's
        number would read as a specification or a price the shop gave)."""
        prompt = {"language": understood.language, "question": understood.text}
        message = self._ask_model(reply, _LLM_EXPLAIN, prompt, max_tokens=260)
        if message is None or not grounding.grounded(message, understood.text):
            return None
        return message
