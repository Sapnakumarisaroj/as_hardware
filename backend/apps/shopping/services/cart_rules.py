# ruff: noqa: E501 — the rules read better one per line
"""Data the smart cart reasons with (Phase 22, extended): what a cart line usually needs, which specifications
define a product, which variants are the same thing in another pack size, and the project kits a cart can match.

Everything here is matched on whole words of real catalogue rows ("ply" is not "plywood", "bit" is not "bitumen");
nothing is invented: a rule only says *what kind* of product to look for, the catalogue says whether the shop sells
one, and the pricing engine says what it costs.
"""

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

from django.db.models import Q

from apps.ai.projects import kit

from .recommendations import live

logger = logging.getLogger(__name__)

WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def words(text: str) -> set[str]:
    """Lower-case whole words, with simple plurals folded ("screws" → screw, "boxes" → box)."""
    out = set()
    for word in WORD.findall((text or "").lower()):
        out.add(word)
        if len(word) > 3 and word.endswith("es"):
            out.add(word[:-2])
        if len(word) > 2 and word.endswith("s"):
            out.add(word[:-1])
    return out


def names(product, *, category: bool = True) -> set[str]:
    texts = [product.name, " ".join(str(t) for t in (product.tags or []))]
    if category:
        texts.append(product.category.name)
        if product.subcategory_id:
            texts.append(product.subcategory.name)
    return words(" ".join(texts))


def has_term(have: set[str], term: str) -> bool:
    """Every word of `term` (or its singular) is one of `have`."""
    raw = WORD.findall(term.lower())
    return bool(raw) and all(
        w in have
        or (len(w) > 2 and w.endswith("s") and w[:-1] in have)
        or (len(w) > 3 and w.endswith("es") and w[:-2] in have)
        for w in raw
    )


# --- "Needed with it" ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class NeedRule:
    group: str  # one suggestion per group per cart
    triggers: tuple[str, ...]  # whole words of a cart product's name or tags
    suggest: tuple[str, ...]  # catalogue terms, tried in order; the cart already having one satisfies the rule
    reason: str
    target_kind: str | None = None  # the compatibility kind of the suggestion, when the engine can judge the pair
    priority: int = 75


NEED_RULES: tuple[NeedRule, ...] = (
    NeedRule("hinge_screws", ("hinge",), ("hinge screws", "wood screws", "screws"), "Hinges are fixed with screws.", "screw"),
    NeedRule("channel_screws", ("drawer channel", "drawer slide", "telescopic channel"), ("wood screws", "screws"),
             "Drawer channels are fixed with screws.", "screw"),
    NeedRule("handle_screws", ("handle", "knob"), ("handle screws", "machine screws", "screws"), "Handles are fixed with screws.", "screw"),
    NeedRule("adhesive", ("plywood", "blockboard", "mdf", "laminate", "veneer"), ("fevicol", "wood adhesive", "adhesive", "wood glue"),
             "Plywood and laminate are bonded with wood adhesive."),
    NeedRule("edge_band", ("plywood", "blockboard", "mdf"), ("edge band", "edge banding", "edge tape"), "Cut board edges are finished with edge band."),
    NeedRule("floor_spring", ("patch fitting",), ("floor spring",), "A glass door on patch fittings swings on a floor spring."),
    NeedRule("glass_lock", ("patch fitting",), ("glass door lock", "patch lock"), "A glass door needs a lock made for glass."),
    NeedRule("strike_plate", ("door lock", "mortise lock", "lock body"), ("strike plate",), "A door lock closes into a strike plate."),
    NeedRule("lock_screws", ("door lock", "mortise lock", "lock body", "deadbolt"), ("wood screws", "screws"), "A door lock is fixed with screws.", "screw"),
    NeedRule("goggles", ("drill", "grinder", "cutter", "saw", "jigsaw", "planer", "rotary hammer"), ("safety goggles", "goggles"),
             "Power tools throw dust and chips: protect your eyes.", priority=60),
    NeedRule("gloves", ("grinder", "cutter", "saw"), ("safety gloves", "gloves"), "Cutting tools: protect your hands.", priority=55),
)  # fmt: skip


def rule_applies(rule: NeedRule, product) -> bool:
    """A trigger word is in the product's own name or tags, and the product isn't itself what the rule suggests
    ("Hinge Screws" don't need hinge screws)."""
    own = names(product, category=False)
    return any(has_term(own, t) for t in rule.triggers) and not any(has_term(own, s) for s in rule.suggest)


def satisfied(rule: NeedRule, cart_products) -> bool:
    return any(has_term(names(p), s) for p in cart_products for s in rule.suggest)


