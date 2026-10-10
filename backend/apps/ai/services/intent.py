# ruff: noqa: E501
"""IntentService: what does the customer want?

Two layers. The rules run every time and are enough for the basic mode: they detect the
language, the intent, the budget, room sizes, the known jobs (topics), general-knowledge
questions and safety-relevant work, and turn the customer's words into English catalogue
search words. When a language model is configured it is asked the same questions and its
answer *adds* to the rules (extra search words, a better intent when the rules found nothing,
a follow-up question in the customer's language). The model can't add products, only words
to search with.

Voice questions (Phase 18, `voice.py`) reach it through `HardwareAssistantService.answer()`.
"""

import logging
import re
from decimal import Decimal

from integrations.llm import ChatOptions, LLMError, LLMUnavailable, get_llm_provider

from . import grounding
from . import vocabulary as V
from .schemas import LANGUAGES, Intent, Understanding

logger = logging.getLogger(__name__)

BUDGET = re.compile(
    r"(?:₹|rs\.?|rupees?|rupaye|inr)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:₹|rs\.?|rupees?|rupaye|inr|rupay|रुपये|रुपए|rs)\b",
    re.IGNORECASE,
)
BUDGET_WORDS = re.compile(
    r"\b(budget|under|below|within|upto|up to|max|maximum|less than|ke andar|se kam|tak|तक|के भीतर|से कम)\b",
    re.IGNORECASE,
)
BARE_NUMBER = re.compile(r"\b(\d{3,6})\b")
DIMENSIONS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:x|×|by|\*)\s*(\d+(?:\.\d+)?)", re.IGNORECASE)

INTENT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    (
        Intent.GENERAL_HARDWARE_QUESTION,
        (
            r"^\s*(what|which|why|how|when)\b.*\?",
            r"\bwhat\s+(is|are|does)\b",
            r"\bdifference\b",
            r"\bexplain\b",
            r"\bmeaning\b",
            r"\bkya\s+hota\s+hai",
            r"\bkya\s+hai\b",
            r"क्या\s*(होता|है)",
            r"\bhow\s+to\s+use\b",
            r"\bkaise\s+use\b",
            r"\bkaise\s+kaam",
            r"कैसे\s*(काम|इस्तेमाल)",
        ),
    ),
    (
        Intent.COMPATIBILITY,
        (
            r"compatib",
            r"\bfit\b",
            r"\bfits\b",
            r"work\s+with",
            r"suitable\s+for",
            r"\bmatch\b",
            r"chalega",
            r"\bsaath\s+chal",
            r"\bsahi\s+rahega",
            r"go\s+with",
        ),
    ),
    (
        Intent.QUANTITY,
        (
            r"how\s+(much|many)",
            r"\bkitna\b",
            r"\bkitne\b",
            r"\bkitni\b",
            r"कितन",
            r"\bquantity\b",
            r"\bqty\b",
            r"\bsq\.?\s*ft",
            r"\bsquare\s+feet",
            r"\blitres?\b",
            r"\bliters?\b",
            r"\bbags?\s+of\b",
        ),
    ),
    (
        Intent.REPAIR_HELP,
        (
            r"\brepair",
            r"\bfix\b",
            r"\bfixing\b",
            r"\bleak",
            r"\bbroken\b",
            r"\bbroke\b",
            r"\bnot\s+working",
            r"\bstuck\b",
            r"\bkharab\b",
            r"\btoot",
            r"\btuta\b",
            r"\btheek\b",
            r"\bthik\b",
            r"\bmarammat",
            r"मरम्मत",
            r"ठीक",
            r"खराब",
            r"टूट",
            r"tapak",
            r"टपक",
            r"\bdripp?ing\b",
            r"\bjam(med)?\b",
            r"\bcrack",
        ),
    ),
    (
        Intent.PROJECT_HELP,
        (
            r"\bbuild",
            r"\binstall",
            r"\bproject\b",
            r"\bmake\s+a\b",
            r"\bmaking\b",
            r"\bset\s+up\b",
            r"\bkit\b",
            r"\bmaterial",
            r"\bsaman\b",
            r"\bsamaan\b",
            r"सामान",
            r"\bbanana\b",
            r"\bbanane\b",
            r"\blagana\b",
            r"\blagane\b",
            r"बनाना",
            r"लगाना",
            r"\bpaint",
            r"\brang\b",
            r"रंग",
            r"\brenovat",
            r"\bwiring\b",
            r"\bshelf\b",
            r"\bshelves\b",
        ),
    ),
]

