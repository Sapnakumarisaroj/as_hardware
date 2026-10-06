from dataclasses import dataclass, field
from decimal import Decimal


class Intent:
    PRODUCT_SEARCH = "PRODUCT_SEARCH"
    PROJECT_HELP = "PROJECT_HELP"
    REPAIR_HELP = "REPAIR_HELP"
    COMPATIBILITY = "COMPATIBILITY"
    QUANTITY = "QUANTITY"
    BUDGET = "BUDGET"
    GENERAL_HARDWARE_QUESTION = "GENERAL_HARDWARE_QUESTION"

    ALL = (PRODUCT_SEARCH, PROJECT_HELP, REPAIR_HELP, COMPATIBILITY, QUANTITY, BUDGET, GENERAL_HARDWARE_QUESTION)


LANGUAGES = ("en", "hi", "hinglish")


@dataclass
class Understanding:
    """What the customer asked for, as far as we can tell."""

    text: str = ""  # what the customer wrote
    intent: str = Intent.PRODUCT_SEARCH
    language: str = "en"
    terms: list[str] = field(default_factory=list)  # English words to search the catalogue with
    topics: list[str] = field(default_factory=list)  # keys into vocabulary.TOPICS
    concepts: list[str] = field(default_factory=list)  # keys into vocabulary.KNOWLEDGE
    budget: Decimal | None = None
    dimensions: tuple[float, float] | None = None  # e.g. a 12 x 15 room, in feet
    needs_clarification: bool = False
    question: str = ""
    safety: list[str] = field(default_factory=list)  # keys into vocabulary.SAFETY
    source: str = "rules"  # rules | llm
    model_failed: bool = False  # a configured model was asked and could not answer
    guessed: bool = False  # the vocabulary knew none of the words; `terms` are the customer's own


@dataclass
class ProductMatch:
    product: object  # catalog.Product row from selectors.product_queryset()
    variant_id: int
    price: Decimal
    reason: str
    term: str
    relevance: int = 0


@dataclass
class AssistantReply:
    message: str = ""
    products: list[ProductMatch] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    intent: str = Intent.PRODUCT_SEARCH
    language: str = "en"
    ai_mode: str = "basic"  # basic | llm
    notice: str = ""  # shown to the customer when the configured model could not be used
    model_failed: bool = False
    knowledge: list[dict] = field(default_factory=list)
    safety: list[str] = field(default_factory=list)
    estimate: dict | None = None
    compatibility: dict | None = None  # Phase 21: the compatibility engine's verdict (never the model's)
    provider: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0

    def product_refs(self) -> list[dict]:
        return [{"product_id": m.product.pk, "variant_id": m.variant_id, "reason": m.reason} for m in self.products]
