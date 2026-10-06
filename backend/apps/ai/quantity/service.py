# ruff: noqa: E501 — sentences in three languages read better on one line
"""Quantity AI (Phase 20): a requirement → estimated quantities → real products → one priced cart.

    "I need materials for 500 sq ft plastering" / "100 feet of wire" / "Mujhe 500 sq ft ke liye plastering ka saman chahiye"
      → calculator (rules: the calculators' words in English, Hindi, Hinglish; the AI model only when the rules
        find nothing, and only numbers that appear in the words are kept)
      → answers read from the words with units shown ("5 × 4 m = 16.4 × 13.1 ft"), missing questions,
        labelled assumptions ("Assumed: wall height 10 ft")
      → formulas (`quantity.formulas`, shared with the project builder and the assistant) with their breakdown
      → catalogue products and pack combinations (`projects.kit`, `quantity.packs`)
      → bulk tiers, offers, coupon, stock and delivery (`kit.price_rows` → the cart's pricing and delivery engines)

Read-only: nothing is stored unless the customer saves the calculation (a project) or adds it to the cart
(the cart service checks every line again). The model can't change a price, stock or an order: it only
suggests a calculator and numbers, which are validated like any other answer.
"""

import logging
import re

from apps.carts import services as carts
from apps.catalog.interpret import interpret
from apps.core.exceptions import ServiceError
from integrations.llm import ChatOptions, LLMError, LLMUnavailable, get_llm_provider

from ..projects import builder, flow, kit
from ..projects.templates import CALCULATORS, ProjectTemplate
from .text import say, t

logger = logging.getLogger(__name__)

ESTIMATED = t("Estimated quantity", "अनुमानित मात्रा", "Andazan quantity")
UNKNOWN = t(
    "I couldn't tell what to calculate. Pick one of the calculators and enter the measurements.",
    "समझ नहीं आया कि क्या गिनना है। कोई कैलकुलेटर चुनें और माप डालें।",
    "Samajh nahi aaya kya calculate karna hai. Koi calculator chunein aur measurement daalein.",
)
AI_OFF = t(
    "The AI helper isn't available right now, so only the built-in rules read your words. The calculations still work.",
    "AI सहायक अभी उपलब्ध नहीं है, इसलिए सिर्फ़ तय नियम आपके शब्द पढ़ रहे हैं। गणना फिर भी काम करती है।",
    "AI helper abhi available nahi hai, isliye sirf built-in rules aapke shabd padh rahe hain. Calculation phir bhi kaam karti hai.",
)
AI_USED = t(
    "Some details were read by the AI helper: please check them.",
    "कुछ बातें AI सहायक ने पढ़ीं: कृपया जाँच लें।",
    "Kuch details AI helper ne padhi: please check kar lein.",
)
QUANTITY_WORDS = re.compile(
    r"how\s+(much|many)|kitn[aie]|कितन|material|samaan|saman|सामान|quantity|estimate|calculat|andaz|अंदाज़|\bneed\b|chahiye|चाहिए",
    re.IGNORECASE,
)


class QuantityError(ServiceError):
    default_code = "quantity_error"


def _calculator_list(language: str) -> list[dict]:
    return [
        {
            "key": tpl.key,
            "name": say(tpl.name, language),
            "summary": say(tpl.summary, language),
            "examples": list(tpl.examples),
            "risky": tpl.risky,
        }
        for tpl in CALCULATORS.values()
    ]


def _model_prompt() -> str:
    lines = []
    for tpl in CALCULATORS.values():
        parts = []
        for q in tpl.questions:
            if q.kind == "choice":
                parts.append(f"{q.key} ({'|'.join(c.value for c in q.choices)})")
            else:
                parts.append(f"{q.key} (number, {q.unit})")
        lines.append(f"- {tpl.key} ({tpl.name['en']}: {tpl.summary['en']}) answers: {', '.join(parts)}")
    return (
        "You read a customer's requirement for an Indian hardware shop (English, Hindi or Hinglish) and pick ONE "
        "calculator. Copy only numbers the customer actually wrote; never guess a number. A number in another unit "
        'may be given as {"value": 5, "unit": "m"} (units: mm, cm, m, inch, ft, sq ft, sq m). Calculators and their answers:\n'
        + "\n".join(lines)
        + '\nReply with ONE JSON object: {"calculator": "<key or null>", "answers": {"<answer key>": <value>}}'
    )


