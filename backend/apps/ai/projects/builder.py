# ruff: noqa: E501 — sentences in three languages read better on one line
"""Project builder service (Phase 19): one saved project per job, from first description to the cart.

start(user, description / project type) → questions still needed, assumptions, and (once nothing is
missing) a kit of real catalogue lines; answer(...) → the kit is worked out again, keeping the lines the
customer changed; plan_payload(...) → everything the page shows, priced and delivery-checked live.

A saved Quantity AI calculation (Phase 20) is a project too: its type is one of the calculators.
"""

from django.db import transaction

from apps.core.exceptions import ServiceError

from ..models import Project
from ..quantity.formulas import FormulaError
from ..services.vocabulary import SAFETY_TEXT
from . import flow, kit
from .templates import ALL_TEMPLATES, TEMPLATES, ProjectTemplate, say, t

ESTIMATE_NOTICE = t(
    "Quantities marked “estimate” come from common rules of thumb and include a little extra. Check them against your site before buying.",
    "“अनुमान” वाली मात्राएँ आम नियमों से निकाली गई हैं और थोड़ी ज़्यादा रखी गई हैं। ख़रीदने से पहले अपनी जगह के हिसाब से जाँच लें।",
    "“Estimate” wali quantity aam rules se nikali gayi hai aur thodi zyada rakhi gayi hai. Kharidne se pehle apni jagah ke hisaab se check kar lein.",
)
PROFESSIONAL = t(
    "We recommend a qualified professional for this job.",
    "इस काम के लिए किसी योग्य कारीगर/विशेषज्ञ की सलाह लें।",
    "Is kaam ke liye kisi qualified professional ki madad lein.",
)
VERIFY = t(
    "Verify measurements with a qualified professional before purchasing.",
    "ख़रीदने से पहले माप किसी योग्य विशेषज्ञ से जाँच करवा लें।",
    "Kharidne se pehle measurement kisi qualified professional se check karwa lein.",
)
MAX_DESCRIPTION = 500


class ProjectError(ServiceError):
    default_code = "project_error"


def template_for(project: Project) -> ProjectTemplate:
    template = ALL_TEMPLATES.get(project.project_type)
    if template is None:
        raise ProjectError("This project type has no guided plan yet.", code="project_type_unsupported")
    return template


def templates_payload(language: str = "en", templates: dict | None = None) -> list[dict]:
    return [
        {
            "key": tpl.key,
            "name": say(tpl.name, language),
            "summary": say(tpl.summary, language),
            "first_question": tpl.questions[0].describe(language) if tpl.questions else None,
        }
        for tpl in (templates or TEMPLATES).values()
    ]


def materials_for(template: ProjectTemplate, answers: dict) -> list:
    """The template's needs; answers that can't describe a real job become an `invalid_answers` error."""
    try:
        return template.materials(answers)
    except FormulaError as exc:
        raise ProjectError(
            "Some answers aren't possible.", code="invalid_answers", details={exc.key: str(exc)}
        ) from exc


@transaction.atomic
def start(
    user,
    *,
    description: str = "",
    project_type: str = "",
    answers: dict | None = None,
    language: str = "",
    calculators: bool = False,
) -> Project:
    """`calculators`: also accept a Quantity AI calculator as the type (a saved quantity calculation)."""
    description = " ".join((description or "").split())[:MAX_DESCRIPTION]
    allowed = ALL_TEMPLATES if calculators else TEMPLATES
    if project_type and project_type not in allowed:
        raise ProjectError(
            "Choose one of the project types.", code="project_type_unknown", details={"choices": list(allowed)}
        )
    project_type = project_type or flow.detect_type(description) or ""
    if not project_type:
        raise ProjectError(
            "We couldn't tell what kind of project this is. Pick one of the project types.",
            code="project_type_unknown",
            details={"choices": list(allowed)},
        )
    template = allowed[project_type]
    language = flow.language_for(description, language)
    reading = flow.read_description(template, description) if description else flow.Reading({})
    given, errors, notes = flow.clean_answers_noted(template, answers or {})
    if errors:
        raise ProjectError("Some answers aren't valid.", code="invalid_answers", details=errors)
    project = Project.objects.create(
        user=user,
        project_type=project_type,
        title=say(template.name, language)[:150],
        inputs={
            "description": description,
            "language": language,
            "answers": {k: v for k, v in {**reading.answers, **given}.items() if v is not None},
            "from_description": sorted(reading.answers),
            "interpretations": [n for n in reading.notes if n["key"] not in given] + notes,
        },
    )
    refresh(project)
    return project


