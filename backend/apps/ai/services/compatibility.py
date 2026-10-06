# ruff: noqa: E501 — sentences in three languages read better on one line
"""Compatibility questions for the assistant and voice (Phase 21).

"Will this drill bit work with this drill?" / "Is a CPVC elbow compatible with UPVC pipe?" /
"Which screws work with the 6 mm wall plugs?" / "kya ye bit is drill mein chalega?"
  → the products are found in the shop's catalogue (the listing's search; "this" = the product being viewed)
  → catalog.compatibility.CompatibilityService decides from listing facts and the shop's links
  → the answer states the engine's verdict; a configured model may only reword the reason, never the verdict.
"""

import json
import logging
import re
from decimal import Decimal

from apps.catalog import selectors
from apps.catalog.compatibility import profiles
from apps.catalog.compatibility.rules import COMPATIBLE, NOT, POSSIBLY, UNKNOWN
from apps.catalog.compatibility.service import CompatibilityService
from integrations.llm import ChatOptions, LLMError, LLMUnavailable

from ..projects.kit import names_the_need
from .catalog_match import choose_variant, find_products
from .schemas import AssistantReply, Intent, ProductMatch

logger = logging.getLogger(__name__)

QUESTION = re.compile(
    r"compatib|\bwork(s)?\s+(with|on|in)\b|\bfits?\s+(with|on|in|into)?\b|\bgo(es)?\s+with\b|\bmatch(es)?\b|\buse\b.*\bwith\b|"
    r"chalega|chalegi|lagega|lagegi|fit\s+hoga|fit\s+hogi|sahi\s+rahega|चलेगा|चलेगी|लगेगा|फिट|accessor",
    re.IGNORECASE,
)
SPLIT = re.compile(
    r"\s+(?:with|and|on|into|in|for|to|se|ke\s+saath|ke\s+sath|mein|me|aur|के\s+साथ|से|में|और)\s+", re.IGNORECASE
)
FILLER = re.compile(
    r"\b(will|would|can|could|does|do|is|are|i|my|this|that|these|those|the|a|an|it|use|work|works|working|fit|fits|go|goes|"
    r"compatible|compatibility|with|kya|ye|yeh|is|iss|wala|wali|mera|meri|chalega|chalegi|lagega|lagegi|hoga|hogi|ho|sakta|sakti|"
    r"which|what|show|me|accessories|accessory|that|work|are|be|together|each|other|use|products?|items?|one|thing|"
    r"cheez|saman|samaan|need|want|buy)\b|[?!]|[.,](?!\d)",  # keep the point of "2.5 sq mm"
    re.IGNORECASE,
)
# kind words a customer may ask for ("which screws…", "show drill bits for…")
KIND_WORDS = {
    "drill_bit": r"drill\s+bits?|\bbits?\b",
    "screw": r"\bscrews?\b|pech",
    "wall_plug": r"wall\s+plugs?|\bplugs?\b|anchors?",
    "pipe_fitting": r"fittings?|elbows?|valves?|connectors?",
    "pipe": r"\bpipes?\b",
    "wire": r"\bwires?\b|cables?|taar",
    "mcb": r"\bmcbs?\b",
    "switch": r"switch",
    "socket": r"socket",
    "drill": r"\bdrills?\b",
    "spanner": r"spanners?",
}