def _numbers_in(text: str) -> set[float]:
    return {float(n) for n in re.findall(r"\d+(?:\.\d+)?", flow.normalise(text))}


class QuantityAIService:
    def __init__(self, provider=None):
        self.provider = provider or get_llm_provider()

    # --- Status ------------------------------------------------------------------------------------------

    def status(self, language: str = "en") -> dict:
        from ..quantity import packs

        return {
            "calculators": _calculator_list(language),
            "ai": {"available": bool(self.provider.available)},
            "pack_rule": packs.rule(),
            "label": say(ESTIMATED, language),
        }

    # --- Understanding -----------------------------------------------------------------------------------

    @staticmethod
    def detect(text: str) -> str | None:
        return flow.detect_type(text, CALCULATORS)

    @classmethod
    def is_quantity_request(cls, text: str) -> bool:
        """For voice: a calculator's words plus a size ("500 sq ft", "12x15") or a how-much word."""
        if not cls.detect(text):
            return False
        normal = flow.normalise(text)
        from .units import AREA, DIMENSIONS

        return bool(AREA.search(normal) or DIMENSIONS.search(normal) or QUANTITY_WORDS.search(normal))

    def _ask_model(self, text: str) -> tuple[str | None, dict]:
        """(calculator, raw answers) from the model; numbers not in the customer's words are dropped."""
        reply = self.provider.chat(
            [{"role": "system", "content": _model_prompt()}, {"role": "user", "content": text[:500]}],
            ChatOptions(json=True, max_tokens=200, temperature=0.0),
        )
        data = reply.json()
        key = str(data.get("calculator") or "").strip().lower()
        answers = data.get("answers") if isinstance(data.get("answers"), dict) else {}
        said = _numbers_in(text)
        normal = flow.normalise(text).lower()
        choices = {q.key for tpl in CALCULATORS.values() for q in tpl.questions if q.kind == "choice"}
        kept = {}
        for name, value in answers.items():
            if name in choices and str(value).lower() not in normal:
                continue  # a choice ("2x4" tiles) the customer never said: asked, not guessed
            number = value.get("value") if isinstance(value, dict) else value
            if isinstance(number, int | float) or (isinstance(number, str) and re.fullmatch(r"\d+(\.\d+)?", number)):
                if float(number) not in said:
                    continue  # a number the customer never said
            kept[name] = value
        return (key if key in CALCULATORS else None), kept

    def understand(self, text: str, calculator: str = "") -> dict:
        """Which calculator and what the words already answer. Never raises for the model's sake."""
        ai = {"available": bool(self.provider.available), "used": False, "failed": False}
        key = calculator if calculator in CALCULATORS else (self.detect(text) if text else None)
        source = "chosen" if calculator in CALCULATORS else "rules"
        reading = flow.read_description(CALCULATORS[key], text) if key and text else flow.Reading({})
        from_ai: dict = {}
        wants_model = text and (key is None or (_numbers_in(text) and self._missing_after(key, reading.answers)))
        if wants_model and self.provider.available:
            try:
                model_key, raw = self._ask_model(text)
                if key is None and model_key:
                    key, source = model_key, "ai"
                    reading = flow.read_description(CALCULATORS[key], text)
                if key and model_key == key:
                    accepted, _, _ = flow.clean_answers_noted(CALCULATORS[key], raw)
                    from_ai = {k: v for k, v in accepted.items() if v is not None and k not in reading.answers}
                ai["used"] = bool(source == "ai" or from_ai)
            except (LLMUnavailable, LLMError) as exc:
                logger.info("Quantity AI model skipped: %s", exc)
                ai["failed"] = True
            except Exception:  # a model answer must never break the calculator
                logger.exception("Quantity AI model failed")
                ai["failed"] = True
        return {"calculator": key, "source": source, "reading": reading, "from_ai": from_ai, "ai": ai}

    @staticmethod
    def _missing_after(key: str, answers: dict) -> bool:
        return not flow.resolve(CALCULATORS[key], answers).complete

    # --- Estimating --------------------------------------------------------------------------------------

    def estimate(
        self,
        *,
        text: str = "",
        calculator: str = "",
        answers: dict | None = None,
        language: str = "",
        user=None,
        postal_code: str = "",
        address_id: int | None = None,
        overrides: dict | None = None,
        coupon: str = "",
    ) -> dict:
        text = " ".join((text or "").split())[: builder.MAX_DESCRIPTION]
        language = flow.language_for(text, language)
        understood = self.understand(text, calculator)
        ai = understood["ai"]
        notice = ""
        if ai["used"]:
            notice = say(AI_USED, language)
        elif (not ai["available"] or ai["failed"]) and understood["calculator"] is None:
            notice = say(AI_OFF, language)
        key = understood["calculator"]
        base = {
            "text": text,
            "language": language,
            "label": say(ESTIMATED, language),
            "understood_by": understood["source"] if key else "",
            "ai": {"available": ai["available"], "used": ai["used"], "notice": notice},
            "calculators": _calculator_list(language),
        }
        if key is None:
            return {**base, "calculator": None, "complete": False, "message": say(UNKNOWN, language)}

        template: ProjectTemplate = CALCULATORS[key]
        reading = understood["reading"]
        given, errors, notes = flow.clean_answers_noted(template, answers or {})
        if errors:
            raise QuantityError("Some answers aren't valid.", code="invalid_answers", details=errors)
        merged = {**understood["from_ai"], **reading.answers, **{k: v for k, v in given.items()}}
        merged = {k: v for k, v in merged.items() if v is not None}
        state = flow.resolve(template, merged)
        result = {
            **base,
            "calculator": key,
            "name": say(template.name, language),
            "summary": say(template.summary, language),
            "answers": merged,
            "from_description": sorted(reading.answers),
            "from_ai": sorted(understood["from_ai"]),
            "interpretations": [n for n in reading.notes if n["key"] not in given] + notes,
            "questions": [q.describe(language) for q in template.questions if q.applies(state.answers)],
            "missing": [q.key for q in state.missing],
            "assumptions": flow.describe_assumptions(template, state, language),
            "complete": state.complete,
            **builder.guidance(template, state, language),
            "title": "",
            "materials": [],
            "kit": None,
        }
        if not state.complete:
            return result
        needs = builder.materials_for(template, state.answers)
        result["title"] = template.title(state.answers, language) if template.title else result["name"]
        prefer = {k: v for k, v in (interpret(text, {}).filters if text else {}).items() if k.startswith("opt_")}
        lines = kit.need_lines(needs, language, prefer=prefer or None)
        lines = self._apply_overrides(lines, overrides or {})
        rows = [
            kit.Row(
                line["material_key"], line["material_key"], line["label"], line["variant"], int(line["quantity"]),
                line["included"], line["details"], line["rationale"], line["unit"], line["is_optional"],
                line["is_estimate"], line.get("customer_set", False),
            )
            for line in lines
        ]  # fmt: skip
        result["kit"] = kit.price_rows(
            rows, user=user, postal_code=postal_code, address_id=address_id, coupon_code=coupon
        )
        result["materials"] = self._materials(needs, result["kit"]["items"], language)
        return result

    @staticmethod
    def _apply_overrides(lines: list[dict], overrides: dict) -> list[dict]:
        """The customer's changes on the result page ({material_key: {variant_id?, quantity?, included?}}),
        checked like project changes. A new product for a need replaces its other suggested pack sizes."""
        for key, change in overrides.items():
            if not isinstance(change, dict):
                continue
            line = next((line for line in lines if line["material_key"] == key), None)
            if line is None:
                continue
            if change.get("variant_id"):
                variant = carts._purchasable_variant(int(change["variant_id"]))
                count, size = kit.regather(line["details"], variant)
                line.update(
                    variant=variant, quantity=count, unit=variant.product.unit, included=True, customer_set=True
                )
                line["details"] = {**line["details"], "status": "found", "product_id": variant.product_id, "pack_amount": size,
                                   "pack_explanation": "", "size_known": size is not None or line["details"].get("need_unit") == "pcs"}  # fmt: skip
                lines = [
                    other
                    for other in lines
                    if other is line or kit.base_key(other["material_key"]) != kit.base_key(key)
                ]
            if change.get("quantity") is not None:
                line.update(quantity=max(1, min(int(change["quantity"]), 9999)), customer_set=True)
            if change.get("included") is not None:
                if change["included"] and line["variant"] is None:
                    raise QuantityError("Choose a product for this item first.", code="no_product")
                line.update(included=bool(change["included"]), customer_set=True)
        return lines

    @staticmethod
    def _materials(needs, items: list[dict], language: str) -> list[dict]:
        """One entry per material: the estimate, its breakdown, and what is recommended to buy."""
        out = []
        for need in needs:
            parts = [i for i in items if i["base_key"] == need.key]
            bought = [i for i in parts if i["variant"]]
            sizes = [i["pack_amount"] for i in bought]
            covers = sum(i["pack_amount"] * i["quantity"] for i in bought) if bought and all(s for s in sizes) else None
            from .packs import UNIT_LABEL

            out.append(
                {
                    "key": need.key,
                    "label": say(need.label, language),
                    "need": {
                        "amount": round(need.amount, 2),
                        "unit": need.unit,
                        "unit_label": UNIT_LABEL.get(need.unit, need.unit),
                    },
                    "is_estimate": need.estimate,
                    "is_optional": need.optional,
                    "steps": kit.steps_payload(need, language),
                    "recommended": " + ".join(
                        f"{i['quantity']} × {i['variant']['name'] or i['variant']['sku']}" for i in bought
                    ),
                    "covers": round(covers, 2) if covers is not None else None,
                    "extra": round(covers - need.amount, 2) if covers is not None else None,
                    "found": bool(bought),
                    "explanation": parts[0]["pack_explanation"] if parts else "",
                    "item_keys": [i["material_key"] for i in parts],
                }
            )
        return out

    # --- Saving and the cart -----------------------------------------------------------------------------

    def save(
        self,
        user,
        *,
        text: str = "",
        calculator: str = "",
        answers: dict | None = None,
        language: str = "",
        overrides: dict | None = None,
    ):
        """The calculation as a project (the project page then edits it, prices it and adds it to the cart)."""
        understood = self.understand(text, calculator)
        key = understood["calculator"]
        if key is None:
            raise QuantityError(
                "Choose a calculator first.", code="calculator_unknown", details={"choices": list(CALCULATORS)}
            )
        combined = {**understood["from_ai"], **(answers or {})}
        project = builder.start(
            user, description=text, project_type=key, answers=combined, language=language, calculators=True
        )
        items = {i.material_key: i for i in project.items.all()}
        for item_key, change in (overrides or {}).items():
            if item_key in items and isinstance(change, dict):
                kit.change_item(
                    items[item_key],
                    **{k: change[k] for k in ("variant_id", "quantity", "included") if change.get(k) is not None},
                )
        return project

    @staticmethod
    def add_to_cart(user, lines: list[dict]) -> dict:
        return kit.add_lines_to_cart(user, [(line["variant_id"], line["quantity"]) for line in lines])
