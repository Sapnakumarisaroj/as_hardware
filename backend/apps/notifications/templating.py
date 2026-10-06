"""`{variable}` templates for notification messages.

Deliberately not Django templates: an administrator edits these, so there are no tags, filters,
attribute lookups or loops — only whole-word variables from the event's list. Anything else is
refused when the template is saved, and a template that can't be rendered at send time falls back
to the built-in default words, so a bad edit never stops a message.
"""

import re

VARIABLE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
STRAY_BRACE = re.compile(r"[{}]")
LIMITS = {"title": 150, "body": 2000, "whatsapp": 1024, "sms": 480}


class TemplateError(ValueError):
    pass


def variables_in(text: str) -> list[str]:
    """Variable names in the order they first appear (WhatsApp template parameters use this order)."""
    seen: list[str] = []
    for name in VARIABLE.findall(text or ""):
        if name not in seen:
            seen.append(name)
    return seen


def validate(text: str, allowed: tuple[str, ...] | list[str], *, limit: int) -> list[str]:
    """Problems with a template, in plain words; empty when it is fine."""
    problems = []
    if len(text) > limit:
        problems.append(f"Keep it under {limit} characters (now {len(text)}).")
    unknown = [name for name in variables_in(text) if name not in allowed]
    if unknown:
        problems.append(f"Unknown variable(s): {', '.join('{' + n + '}' for n in unknown)}.")
    if STRAY_BRACE.search(VARIABLE.sub("", text)):
        problems.append("Braces may only wrap a variable name, like {order_number}.")
    return problems


def render(text: str, context: dict, *, secret: tuple[str, ...] = (), reveal: bool = False) -> str:
    """Fill in the variables. Secret variables become "••••••" unless `reveal`. A missing variable raises."""

    def fill(match: re.Match) -> str:
        name = match.group(1)
        if name in secret and not reveal:
            return "••••••"
        if name not in context or context[name] is None:
            raise TemplateError(f"No value for {{{name}}}.")
        return str(context[name])

    return re.sub(r"[ \t]{2,}", " ", VARIABLE.sub(fill, text or "")).strip()  # an empty sentence leaves no gap
