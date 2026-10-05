"""Search words that name a filter (Phase 16): "53 grade cement", "50 kg cement", "AC wire 1.5 sq mm".

The query is compared with what the catalogue actually holds, never with a hand-written list:
- option values (`OptionValue`, e.g. Grade "53 Grade", Bag size "50 kg", Cross-section "1.5 sq mm"),
- specification values that carry a unit ("20 kg", "1200 mm"),
- category and subcategory names ("Cement", "Wires & Cables" → "wire").

Only exact phrase matches count (after spacing "50kg" → "50 kg"), so nothing is invented: a grade the
shop doesn't stock is simply not understood. Departments are not used (too broad: "electrical tape" is
in Sealants & Tapes), and two different categories in one query cancel each other out.
The listing applies the filters only when they still leave results (see `views.ProductViewSet.list`),
and returns them as `search.interpreted` so the shopper sees and can remove them.
"""

import re
from dataclasses import dataclass, field

from django.core.cache import cache

from .models import Category, OptionValue, ProductSpecification

CACHE_KEY = "catalog:interpret-vocabulary"
CACHE_SECONDS = 300
MAX_SPEC_VALUES = 2000


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("sqmm", "sq mm").replace("sq.mm", "sq mm").replace("mm2", "sq mm")
    text = re.sub(r"(\d)([a-z])", r"\1 \2", text)  # 50kg → 50 kg, 53grade → 53 grade
    text = re.sub(r"([a-z])(\d)", r"\1 \2", text)
    text = re.sub(r"[^\w./]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _singular_phrase(text: str) -> str:
    return " ".join(_singular(w) for w in text.split())


def _contains(haystack: str, phrase: str) -> bool:
    return bool(phrase) and re.search(rf"(?<![\w.]){re.escape(phrase)}(?![\w.])", haystack) is not None


@dataclass
class Interpretation:
    filters: dict[str, str] = field(default_factory=dict)  # listing parameter → value
    labels: list[dict] = field(default_factory=list)  # [{param, value, label}]

    def __bool__(self) -> bool:
        return bool(self.filters)


def _vocabulary() -> dict:
    vocab = cache.get(CACHE_KEY)
    if vocab is not None:
        return vocab
    options = [
        {
            "phrase": normalize(v.value),
            "type_slug": v.option_type.slug,
            "type_name": v.option_type.name,
            "slug": v.slug,
            "value": v.value,
        }
        for v in OptionValue.objects.filter(option_type__is_active=True).select_related("option_type")
    ]
    specs = []
    for key, name, value, unit in (
        ProductSpecification.objects.exclude(unit="")
        .values_list("key", "name", "value", "unit")
        .distinct()[:MAX_SPEC_VALUES]
    ):
        if re.fullmatch(r"\d+(\.\d+)?", value.strip()):
            specs.append(
                {"phrase": normalize(f"{value} {unit}"), "key": key, "name": name, "value": value, "unit": unit}
            )
    categories = []
    for category in Category.objects.filter(is_active=True).exclude(parent__isnull=True):
        parts = [p for p in re.split(r"\s*(?:&|,|\band\b|/)\s*", category.name) if p.strip()]
        phrases = {_singular_phrase(normalize(p)) for p in parts} | {_singular_phrase(normalize(category.name))}
        categories.append({"slug": category.slug, "name": category.name, "phrases": sorted(p for p in phrases if p)})
    vocab = {"options": options, "specs": specs, "categories": categories}
    cache.set(CACHE_KEY, vocab, CACHE_SECONDS)
    return vocab


def interpret(query: str, params=None) -> Interpretation:
    """Filters named by the query, leaving out any the request already sets."""
    params = params or {}
    text = normalize(query)
    result = Interpretation()
    if not text:
        return result
    vocab = _vocabulary()
    used: list[str] = []

    by_type: dict[str, dict] = {}
    for option in vocab["options"]:
        if len(option["phrase"]) >= 2 and _contains(text, option["phrase"]):
            current = by_type.get(option["type_slug"])
            if current is None or len(option["phrase"]) > len(current["phrase"]):
                by_type[option["type_slug"]] = option
    for type_slug, option in by_type.items():
        param = f"opt_{type_slug}"
        if param in params:
            continue
        result.filters[param] = option["slug"]
        result.labels.append(
            {"param": param, "value": option["slug"], "label": f"{option['type_name']}: {option['value']}"}
        )
        used.append(option["phrase"])

    for spec in vocab["specs"]:
        param = f"spec_{spec['key']}"
        if param in params or param in result.filters or any(spec["phrase"] in u for u in used):
            continue
        if _contains(text, spec["phrase"]):
            result.filters[param] = spec["value"]
            result.labels.append(
                {"param": param, "value": spec["value"], "label": f"{spec['name']}: {spec['value']} {spec['unit']}"}
            )
            used.append(spec["phrase"])

    if "category" not in params and "subcategory" not in params:
        words = _singular_phrase(text)
        matches = {}
        for category in vocab["categories"]:
            best = max((p for p in category["phrases"] if _contains(words, p)), key=len, default=None)
            if best:
                matches[category["slug"]] = (best, category)
        if matches:
            longest = max(len(phrase) for phrase, _ in matches.values())
            top = [(phrase, c) for phrase, c in matches.values() if len(phrase) == longest]
            # A query that is only a category word ("drill", "taps") is left to search, which also finds
            # related items (drill bits); the category becomes a filter when the query says more.
            says_more = bool(result.filters) or bool(re.sub(rf"\b{re.escape(top[0][0])}\b", " ", words).strip())
            if len(top) == 1 and says_more:
                category = top[0][1]
                result.filters["category"] = category["slug"]
                result.labels.append({"param": "category", "value": category["slug"], "label": category["name"]})
    return result
