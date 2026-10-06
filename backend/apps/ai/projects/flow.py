"""Guided flow, shared by the project builder (Phase 19) and Quantity AI (Phase 20):
description → template → answers → the next questions.

Everything here is deterministic. The description is read for what it already says ("paint my 12x15 bedroom,
walls have cracks" → painting, length 12, width 15, interior, minor cracks; "5 m x 4 m" → feet, shown as an
interpretation); each question is asked only while its answer is missing and changes the materials; a
question with a default is never asked, its default is listed as an assumption the customer can change.
"""

import re
from dataclasses import dataclass, field

from ..quantity import units as U
from ..services.intent import detect_language
from .templates import TEMPLATES, ProjectTemplate, Question, say, t

ASSUMED = t("Assumed: {question} {value}", "मान लिया: {question} {value}", "Maan liya: {question} {value}")
NUMBER = r"(\d+(?:\.\d+)?)"


class ProjectInputError(ValueError):
    pass


def normalise(text: str) -> str:
    return U.normalise(text)


def detect_type(text: str, templates: dict[str, ProjectTemplate] | None = None) -> str | None:
    """The template whose words appear most in the description; ties go to the earlier (more specific) one."""
    text = normalise(text).lower()
    best, best_hits = None, 0
    for key, template in (templates or TEMPLATES).items():
        hits = sum(1 for pattern in template.patterns if re.search(pattern, text, re.IGNORECASE))
        if hits > best_hits:
            best, best_hits = key, hits
    return best


@dataclass
class Reading:
    answers: dict
    notes: list[dict] = field(default_factory=list)  # [{key, text}]: how a value was read or converted


def read_description(template: ProjectTemplate, text: str) -> Reading:
    """Answers the description already gives, with the interpretation of any unit. Only values the
    questions accept are kept."""
    text = normalise(text)
    found: dict = {}
    notes: list[dict] = []
    roles = {q.role: q for q in template.questions if q.role}
    rest = text

    # Choices first; their words (e.g. "600x600 mm" tiles) are then taken out before sizes are read.
    for question in template.questions:
        if question.kind != "choice":
            continue
        for choice in question.choices:
            match = next((m for p in choice.patterns if (m := re.search(p, rest, re.IGNORECASE))), None)
            if match:
                found[question.key] = choice.value
                if "x" in match.group(0).lower() or "×" in match.group(0):
                    rest = rest[: match.start()] + " " + rest[match.end() :]
                break

    sizes = U.read_dimensions(rest, unit="ft")
    if sizes and ("length" in roles or "area" in roles):
        values = {r.key: r.value for r in sizes}
        if "length" in roles and "width" in roles:
            found["length"], found["width"] = values["length"], values["width"]
            if "height" in values and "height" in roles:
                found["height"] = values["height"]
        elif "area" in roles:
            found["area"] = round(values["length"] * values["width"], 2)
        if sizes[0].note:
            notes.append({"key": "length", "text": sizes[0].note})
    if "area" in roles and (area := U.read_area(rest, unit="sq ft")):
        found["area"] = area.value
        found.pop("length", None), found.pop("width", None)
        if area.note:
            notes.append({"key": "area", "text": area.note})
    if "metres" in roles and (run := U.read_length(rest, unit="m")):
        found[roles["metres"].key] = run.value
        if run.note:
            notes.append({"key": roles["metres"].key, "text": run.note})

    for question in template.questions:
        if question.count_words:
            words = "|".join(re.escape(w) for w in question.count_words)
            if match := re.search(rf"{NUMBER}\s*(?:{words})(?![a-z])", rest, re.IGNORECASE):
                found[question.key] = float(match.group(1))

    if template.infer:
        template.infer(found, text)
    by_key = {q.key: q for q in template.questions}
    answers = {
        k: v for k, v in ((k, by_key[k].clean(v) if k in by_key else v) for k, v in found.items()) if v is not None
    }
    return Reading(answers, [n for n in notes if n["key"] in answers])


def extract_answers(template: ProjectTemplate, text: str) -> dict:
    return read_description(template, text).answers


def clean_answers(template: ProjectTemplate, given: dict) -> tuple[dict, dict[str, str]]:
    """Customer answers checked against the questions: (accepted, errors by key). A number may come with
    its unit ({"value": 5, "unit": "m"}); it is converted to the question's unit."""
    accepted, errors, _ = clean_answers_noted(template, given)
    return accepted, errors


def clean_answers_noted(template: ProjectTemplate, given: dict) -> tuple[dict, dict[str, str], list[dict]]:
    by_key = {q.key: q for q in template.questions}
    accepted, errors, notes = {}, {}, []
    for key, value in (given or {}).items():
        question = by_key.get(key)
        if question is None:
            continue
        if value is None or value == "" or (isinstance(value, dict) and value.get("value") in (None, "")):
            accepted[key] = None  # cleared
            continue
        if question.kind == "number":
            try:
                number, note = question.convert(value)
            except U.UnitError:
                errors[key] = f"Use one of these units: {', '.join(question.units)}."
                continue
            if note:
                notes.append({"key": key, "text": note})
            value = number if number is not None else value
        cleaned = question.clean(value)
        if cleaned is None:
            if question.kind == "choice":
                errors[key] = "Choose one of the options."
            else:
                unit = f" {question.unit}" if question.unit and question.unit not in ("%",) else ""
                errors[key] = f"Enter a number from {question.minimum:g} to {question.maximum:g}{unit}."
        else:
            accepted[key] = cleaned
    return accepted, errors, notes


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