_LLM_SYSTEM = """You help a hardware shop understand a customer's message. The shop sells tools, electrical,
plumbing, construction and safety products. Reply with ONE JSON object and nothing else:
{"intent": "PRODUCT_SEARCH" | "PROJECT_HELP" | "REPAIR_HELP" | "COMPATIBILITY" | "QUANTITY" | "BUDGET" | "GENERAL_HARDWARE_QUESTION",
 "language": "en" | "hi" | "hinglish",
 "search_terms": [up to 6 short ENGLISH product words a shop would stock for this, e.g. "PTFE tape", "impact drill", "wall plugs"],
 "budget": number or null,
 "needs_clarification": true if the request is too vague to pick products,
 "question": one short follow-up question in the customer's language, or null}
Never invent product names, prices or availability."""


def detect_language(text: str) -> str:
    if V.DEVANAGARI.search(text):
        return "hi"
    words = set(re.findall(r"[a-z]+", text.lower()))
    hits = len(words & V.HINGLISH_MARKERS)
    if hits >= 2 or (hits == 1 and len(words) <= 4):
        return "hinglish"
    return "en"


def parse_budget(text: str) -> Decimal | None:
    lowered = text.lower()
    match = BUDGET.search(lowered)
    raw = None
    if match:
        raw = match.group(1) or match.group(2)
    elif BUDGET_WORDS.search(lowered):
        if number := BARE_NUMBER.search(lowered):
            raw = number.group(1)
    if not raw:
        return None
    try:
        value = Decimal(raw.replace(",", ""))
    except ArithmeticError:
        return None
    return value if 0 < value < Decimal("10000000") else None


def parse_dimensions(text: str) -> tuple[float, float] | None:
    match = DIMENSIONS.search(text)
    if not match:
        return None
    length, width = float(match.group(1)), float(match.group(2))
    if 1 <= length <= 200 and 1 <= width <= 200:
        return length, width
    return None


def _search_words(text: str) -> tuple[list[str], list[str]]:
    """Catalogue search words from the customer's words; also which customer words were used."""
    lowered = text.lower()
    used, terms = [], []
    covered = [False] * len(lowered)
    for phrase in sorted(V.WORDS, key=len, reverse=True):
        for match in re.finditer(rf"(?<![\w]){re.escape(phrase)}(?![\w])", lowered):
            start, end = match.span()
            if any(covered[start:end]):
                continue
            for i in range(start, end):
                covered[i] = True
            used.append(phrase)
            for term in V.WORDS[phrase]:
                if term not in terms:
                    terms.append(term)
    return terms, used


FILLER = {
    "i",
    "me",
    "my",
    "we",
    "our",
    "you",
    "need",
    "needs",
    "want",
    "wants",
    "would",
    "like",
    "looking",
    "look",
    "find",
    "get",
    "buy",
    "show",
    "give",
    "please",
    "help",
    "some",
    "any",
    "one",
    "something",
    "thing",
    "things",
    "item",
    "items",
    "do",
    "have",
    "has",
    "is",
    "are",
    "can",
    "could",
    "should",
    "there",
    "this",
    "that",
    "it",
    "its",
    "at",
    "as",
    "or",
    "if",
    "so",
    "up",
    "out",
    "from",
    "about",
    "what",
    "which",
    "where",
    "when",
    "how",
    "kya",
    "hai",
    "hain",
    "ho",
    "toh",
    "bhi",
    "koi",
    "ek",
    "mera",
    "meri",
    "mere",
    "mujhe",
    "chahiye",
    "chaiye",
    "dedo",
    "de",
    "batao",
    "dikhao",
    "liye",
    "ke",
    "ka",
    "ki",
    "ko",
    "se",
    "mein",
    "par",
    "aur",
    "ya",
    "hi",
    "kuch",
    "saman",
    "samaan",
    "material",
    "hardware",
}