VERDICT_TEXT = {
    "en": {
        COMPATIBLE: "✅ Compatible",
        POSSIBLY: "⚠️ Possibly compatible",
        NOT: "❌ Not compatible",
        UNKNOWN: "ℹ️ Not enough information",
    },
    "hinglish": {
        COMPATIBLE: "✅ Compatible hai",
        POSSIBLY: "⚠️ Shayad compatible",
        NOT: "❌ Compatible nahi hai",
        UNKNOWN: "ℹ️ Poori jaankari nahi hai",
    },
    "hi": {COMPATIBLE: "✅ संगत है", POSSIBLY: "⚠️ शायद संगत", NOT: "❌ संगत नहीं है", UNKNOWN: "ℹ️ पूरी जानकारी नहीं है"},
}
TEXT = {
    "en": {
        "two": "{verdict}: {a} with {b}.",
        "need_two": "Tell me both products (for example “Will the masonry bit set work with the cordless drill?”), or ask from a product's page.",
        "options": "Products that work with it:",
        "none": "I couldn't find products in our catalogue that the listings confirm work with {a}.",
        "accessories": "Accessories for {a}:",
        "ai": "Explained by the AI helper; the verdict comes from the product listings.",
    },
    "hinglish": {
        "two": "{verdict}: {a} ke saath {b}.",
        "need_two": "Dono products bataiye (jaise “Masonry bit set cordless drill mein chalega?”), ya product page se poochiye.",
        "options": "Iske saath chalne wale products:",
        "none": "Catalogue mein aise products nahi mile jo {a} ke saath pakka chalein.",
        "accessories": "{a} ke accessories:",
        "ai": "AI helper ne samjhaya hai; faisla product listing se hai.",
    },
    "hi": {
        "two": "{verdict}: {a} के साथ {b}।",
        "need_two": "दोनों प्रोडक्ट बताइए (जैसे “मेसनरी बिट सेट कॉर्डलेस ड्रिल में चलेगा?”), या प्रोडक्ट पेज से पूछिए।",
        "options": "इसके साथ चलने वाले प्रोडक्ट:",
        "none": "कैटलॉग में ऐसे प्रोडक्ट नहीं मिले जो {a} के साथ पक्का चलें।",
        "accessories": "{a} के एक्सेसरी:",
        "ai": "AI सहायक ने समझाया है; फ़ैसला प्रोडक्ट लिस्टिंग से है।",
    },
}
LLM_SYSTEM = """You explain a hardware compatibility result to a shop customer in 1-2 short sentences, in the language
given ("en" English, "hi" Hindi in Devanagari, "hinglish" Hindi in Latin letters). Use ONLY the facts in the JSON.
Never change the verdict, never add a dimension, standard or rating that is not in the facts. Reply with ONE JSON
object: {"explanation": "..."}"""


def t(language: str, key: str, **values) -> str:
    return (TEXT.get(language) or TEXT["en"])[key].format(**values)


def is_question(text: str) -> bool:
    return bool(QUESTION.search(text or ""))


def _product(part: str):
    """(product, variant or None) a part of the question names. The kind it names ("drill" vs "drill bit") wins;
    every word must be in the product's own listing ("product" is not a product); size words pick the variant
    ("1.5 sq mm wire"). Only kind words ("this drill bit") name a product only if the shop has just one."""
    words = " ".join(FILLER.sub(" ", part).split())
    if len(words) < 3:
        return None
    match = find_products(words, limit=8)
    if not match.products or match.quality != "exact":
        return None
    kind = _asked_kind(words)
    named = [p for p in match.products if names_the_need(p, list(p.variants.all()), words)]
    of_kind = [p for p in named if kind and profiles.kind_of(p) == kind]
    leftover = words.lower()
    for pattern in KIND_WORDS.values():
        leftover = re.sub(pattern, " ", leftover)
    if not leftover.strip() and len(of_kind) != 1:
        return None  # "this drill bit" with several in the shop: ask, don't pick one
    product = (of_kind or named or [None])[0]
    if product is None:
        return None
    variant = choose_variant(product, match.params) if any(k.startswith("opt_") for k in match.params) else None
    if variant is None:  # variants without options ("16 A", "32 A"): the one whose name the words contain
        said = set(re.findall(r"\d+(?:\.\d+)?|[a-z]+", part.lower()))  # the words as said ("16 A" keeps its "a")
        named_variants = [
            v for v in product.variants.all()
            if v.is_active and v.name and set(re.findall(r"\d+(?:\.\d+)?|[a-z]+", v.name.lower())) <= said
        ]  # fmt: skip
        variant = named_variants[0] if len(named_variants) == 1 else None
    return product, variant


