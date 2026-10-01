"""Photo → hardware item → real catalogue products (Phase 14).

    clean_image          validate, strip metadata, scale down (image_input.py); nothing is stored
    VisionProvider       names the item: CLIP probabilities over known kinds, or a vision model's estimate
    interpret            identified / uncertain / not_hardware, with the confidence the provider can justify
    catalogue            each name becomes an ordinary search (the shop's search backend over published
                         products); only products that really match the item's words are kept
    history              signed-in customers keep the outcome (never the photo) as an image conversation

The provider never sees prices or stock and cannot add a product. Every product card is built from
the database when it is shown, so a price or stock change is never stale.
"""

import logging
import re
from dataclasses import asdict, dataclass, field

from django.conf import settings
from django.core.cache import cache

from apps.catalog import selectors
from apps.catalog.search import get_search_backend
from integrations.vision import Guess, VisionError, VisionResult, VisionUnavailable, get_vision_provider

from ..models import AIConversation, AIMessage
from . import vision_kinds
from .image_input import CleanImage, clean_image, max_megabytes

logger = logging.getLogger(__name__)

IDENTIFIED = 0.5  # calibrated probability from which we say "this is a …"
VERY_LIKELY = 0.75
NOT_HARDWARE_MIN = 0.4  # "not a hardware item" only when that is the stronger, fairly sure answer
CANDIDATE_MIN = 0.05  # weaker guesses are not worth a search
SELF_REPORTED_CAP = 0.8  # a model's own confidence is never shown as more than "likely"
POSSIBLE = 3  # alternatives searched when unsure
PER_ALTERNATIVE = 2  # products per alternative

STATUS_TEXT = {
    "identified": "Identified",
    "uncertain": "Not sure",
    "not_hardware": "Not a hardware item",
    "no_match": "Not in our catalogue",
    "unavailable": "Photo search unavailable",
}


@dataclass
class Outcome:
    status: str
    explanation: str
    identification: dict | None = None
    alternatives: list[dict] = field(default_factory=list)
    search_query: str = ""
    notice: str = ""
    ai: dict = field(default_factory=dict)
    image: dict = field(default_factory=dict)
    product_refs: list[dict] = field(default_factory=list)

    def payload(self) -> dict:
        data = asdict(self)
        data.pop("product_refs")
        data["status_text"] = STATUS_TEXT[self.status]
        return data


def level(confidence: float) -> str:
    if confidence >= VERY_LIKELY:
        return "high"
    if confidence >= IDENTIFIED:
        return "medium"
    return "low"


def percent(confidence: float) -> int:
    return round(confidence * 100)


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9.]+", text.lower()) if len(w) > 1]


def _has_words(text: str, term: str) -> bool:
    """Every word of `term` is a whole word (or its plural) in `text`."""
    text = text.lower()
    return all(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?:s|es)?(?![a-z0-9])", text) for w in _words(term))


def _match_strength(product, term: str) -> str:
    """ "name" when the item's words are in the product name, "related" when only in its categories or tags
    (a PTFE tape tagged "tap"), "" when not at all (only inside other words: "tap" in "Tape")."""
    if _has_words(product.name, term):
        return "name"
    other = " ".join(
        str(x)
        for x in (
            product.category.name if product.category_id else "",
            product.subcategory.name if product.subcategory_id else "",
            " ".join(product.tags or []),
        )
    )
    return "related" if _has_words(other, term) else ""


def _head(text: str) -> str:
    words = _words(text)
    return words[-1].rstrip("s") if words else ""


def _more_specific_elsewhere(product, term: str, kinds) -> bool:
    """The product is really a different, more specific item: a "Masonry Drill Bit Set" is a *drill bit*,
    not a drill, although it contains the word "drill". Same head noun ("Impact Drill") is fine."""
    words = set(_words(term))
    for kind in kinds:
        for phrase in {kind.label, kind.query}:
            other = set(_words(phrase))
            if words < other and _head(phrase) != _head(term) and _has_words(product.name, phrase):
                return True
    return False