def _leftover_words(text: str) -> list[str]:
    """The customer's own words, minus filler, as search words (up to four)."""
    from apps.catalog.search import tokenize

    words = [
        w for w in tokenize(text) if w not in FILLER and w not in V.GENERIC_WORDS and not w.isdigit() and len(w) > 2
    ]
    return words[:4]


def _topics(text: str) -> list[str]:
    lowered = text.lower()
    return [key for key, topic in V.TOPICS.items() if any(re.search(p, lowered) for p in topic.patterns)]


def _concepts(text: str) -> list[str]:
    lowered = text.lower()
    return [key for key, concept in V.KNOWLEDGE.items() if any(re.search(p, lowered) for p in concept.patterns)]


def _safety(text: str, topics: list[str]) -> list[str]:
    lowered = text.lower()
    found = [key for key, patterns in V.SAFETY_TRIGGERS.items() if any(re.search(p, lowered) for p in patterns)]
    for key in topics:
        safety = V.TOPICS[key].safety
        if safety and safety not in found:
            found.append(safety)
    return found


def _intent(text: str, *, terms: list[str], topics: list[str], concepts: list[str], budget) -> str:
    lowered = text.lower()
    for intent, patterns in INTENT_PATTERNS:
        if any(re.search(p, lowered) for p in patterns):
            if (
                intent == Intent.GENERAL_HARDWARE_QUESTION
                and not concepts
                and terms
                and not re.search(r"\bwhat\s+is\b|kya\s+h", lowered)
            ):
                continue  # "which drill for concrete?" is a search, not a definition
            return intent
    if topics:
        return V.TOPICS[topics[0]].intent
    if budget is not None and len(terms) <= 1:
        return Intent.BUDGET
    return Intent.PRODUCT_SEARCH