def find_live(term: str, *, exclude, demo: bool, limit: int = 3) -> list:
    """Live (published, active, in-stock) products whose name, tags or category hold every word of `term`."""
    qs = live().filter(is_demo=demo).exclude(pk__in=list(exclude))
    for word in WORD.findall(term.lower()):
        stem = word[:-1] if len(word) > 3 and word.endswith("s") else word
        qs = qs.filter(
            Q(name__icontains=stem) | Q(category__name__icontains=stem) | Q(subcategory__name__icontains=stem)
        )
    rows = list(qs.order_by("-sold_count", "price", "pk")[:20])
    return [row for row in rows if has_term(names(row), term)][:limit]


# --- Defining specifications ------------------------------------------------------------------------------

# Specifications that describe a listing without changing what the product *is*. Every other one (thickness,
# size, length, grade, material, colour, capacity…) defines it: an "alternative" must state the same value.
NON_DEFINING = {
    "brand", "manufacturer", "warranty", "guarantee", "country-of-origin", "origin", "made-in", "model",
    "model-number", "model-no", "certification", "certifications", "features", "feature", "application",
    "applications", "uses", "usage", "use", "note", "notes", "box-contents", "in-the-box", "hsn", "hsn-code",
}  # fmt: skip


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().replace(",", " ").split())


def defining_specs(product) -> dict[str, tuple]:
    out = {}
    for spec in product.specifications.all():
        if spec.key in NON_DEFINING:
            continue
        number = spec.numeric_value
        out[spec.key] = (float(number) if number is not None else _norm(spec.value), _norm(spec.unit))
    return out


def states_same(wanted: dict, offered: dict) -> bool:
    """Every defining specification of the product (`wanted`) is stated with the same value by the other."""
    return all(offered.get(key) == value for key, value in wanted.items())


def spec_text(product, specs: dict) -> tuple[str, str]:
    """("Thickness 18 mm, Grade BWP", "thickness, grade") for the product's defining specifications."""
    rows = [s for s in product.specifications.all() if s.key in specs]
    same = ", ".join(f"{s.name} {s.value} {s.unit}".strip() for s in rows)
    return same, ", ".join(s.name.lower() for s in rows)


def variant_label(variant) -> tuple:
    return (_norm(variant.name), tuple(sorted(_norm(o.value.value) for o in variant.option_values.all())))


# --- Pack sizes -------------------------------------------------------------------------------------------

SINGLE = re.compile(r"^\s*(single|loose|one|1|1\s*(pc|pcs|piece|nos?|no))\s*$", re.IGNORECASE)
PACK_UNITS = ("kg", "l", "m", "pcs")


def explicit_pack(variant, unit: str) -> tuple[float, str] | None:
    """(size in `unit`, the rest of the variant's label) when the variant's own name or options state its pack
    size ("5 kg", "Box of 50", "Single"); None when they don't (the product-wide fallback isn't trusted here)."""
    texts = [variant.name or ""] + [o.value.value for o in variant.option_values.all()]
    for index, text in enumerate(texts):
        for pattern, factor in kit.SIZE_PATTERNS.get(unit, ()):
            if match := re.search(pattern, text, re.IGNORECASE):
                size = float(match.group(1)) * factor
                if size > 0:
                    rest = texts[:index] + [text[: match.start()] + text[match.end() :]] + texts[index + 1 :]
                    return size, _norm(" ".join(rest)).strip(" -–()")
        if unit == "pcs" and index == 0 and SINGLE.match(text or ""):
            return 1.0, _norm(" ".join(texts[1:]))
    return None


# --- Project kits -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class KitNeed:
    template: str
    template_name: str
    key: str
    label: str
    search: tuple[str, ...]
    avoid: tuple[str, ...]


def _sample_answers(template) -> dict:
    """Answers for listing a template's materials (which products, not how much): defaults, else the first
    choice, else a small number within the question's limits. Amounts from these are never shown."""
    answers = {}
    for question in template.questions:
        if question.default is not None:
            answers[question.key] = question.default
        elif question.kind == "choice" and question.choices:
            answers[question.key] = question.choices[0].value
        else:
            answers[question.key] = min(max(10, question.minimum), question.maximum)
    return answers


@lru_cache(maxsize=1)
def kit_needs() -> tuple[tuple[str, tuple[KitNeed, ...]], ...]:
    """(template key, its required materials) for every project template the builder offers."""
    from apps.ai.projects.templates import TEMPLATES, say

    out = []
    for key, template in TEMPLATES.items():
        try:
            needs = template.materials(_sample_answers(template))
        except Exception:  # noqa: BLE001 — a template that can't list materials from sample answers is skipped
            logger.info("smart cart: template %s has no sample materials", key, exc_info=True)
            continue
        name = say(template.name, "en")
        rows = tuple(
            KitNeed(key, name, n.key, say(n.label, "en"), tuple(n.search), tuple(n.avoid))
            for n in needs
            if not n.optional
        )
        if len(rows) >= 3:
            out.append((key, rows))
    return tuple(out)


def need_met(need: KitNeed, product, variants) -> bool:
    return any(kit.names_the_need(product, variants, term, need.avoid) for term in need.search)
