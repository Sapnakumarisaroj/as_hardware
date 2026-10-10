"""Image → "what hardware item is this?" behind one small interface (Phase 14).

A provider only *names* the item in the photo. It never sees the catalogue's prices or stock and
cannot add a product: the image search service turns the names into ordinary catalogue searches.

Two kinds of answers:

- a **calibrated** answer (CLIP): a probability for each of the item kinds the shop gives it, so
  the confidence means something and the answer is always one of the known kinds;
- a **model's own estimate** (vision-language models through Ollama or an API): free text plus a
  self-reported confidence, which the service caps because such models tend to be over-confident.
"""

import base64
import io
import re
from dataclasses import dataclass, field

from integrations.llm import LLMError, LLMUnavailable


class VisionError(LLMError):
    """The provider answered with something unusable."""


class VisionUnavailable(LLMUnavailable):
    """The provider can't be used right now (not configured, model missing, not running). The caller falls back."""


@dataclass(frozen=True)
class Guess:
    label: str  # a plain English item name, e.g. "claw hammer"
    confidence: float  # 0..1
    search: str = ""  # catalogue words to search with (defaults to the label)

    @property
    def query(self) -> str:
        return self.search or self.label


@dataclass
class VisionResult:
    guesses: list[Guess]  # best first
    description: str = ""
    is_hardware: bool | None = None  # None: the provider can't tell
    calibrated: bool = False  # True when `confidence` is a real probability (CLIP)
    provider: str = ""
    model: str = ""
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Kind:
    """An item kind a provider may answer with: a name, a few ways to say it, and the search words."""

    label: str
    prompts: tuple[str, ...]
    search: str

    @property
    def query(self) -> str:
        return self.search or self.label


class VisionProvider:
    name = "none"
    model = ""
    calibrated = False

    @property
    def available(self) -> bool:
        return False

    def identify(self, image, kinds: list[Kind]) -> VisionResult:
        """`image` is an RGB PIL image (already validated and scaled down)."""
        raise VisionUnavailable("No vision model is configured.")

    def describe(self) -> dict:
        return {"provider": self.name, "model": self.model, "available": self.available, "calibrated": self.calibrated}


# --- Shared by the vision-language providers -------------------------------------------------------

PROMPT = """You identify hardware-store items in customer photos for an Indian hardware shop.
Look at the photo and answer with ONE JSON object and nothing else:
{{"is_hardware": true or false,
  "item": "the item's common English name, e.g. claw hammer",
  "alternatives": ["up to 3 other things it could be"],
  "search_terms": ["2-4 short words a shop would list it under"],
  "confidence": a number from 0 to 1 for how sure you are,
  "description": "one short sentence about what you see, with no prices, sizes, numbers or availability"}}
Prefer one of these names when one fits: {kinds}.
If the photo is unclear or not a hardware item, say so with a low confidence. Never guess brands, prices or sizes."""


def prompt_for(kinds: list[Kind]) -> str:
    return PROMPT.format(kinds=", ".join(k.label for k in kinds[:80]))


def jpeg_base64(image) -> str:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    return base64.b64encode(out.getvalue()).decode("ascii")


def _number(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number > 1:  # "85" meaning 85 %
        number /= 100
    return max(0.0, min(1.0, number))


# What a description of a photo must never contain: prices, stock or delivery claims, product codes, or numbers
# (sizes, quantities) — the catalogue is the only source of those. Devanagari digits count as digits.
_DESCRIPTION_FORBIDDEN = re.compile(
    r"[0-9०-९]|₹|\brs\b|\binr\b|\brupees?\b|\brupaye\b|रुपये|रुपए|/-|\bprice[sd]?\b|\bcosts?\b|\bmrp\b|\bcheap\w*\b|"
    r"\bexpensive\b|\bdiscount\w*\b|\boffer\w*\b|\bstock\b|\bin\s+store\b|\bavailab\w+\b|\bdeliver\w*\b|\bsku\b|"
    r"\bmodel\s+(no|number)\b|\bpart\s+(no|number)\b|कीमत|दाम|स्टॉक|उपलब्ध",
    re.IGNORECASE,
)


def clean_description(text: str) -> str:
    """The model's description, keeping only the sentences that describe what is seen (no prices, stock, codes or
    numbers). "" when nothing is left."""
    text = " ".join(str(text or "").split())[:300]
    sentences = re.split(r"(?<=[.!?।])\s+", text)
    return " ".join(s for s in sentences if s and not _DESCRIPTION_FORBIDDEN.search(s)).strip()


def parse_answer(data: dict, *, provider: str, model: str) -> VisionResult:
    """A vision-language model's JSON answer → VisionResult (labels trimmed, numbers clamped)."""
    item = str(data.get("item") or "").strip()[:80]
    if not item:
        raise VisionError("The vision model did not name an item.")
    confidence = _number(data.get("confidence"), 0.5)
    terms = [str(t).strip()[:40] for t in (data.get("search_terms") or []) if str(t).strip()][:4]
    guesses = [Guess(item.lower(), confidence, search=item.lower())]
    for alt in (data.get("alternatives") or [])[:3]:
        alt = str(alt).strip().lower()[:80]
        if alt and alt != item.lower():
            guesses.append(Guess(alt, round(confidence * 0.4, 3)))
    hardware = data.get("is_hardware")
    return VisionResult(
        guesses=guesses,
        description=clean_description(data.get("description")),
        is_hardware=hardware if isinstance(hardware, bool) else None,
        calibrated=False,
        provider=provider,
        model=model,
        extra={"search_terms": terms},
    )