def _is_vague(text: str, terms: list[str], used: list[str], topics: list[str]) -> tuple[bool, str]:
    """Too little to search well? Returns (vague, topic key that has a clarifying question)."""
    lowered = text.lower()
    for key in topics:
        topic = V.TOPICS[key]
        if not topic.clarify:
            continue
        specific = any(re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", lowered) for word in topic.specific)
        if not specific:
            return True, key
    if not terms:
        return True, ""
    if used and all(word in V.GENERIC_WORDS for word in used) and not topics:
        return True, ""
    return False, ""


class IntentService:
    def __init__(self, provider=None):
        self.provider = provider or get_llm_provider()

    def understand(self, text: str, *, history: list[dict] | None = None, language_hint: str = "") -> Understanding:
        """Rules first; a model, when configured, adds to what the rules found. Never raises."""
        text = (text or "").strip()
        result = self._rules(text, language_hint)
        # The model is asked only when the rules recognised nothing: a phrasing or a job the
        # vocabulary doesn't know. Recognised requests are answered at once, without a model call.
        recognised = not result.guessed and (
            result.terms or result.topics or result.concepts or (result.intent == Intent.BUDGET and result.budget)
        )
        if self.provider.available and not recognised:
            try:
                self._refine(result, text, history or [])
            except (LLMUnavailable, LLMError) as exc:
                logger.info("LLM understanding skipped: %s", exc)
                result.source = "rules"
                result.model_failed = True
            except Exception:  # a model answer must never break the assistant
                logger.exception("LLM understanding failed")
                result.source = "rules"
                result.model_failed = True
        return result

    # --- rules -------------------------------------------------------------------------------------

    def _rules(self, text: str, language_hint: str) -> Understanding:
        language = detect_language(text)
        if language == "en" and language_hint in LANGUAGES:
            language = language_hint
        terms, used = _search_words(text)
        topics = _topics(text)
        for key in topics:
            for term in V.TOPICS[key].terms:
                if term not in terms:
                    terms.append(term)
        concepts = _concepts(text)
        for key in concepts:
            for term in V.KNOWLEDGE[key].terms:
                if term not in terms:
                    terms.append(term)
        budget = parse_budget(text)
        dimensions = parse_dimensions(text)
        intent = _intent(text, terms=terms, topics=topics, concepts=concepts, budget=budget)
        guessed = False
        if not terms and not topics and not concepts and not used:
            # Words the vocabulary doesn't know: search the catalogue with them as they are.
            terms = _leftover_words(text)
            guessed = True
        vague, topic_key = _is_vague(text, terms, used, topics)
        question = ""
        if vague and topic_key:
            question = V.TOPICS[topic_key].clarify.get(language) or V.TOPICS[topic_key].clarify["en"]
        elif vague and intent == Intent.BUDGET and budget is not None:
            # Popular products within the budget are shown; the question is offered alongside.
            question = V.text(language, "budget_only", budget=_rupees(budget))
            vague = False
        elif vague and intent not in (Intent.GENERAL_HARDWARE_QUESTION,) and not concepts:
            question = V.text(language, "unclear")
        if intent == Intent.GENERAL_HARDWARE_QUESTION and concepts:
            vague = False
        return Understanding(
            text=text,
            guessed=guessed,
            intent=intent,
            language=language,
            terms=terms[:8],
            topics=topics,
            concepts=concepts,
            budget=budget,
            dimensions=dimensions,
            needs_clarification=bool(vague and question),
            question=question,
            safety=_safety(text, topics),
            source="rules",
        )

    # --- model -------------------------------------------------------------------------------------

    def _refine(self, result: Understanding, text: str, history: list[dict]) -> None:
        messages = [{"role": "system", "content": _LLM_SYSTEM}]
        for turn in history[-4:]:
            messages.append({"role": turn["role"], "content": turn["content"][:500]})
        messages.append({"role": "user", "content": text[:1000]})
        reply = self.provider.chat(messages, ChatOptions(json=True, max_tokens=250, temperature=0.1))
        data = reply.json()
        # What the customer said (this message and their earlier ones): the only source of numbers.
        said = " ".join([text] + [str(turn["content"])[:500] for turn in history[-4:] if turn.get("role") == "user"])

        intent = str(data.get("intent") or "").upper()
        if intent in Intent.ALL and result.intent == Intent.PRODUCT_SEARCH:
            result.intent = intent
        # The language stays as the rules detected it (Devanagari and Hinglish markers are reliable;
        # small models often label plain English as Hindi).
        raw_terms = data.get("search_terms")
        if isinstance(raw_terms, list):
            for term in raw_terms[:6]:
                if isinstance(term, str):
                    clean = re.sub(r"[^\w\s./-]", "", term).strip().lower()[:40]
                    if clean and clean not in result.terms and not V.DEVANAGARI.search(clean):
                        result.terms.append(clean)
        budget = data.get("budget")
        if (
            result.budget is None
            and isinstance(budget, (int, float))
            and not isinstance(budget, bool)
            and 0 < budget < 10_000_000
            and grounding.number_said(budget, said)
        ):
            # Only a budget the customer actually said: a model must never make one up.
            result.budget = Decimal(str(budget))
        question = data.get("question")
        if isinstance(question, str) and question.strip() and data.get("needs_clarification") and not result.terms:
            # Still nothing to search for: ask the model's follow-up question instead of a generic one — unless it
            # talks money or numbers the customer didn't say; then the fixed question is asked.
            asked = question.strip()[:300]
            result.question = asked if grounding.grounded(asked, said) else V.text(result.language, "unclear")
            result.needs_clarification = True
        elif result.terms:
            result.needs_clarification = False
            result.question = ""
        result.terms = result.terms[:10]
        result.source = "llm"


def _rupees(value: Decimal) -> str:
    return f"₹{value:,.0f}" if value == value.to_integral() else f"₹{value:,.2f}"