class ImageSearchService:
    def __init__(self, provider=None, backend=None):
        self.provider = provider or get_vision_provider()
        self.backend = backend or get_search_backend()

    # --- Status (public, so the page can render before a photo is chosen) --------------------------

    def status(self) -> dict:
        enabled = self.provider.name != "none"
        return {
            "enabled": enabled,
            "available": enabled and self.provider.available,
            "provider": self.provider.name,
            "model": self.provider.model,
            "calibrated": self.provider.calibrated,
            "max_bytes": settings.IMAGE_SEARCH_MAX_BYTES,
            "max_megabytes": max_megabytes(),
            "accepted_types": ["image/jpeg", "image/png", "image/webp"],
        }

    # --- The search --------------------------------------------------------------------------------

    def search(self, upload, user=None) -> tuple[Outcome, AIConversation | None]:
        clean = clean_image(upload)  # raises ImageInputError for anything that isn't a usable photo
        result = self._analyse(clean)
        outcome = self._unavailable() if result is None else self._interpret(result)
        outcome.image = clean.summary()
        conversation = self._remember(user, outcome) if user is not None and user.is_authenticated else None
        return outcome, conversation

    def _analyse(self, clean: CleanImage) -> VisionResult | None:
        provider = self.provider
        if provider.name == "none":
            return None
        key = f"ai:image:{provider.name}:{provider.model}:{clean.sha256}"
        cached = cache.get(key)
        if cached:
            cached["guesses"] = [Guess(**g) for g in cached["guesses"]]
            return VisionResult(**cached)
        try:
            if not provider.available:
                return None
            result = provider.identify(clean.image, vision_kinds.all_kinds())
        except VisionUnavailable as exc:
            logger.warning("Photo search unavailable: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001 — a model failure must never break the page
            logger.warning("Photo analysis failed: %s", exc, exc_info=not isinstance(exc, VisionError))
            return None
        if result.guesses:
            cache.set(key, asdict(result), settings.IMAGE_SEARCH_CACHE_SECONDS)
        return result

    def _unavailable(self) -> Outcome:
        return Outcome(
            status="unavailable",
            explanation="Photo search isn’t available right now. Describe the item in words and search instead.",
            ai={"mode": "unavailable", "provider": self.provider.name, "model": self.provider.model},
        )

    # --- Interpretation ----------------------------------------------------------------------------

    def _interpret(self, result: VisionResult) -> Outcome:
        ai = {
            "mode": "vision",
            "provider": result.provider,
            "model": result.model,
            "calibrated": result.calibrated,
        }
        notice = (
            ""
            if result.calibrated
            else "Identified by an AI model, which can be wrong. Check the product details before you buy."
        )

        guesses = [g for g in result.guesses if g.confidence >= CANDIDATE_MIN or g is result.guesses[0]]
        if not result.calibrated:
            guesses = [Guess(g.label, min(g.confidence, SELF_REPORTED_CAP), g.search) for g in guesses]
        hardware = [g for g in guesses if vision_kinds.is_hardware_label(g.label)]
        other = sum(g.confidence for g in guesses if not vision_kinds.is_hardware_label(g.label))
        top = hardware[0] if hardware else None
        description = result.description

        not_hardware = result.is_hardware is False or (
            result.calibrated and other >= NOT_HARDWARE_MIN and other > (top.confidence if top else 0)
        )
        if not_hardware or top is None:
            what = next((g.label for g in guesses if not vision_kinds.is_hardware_label(g.label)), "")
            return Outcome(
                status="not_hardware",
                explanation=(
                    f"This doesn’t look like a hardware item{f' (it looks like {what})' if what else ''}. "
                    "Take a clear photo of the item on its own, in good light."
                ),
                identification=None,
                notice=notice,
                ai=ai,
            )

        sure = top.confidence >= IDENTIFIED
        candidates = [top] + [g for g in hardware[1:] if g.confidence >= (0.15 if sure else CANDIDATE_MIN)][
            : POSSIBLE - 1
        ]
        identification = {
            "label": top.label,
            "confidence": round(top.confidence, 3),
            "percent": percent(top.confidence),
            "level": level(top.confidence),
            "calibrated": result.calibrated,
            "description": description,
        }
        alternatives = [
            {
                "label": g.label,
                "confidence": round(g.confidence, 3),
                "percent": percent(g.confidence),
                "search": g.query,
            }
            for g in candidates[1:]
        ]
        extra_terms = result.extra.get("search_terms") or []
        # A vision-language model's "alternatives" are loose words, not weighed possibilities: when it is sure,
        # they stay suggestions (links) and only the named item fetches products.
        searched = candidates if result.calibrated or not sure else [top]
        refs = self._catalogue(searched, sure, extra_terms)

        if not refs:
            return Outcome(
                status="no_match",
                explanation=(
                    f"This looks like {_a(top.label)}"
                    f"{'' if sure else ' (we’re not sure)'}, but we don’t have this in our catalogue right now. "
                    "Try searching in words, or browse the categories."
                ),
                identification=identification,
                alternatives=alternatives,
                search_query=top.query,
                notice=notice,
                ai=ai,
            )
        if sure:
            certainty = (
                f"We’re {percent(top.confidence)}% sure." if result.calibrated else "That is the AI model’s best guess."
            )
            explanation = f"This looks like {_a(top.label)}. {certainty}"
            status = "identified"
        else:
            options = ", ".join(g.label for g in candidates)
            explanation = (
                f"We’re not sure what this is. It might be: {options}. "
                "Here are possible matches; check the details before you buy, or try a clearer photo."
            )
            status = "uncertain"
        return Outcome(
            status=status,
            explanation=explanation,
            identification=identification,
            alternatives=alternatives,
            search_query=top.query,
            notice=notice,
            ai=ai,
            product_refs=refs,
        )

    # --- Catalogue ---------------------------------------------------------------------------------

    def _products_for(self, term: str, limit: int, kinds) -> list[tuple]:
        """(product, "name" | "related") for one item name, products named after it first."""
        base = selectors.product_queryset()
        result = self.backend.search(base, term)
        if result.matched not in ("all_terms", "related"):
            return []
        rows = list(selectors.order_products(result.queryset, "relevance", searching=True)[: limit * 4])
        rows = [p for p in rows if p.cheapest_variant_id is not None and not _more_specific_elsewhere(p, term, kinds)]
        graded = [(p, _match_strength(p, term)) for p in rows]
        named = [(p, s) for p, s in graded if s == "name"]
        related = [(p, s) for p, s in graded if s == "related"]
        if named or related:
            return (named + related)[:limit]
        # Nothing has the item's words; meaning-based results are still offered, but keyword-only ones
        # ("tap" inside "Tape") are not.
        return [(p, "related") for p in rows[:limit]] if result.matched == "related" else []

    def _catalogue(self, candidates: list[Guess], sure: bool, extra_terms: list[str]) -> list[dict]:
        limit = settings.IMAGE_SEARCH_MAX_PRODUCTS
        kinds = vision_kinds.all_kinds()
        refs: list[dict] = []
        seen: set[int] = set()
        for index, guess in enumerate(candidates):
            terms = [guess.query] + (extra_terms if index == 0 else [])
            quota = (limit - PER_ALTERNATIVE * (len(candidates) - 1)) if index == 0 else PER_ALTERNATIVE
            for term in dict.fromkeys(t.lower() for t in terms if t):
                found = self._products_for(term, max(quota, 1), kinds)
                for product, strength in found:
                    if product.pk in seen or len(refs) >= limit:
                        continue
                    seen.add(product.pk)
                    if strength == "related":
                        reason = f"Related to “{guess.label}”"
                        if not (sure and index == 0):
                            reason += f" ({percent(guess.confidence)}%)"
                    elif sure and index == 0:
                        reason = f"Matches “{guess.label}”"
                    else:
                        reason = f"Possible match: {guess.label} ({percent(guess.confidence)}%)"
                    refs.append(
                        {
                            "product_id": product.pk,
                            "variant_id": product.cheapest_variant_id,
                            "reason": reason,
                            "label": guess.label,
                            "confidence": round(guess.confidence, 3),
                        }
                    )
                if found:
                    break  # the main words found products: the model's extra words aren't needed
        return refs

    # --- History -----------------------------------------------------------------------------------

    def _remember(self, user, outcome: Outcome) -> AIConversation:
        label = (outcome.identification or {}).get("label") or STATUS_TEXT[outcome.status]
        conversation = AIConversation.objects.create(
            user=user,
            kind=AIConversation.Kind.IMAGE,
            title=f"Photo: {label}"[:150],
            metadata={"status": outcome.status, "image": outcome.image},
        )
        AIMessage.objects.create(
            conversation=conversation,
            role=AIMessage.Role.ASSISTANT,
            content=outcome.explanation,
            product_refs=outcome.product_refs,
            payload=outcome.payload(),
            provider=outcome.ai.get("provider", ""),
            model=outcome.ai.get("model", "")[:80],
        )
        return conversation


def _a(label: str) -> str:
    if label.endswith("s") and not label.endswith("ss"):
        return label  # "screws", "pliers"
    vowel_sound = label[:1] in "aeio" or label.startswith(("led ", "mcb", "n95"))  # "a utility knife", "an LED bulb"
    return f"{'an' if vowel_sound else 'a'} {label}"