@transaction.atomic
def answer(project: Project, *, answers: dict | None = None, language: str = "", title: str = "") -> Project:
    project = Project.objects.select_for_update().get(pk=project.pk)
    template = template_for(project)
    given, errors, notes = flow.clean_answers_noted(template, answers or {})
    if errors:
        raise ProjectError("Some answers aren't valid.", code="invalid_answers", details=errors)
    inputs = dict(project.inputs)
    merged = {**inputs.get("answers", {}), **given}
    inputs["answers"] = {k: v for k, v in merged.items() if v is not None}
    inputs["interpretations"] = [n for n in inputs.get("interpretations", []) if n["key"] not in given] + notes
    if language in ("en", "hi", "hinglish"):
        inputs["language"] = language
    project.inputs = inputs
    if title.strip():
        project.title = title.strip()[:150]
        inputs["custom_title"] = True
    project.save(update_fields=["inputs", "title", "updated_at"])
    refresh(project)
    return project


@transaction.atomic
def reset_suggestions(project: Project) -> Project:
    """Forget the customer's changes to suggested lines (their own extra products stay)."""
    project.items.exclude(material_key__startswith="extra-").delete()
    refresh(project)
    return project


def refresh(project: Project) -> None:
    template = template_for(project)
    language = project.inputs.get("language", "en")
    state = flow.resolve(template, project.inputs.get("answers", {}))
    if state.complete:
        kit.build_items(project, materials_for(template, state.answers), language)
        if project.status == Project.Status.DRAFT or project.status == Project.Status.ORDERED:
            project.status = Project.Status.READY
    else:
        project.items.exclude(material_key__startswith="extra-").delete()
        project.status = Project.Status.DRAFT
    if not project.inputs.get("custom_title") and template.title and state.complete:
        project.title = template.title(state.answers, language)[:150]
    project.safety_notes = "\n".join(safety_lines(template, state.answers, language))
    project.save(update_fields=["status", "title", "safety_notes", "updated_at"])


def safety_lines(template: ProjectTemplate, answers: dict, language: str) -> list[str]:
    lines = [say(t_, language) for t_ in (SAFETY_TEXT[k] for k in template.safety if k in SAFETY_TEXT)]
    if template.caution:
        lines.append(say(template.caution, language))
    return lines


def guidance(template: ProjectTemplate, state: flow.FlowState, language: str) -> dict:
    """Safety, professional advice and notes shown with a plan or a calculation."""
    professional = bool(template.professional and state.complete and template.professional(state.answers))
    return {
        "safety": safety_lines(template, state.answers, language),
        "professional": say(PROFESSIONAL, language) if professional else "",
        "verify": say(VERIFY, language) if template.risky else "",
        "not_sold": say(template.not_sold, language) if template.not_sold else "",
        "estimate_notice": say(ESTIMATE_NOTICE, language),
    }


def plan_payload(
    project: Project, *, user, postal_code: str = "", address_id: int | None = None, quote: bool = True
) -> dict:
    template = template_for(project)
    language = project.inputs.get("language", "en")
    given = project.inputs.get("answers", {})
    state = flow.resolve(template, given)
    data = {
        "id": project.pk,
        "title": project.title,
        "project_type": project.project_type,
        "type_name": say(template.name, language),
        "is_calculation": project.project_type not in TEMPLATES,
        "status": project.status,
        "description": project.inputs.get("description", ""),
        "language": language,
        "summary": say(template.summary, language),
        "answers": given,
        "from_description": project.inputs.get("from_description", []),
        "interpretations": project.inputs.get("interpretations", []),
        "questions": [q.describe(language) for q in template.questions if q.applies(state.answers)],
        "missing": [q.key for q in state.missing],
        "assumptions": flow.describe_assumptions(template, state, language),
        "complete": state.complete,
        **guidance(template, state, language),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "kit": None,
    }
    if quote and project.items.exists():
        data["kit"] = kit.quote_kit(project, user=user, postal_code=postal_code, address_id=address_id)
    return data