def _find_all(text: str) -> list:
    """(product, variant) pairs named in the question: each part around "with/and/se/ke saath", then (when fewer
    than two were found) each kind word with the two words before it ("6A switch", "16A socket")."""
    found = []

    def add(hit):
        if hit is not None and hit[0].pk not in [p.pk for p, _ in found]:
            found.append(hit)

    for part in SPLIT.split(text or ""):
        add(_product(part))
    if len(found) < 2:
        tokens = FILLER.sub(" ", text or "").split()
        for index, token in enumerate(tokens):
            if any(re.fullmatch(pattern, token.lower()) for pattern in KIND_WORDS.values()):
                # the tightest window around the kind word that names one product ("modular switch 6A")
                for start, end in (
                    (index - 1, index + 2),
                    (index - 2, index + 1),
                    (index, index + 2),
                    (index - 1, index + 1),
                ):
                    hit = _product(" ".join(tokens[max(0, start) : end]))
                    if hit is not None:
                        add(hit)
                        break
    return found


def _asked_kind(text: str, exclude: str | None = None) -> str | None:
    lowered = text.lower()
    found = [
        (m.start(), kind)
        for kind, pattern in KIND_WORDS.items()
        if kind != exclude and (m := re.search(pattern, lowered))
    ]
    return min(found)[1] if found else None


def _match(product, reason: str) -> ProductMatch:
    variant_id = getattr(product, "cheapest_variant_id", None) or next(
        (v.pk for v in product.variants.all() if v.is_active), None
    )
    return ProductMatch(
        product=product,
        variant_id=variant_id,
        price=Decimal(str(getattr(product, "min_price", 0) or 0)),
        reason=reason,
        term="compatibility",
    )


