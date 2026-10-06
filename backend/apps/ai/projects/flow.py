"""Guided project flow (Phase 19): description → project type → answers → the next questions.

Everything here is deterministic. The description is read for what it already says ("paint my 12x15 bedroom,
walls have cracks" → painting, length 12, width 15, interior, minor cracks); each question is asked only
while its answer is missing and changes the materials; a question with a default is never asked, its
default is listed as an assumption the customer can change.
"""

import re
from dataclasses import dataclass, field

from ..services.intent import detect_language
from .templates import TEMPLATES, ProjectTemplate, Question, say, t

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
NUMBER = r"(\d+(?:\.\d+)?)"
DIMENSIONS = re.compile(rf"{NUMBER}\s*(?:ft|feet|foot|')?\s*(?:x|×|\*|by|बाई)\s*{NUMBER}", re.IGNORECASE)
AREA = re.compile(rf"{NUMBER}\s*(?:sq\.?\s*(?:ft|feet)|sqft|square\s+(?:feet|foot|ft)|वर्ग\s*फ\S*ट)", re.IGNORECASE)
METRES = re.compile(rf"{NUMBER}\s*(?:m|mtr|metres?|meters?|मीटर)(?![a-z])", re.IGNORECASE)

ASSUMED = t("Assumed: {question} {value}", "मान लिया: {question} {value}", "Maan liya: {question} {value}")


class ProjectInputError(ValueError):
    pass


def normalise(text: str) -> str:
    return " ".join((text or "").translate(DEVANAGARI_DIGITS).split())


def detect_type(text: str) -> str | None:
    """The template whose words appear most in the description; ties go to the more specific job."""
    text = normalise(text).lower()
    best, best_hits = None, 0
    for key, template in TEMPLATES.items():
        hits = sum(1 for pattern in template.patterns if re.search(pattern, text, re.IGNORECASE))
        if hits > best_hits:
            best, best_hits = key, hits
    return best


def extract_answers(template: ProjectTemplate, text: str) -> dict:
    """Answers the description already gives. Only values the questions accept are kept."""
    text = normalise(text)
    found: dict = {}
    by_role = {q.role: q for q in template.questions if q.role}

    if match := DIMENSIONS.search(text):
        length, width = float(match.group(1)), float(match.group(2))
        if "length" in by_role and "width" in by_role:
            found["length"], found["width"] = length, width
        elif "area" in by_role:
            found["area"] = length * width
    if "area" in by_role and (match := AREA.search(text)):
        found["area"] = float(match.group(1))
    if "metres" in by_role and (match := METRES.search(text)):
        found[by_role["metres"].key] = float(match.group(1))

    for question in template.questions:
        if question.count_words:
            words = "|".join(re.escape(w) for w in question.count_words)
            if match := re.search(rf"{NUMBER}\s*(?:{words})(?![a-z])", text, re.IGNORECASE):
                found[question.key] = float(match.group(1))
        if question.kind == "choice" and question.key not in found:
            for choice in question.choices:
                if any(re.search(p, text, re.IGNORECASE) for p in choice.patterns):
                    found[question.key] = choice.value
                    break

    if template.infer:
        template.infer(found, text)
    by_key = {q.key: q for q in template.questions}
    return {k: v for k, v in ((k, by_key[k].clean(v) if k in by_key else v) for k, v in found.items()) if v is not None}


def clean_answers(template: ProjectTemplate, given: dict) -> tuple[dict, dict[str, str]]:
    """Customer answers checked against the questions: (accepted, errors by key)."""
    by_key = {q.key: q for q in template.questions}
    accepted, errors = {}, {}
    for key, value in (given or {}).items():
        question = by_key.get(key)
        if question is None:
            continue
        if value is None or value == "":
            accepted[key] = None  # cleared
            continue
        cleaned = question.clean(value)
        if cleaned is None:
            if question.kind == "choice":
                errors[key] = "Choose one of the options."
            else:
                errors[key] = f"Enter a number from {question.minimum:g} to {question.maximum:g}."
        else:
            accepted[key] = cleaned
    return accepted, errors


@dataclass
class FlowState:
    answers: dict  # given + defaults: what the materials are worked out from
    missing: list[Question]  # still to ask, in order
    assumptions: list[dict] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing


def resolve(template: ProjectTemplate, given: dict) -> FlowState:
    """Walk the questions in order: given answers stand, defaults fill in, the rest is asked."""
    answers = {k: v for k, v in given.items() if v is not None}
    missing, assumptions = [], []
    for question in template.questions:
        if not question.applies(answers) or answers.get(question.key) is not None:
            continue  # not relevant to this job (e.g. "taps" when no tap is replaced), or answered
        if question.default is not None:
            answers[question.key] = question.default
            assumptions.append({"key": question.key, "value": question.default})
        else:
            missing.append(question)
    return FlowState(answers, missing, assumptions)


def describe_assumptions(template: ProjectTemplate, state: FlowState, language: str) -> list[dict]:
    by_key = {q.key: q for q in template.questions}
    out = []
    for item in state.assumptions:
        question = by_key[item["key"]]
        value = item["value"]
        label = next((say(c.label, language) for c in question.choices if c.value == value), None)
        if label is None:
            label = f"{value:g} {question.unit}".strip() if isinstance(value, int | float) else str(value)
        out.append(
            {
                "key": question.key,
                "value": value,
                "text": say(ASSUMED, language, question=say(question.text, language), value=label),
            }
        )
    return out


def language_for(description: str, requested: str = "") -> str:
    if requested in ("en", "hi", "hinglish"):
        return requested
    return detect_language(description) if description else "en"