class CompatibilityAssistant:
    def __init__(self, provider=None):
        self.provider = provider
        self.service = CompatibilityService()

    def answer(self, text: str, *, language: str = "en", context_product_id: int | None = None) -> AssistantReply:
        language = language if language in TEXT else "en"
        reply = AssistantReply(intent=Intent.PRODUCT_SEARCH, language=language)
        found = _find_all(text)
        context = selectors.product_queryset().filter(pk=context_product_id).first() if context_product_id else None
        if context is not None and context.pk not in [p.pk for p, _ in found]:
            found.insert(0, (context, None))
        if len(found) >= 2:
            (a, variant_a), (b, variant_b) = found[0], found[1]
            return self._pair(reply, a, b, language, variant_a, variant_b)
        if len(found) == 1:
            return self._for_one(reply, found[0][0], text, language)
        # "Will this drill bit work with this drill?" without saying which: ask, and show the candidates
        kinds = [kind for kind, pattern in KIND_WORDS.items() if re.search(pattern, (text or "").lower())]
        candidates = []
        for kind in kinds[:2]:
            hits = find_products(kind.replace("_", " "), limit=8).products
            candidates += [p for p in hits if profiles.kind_of(p) == kind][:3]
        reply.message = t(language, "need_two")
        reply.products = [_match(p, "which one?") for p in candidates]
        reply.compatibility = {"verdict": UNKNOWN, "reason": "", "needs_products": True, "kinds": kinds[:2]}
        return reply

    def _pair(self, reply, a, b, language: str, variant_a=None, variant_b=None) -> AssistantReply:
        variant_a = self.service.load(a.pk, variant_a.pk)[1] if variant_a else None
        variant_b = self.service.load(b.pk, variant_b.pk)[1] if variant_b else None
        result = self.service.check(self.service.load(a.pk)[0], self.service.load(b.pk)[0], variant_a, variant_b)
        data = result.as_dict()
        options = []
        if result.verdict != COMPATIBLE:
            options = self.service.compatible_options(result.product_a, variant_a, result.kinds[1], exclude={b.pk})
        data["options"] = options
        explanation, by_ai = self._explain(data, language)
        verdict = VERDICT_TEXT.get(language, VERDICT_TEXT["en"])[result.verdict]
        name_a = f"{a.name} ({variant_a.name})" if variant_a is not None and variant_a.name else a.name
        name_b = f"{b.name} ({variant_b.name})" if variant_b is not None and variant_b.name else b.name
        lines = [t(language, "two", verdict=verdict, a=name_a, b=name_b), explanation]
        if by_ai:
            lines.append(t(language, "ai"))
        reply.message = "\n\n".join(lines)
        data["explained_by_ai"] = by_ai
        reply.compatibility = data
        reply.products = [_match(a, "compatibility: product A"), _match(b, "compatibility: product B")]
        rows = {p.pk: p for p in selectors.product_queryset().filter(pk__in=[o["product_id"] for o in options])}
        reply.products += [_match(rows[o["product_id"]], "works with it") for o in options if o["product_id"] in rows]
        return reply

    def _for_one(self, reply, product, text: str, language: str) -> AssistantReply:
        """ "Which screws work with this wall plug?" / "show accessories for this drill"."""
        kind = _asked_kind(text or "", exclude=profiles.kind_of(product))
        if kind:
            options = self.service.compatible_options(product, None, kind, limit=6)
            rows = {p.pk: p for p in selectors.product_queryset().filter(pk__in=[o["product_id"] for o in options])}
            reply.products = [
                _match(rows[o["product_id"]], o["reason"][:120]) for o in options if o["product_id"] in rows
            ]
            reply.message = (
                f"{t(language, 'options')} {', '.join(m.product.name for m in reply.products)}."
                if reply.products
                else t(language, "none", a=product.name)
            )
            reply.compatibility = {
                "verdict": None,
                "product_a": {"id": product.pk, "name": product.name},
                "options": options,
                "kind": kind,
            }
            return reply
        groups = self.service.accessories(product.pk)["groups"]
        ids = [row["product_id"] for name in ("required", "compatible", "accessories") for row in groups[name]][:6]
        rows = {p.pk: p for p in selectors.product_queryset().filter(pk__in=ids)}
        reply.products = [_match(rows[i], "accessory") for i in ids if i in rows]
        reply.message = (
            f"{t(language, 'accessories', a=product.name)} {', '.join(m.product.name for m in reply.products)}."
            if reply.products
            else t(language, "none", a=product.name)
        )
        reply.compatibility = {
            "verdict": None,
            "product_a": {"id": product.pk, "name": product.name},
            "groups": {k: [r["product_id"] for r in v] for k, v in groups.items()},
        }
        return reply

    def _explain(self, data: dict, language: str) -> tuple[str, bool]:
        """The engine's reason, or (with a model) the same facts in plain words. The verdict is never the model's."""
        if self.provider is None or not getattr(self.provider, "available", False):
            return data["reason"], False
        facts = {k: data[k] for k in ("verdict", "reason", "checks")} | {
            "a": data["product_a"]["name"],
            "b": data["product_b"]["name"],
            "language": language,
        }
        try:
            answer = self.provider.chat(
                [
                    {"role": "system", "content": LLM_SYSTEM},
                    {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
                ],
                ChatOptions(json=True, max_tokens=160, temperature=0.1),
            ).json()
            text = str(answer.get("explanation") or "").strip()
            numbers_ok = set(re.findall(r"\d+(?:\.\d+)?", text)) <= set(re.findall(r"\d+(?:\.\d+)?", json.dumps(facts)))
            if text and numbers_ok:
                return text[:400], True
        except (LLMUnavailable, LLMError) as exc:
            logger.info("Compatibility explanation by model skipped: %s", exc)
        except Exception:  # an explanation must never break the answer
            logger.exception("Compatibility explanation failed")
        return data["reason"], False
