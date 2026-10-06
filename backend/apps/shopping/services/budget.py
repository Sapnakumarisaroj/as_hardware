# ruff: noqa: E501 — messages read better on one line
"""BudgetPlanner (Phase 22): "I need plumbing materials under ₹5,000" → a cart that stays within ₹5,000.

    budget        the assistant's own parser (`intent.parse_budget`: "₹5,000", "5000 rupees", "under 5000",
                  "5000 tak", Hindi) or the number the customer typed
    requirement   the Quantity AI calculators and project templates (same questions, answers, assumptions and
                  formulas as `/quantity` and `/projects`); missing details are asked, never guessed
    products      `kit.need_lines` (real catalogue products, pack optimiser, compatibility alignment)
    price         `kit.price_rows` (tiers, offers, free-delivery rules, zone fee, stock) — the cart's engines
    fit           while the total (delivery included) is over the budget: optional items stay unticked; then each
                  line, biggest first, is swapped for a cheaper product of the same kind (Phase 21 kinds, still
                  compatible, enough packs for the same need); then the least essential lines are left out, last
                  first (templates list the main materials first)
    out           the plan within the budget, what was swapped or left out and why, cheaper and premium options
                  (premium only when it still fits), and the whole kit's price as a separate scenario if it's over

The default plan never exceeds the stated budget. Nothing is added to the cart here.
"""

import re
from decimal import Decimal

from apps.ai.projects import builder, flow, kit
from apps.ai.projects.templates import ALL_TEMPLATES, CALCULATORS, TEMPLATES
from apps.ai.quantity.service import QuantityAIService
from apps.ai.services.intent import BUDGET
from apps.catalog import selectors
from apps.catalog.models import ProductVariant
from apps.core.exceptions import ServiceError

from .recommendations import RecommendationService, live

MAX_ROUNDS = 20
TEXT = {
    "en": {
        "need_budget": "Tell me your budget, for example “plumbing materials under ₹5,000”.",
        "unknown": "I couldn't tell what you need. Describe the job (for example “paint a 12x15 room under ₹6,000”) or pick a calculator.",
        "fits": "₹{total} for everything, ₹{left} left of your ₹{budget}.",
        "trimmed": "The full kit costs ₹{full}; this plan keeps to your ₹{budget}.",
        "nothing_fits": "Even the main materials cost more than ₹{budget}. The cheapest full kit is ₹{full}.",
        "swapped": "Swapped for a cheaper product of the same type (saves ₹{saving}).",
        "dropped": "Left out to stay within the budget.",
    },
    "hinglish": {
        "need_budget": "Apna budget bataiye, jaise “plumbing ka saman ₹5,000 ke andar”.",
        "unknown": "Samajh nahi aaya kya chahiye. Kaam bataiye (jaise “12x15 kamre ki putai ₹6,000 ke andar”) ya calculator chunein.",
        "fits": "Sab kuch ₹{total} mein, ₹{budget} mein se ₹{left} bache.",
        "trimmed": "Poora kit ₹{full} ka hai; ye plan ₹{budget} ke andar hai.",
        "nothing_fits": "Main saman bhi ₹{budget} se zyada ka hai. Sabse sasta poora kit ₹{full} ka hai.",
        "swapped": "Usi type ka sasta product (₹{saving} bachat).",
        "dropped": "Budget ke andar rehne ke liye chhoda.",
    },
    "hi": {
        "need_budget": "अपना बजट बताइए, जैसे “प्लंबिंग का सामान ₹5,000 के अंदर”।",
        "unknown": "समझ नहीं आया क्या चाहिए। काम बताइए (जैसे “12x15 कमरे की पुताई ₹6,000 के अंदर”) या कैलकुलेटर चुनें।",
        "fits": "सब कुछ ₹{total} में, ₹{budget} में से ₹{left} बचे।",
        "trimmed": "पूरा किट ₹{full} का है; यह योजना ₹{budget} के अंदर है।",
        "nothing_fits": "मुख्य सामान भी ₹{budget} से ज़्यादा का है। सबसे सस्ता पूरा किट ₹{full} का है।",
        "swapped": "उसी तरह का सस्ता प्रोडक्ट (₹{saving} की बचत)।",
        "dropped": "बजट के अंदर रहने के लिए छोड़ा।",
    },
}


BUDGET_AFTER = re.compile(
    r"\b(?:under|below|within|budget(?:\s+of)?|upto|up\s+to|max(?:imum)?|less\s+than|not\s+more\s+than)\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
BUDGET_BEFORE = re.compile(
    r"(?:₹|rs\.?)?\s*([\d,]+(?:\.\d+)?)\s*(?:rupees?\s*)?(?:ke\s+andar|ke\s+niche|tak|se\s+kam|के\s+अंदर|के\s+भीतर|तक|से\s+कम)",
    re.IGNORECASE,
)


def budget_from_text(text: str) -> Decimal | None:
    """The amount the customer named as the budget: a currency amount ("₹5,000"), the number after "under /
    within / budget" or before "ke andar / tak". Not just any number ("300 sq ft under 1500" → 1500)."""
    for pattern in (BUDGET, BUDGET_AFTER, BUDGET_BEFORE):
        match = pattern.search(text or "")
        if match:
            raw = next(g for g in match.groups() if g)
            try:
                value = Decimal(raw.replace(",", ""))
            except ArithmeticError:
                continue
            if Decimal("0") < value < Decimal("10000000"):
                return value
    return None


class BudgetError(ServiceError):
    default_code = "budget_error"


def t(language: str, key: str, **values) -> str:
    return (TEXT.get(language) or TEXT["en"])[key].format(**values)


def _rupees(value: Decimal) -> str:
    return f"{value:,.0f}"


class BudgetPlanner:
    def __init__(self):
        self.recs = RecommendationService()

    def plan(self, *, text: str = "", budget: Decimal | None = None, calculator: str = "", answers: dict | None = None,
             language: str = "", user=None, postal_code: str = "", address_id: int | None = None) -> dict:  # fmt: skip
        text = " ".join((text or "").split())[: builder.MAX_DESCRIPTION]
        language = flow.language_for(text, language)
        budget = budget if budget is not None else budget_from_text(text)
        base = {"text": text, "language": language, "budget": f"{budget:.2f}" if budget else None}
        if not budget or budget <= 0:
            return {**base, "complete": False, "message": t(language, "need_budget")}
        requirement = BUDGET_BEFORE.sub(
            " ", BUDGET_AFTER.sub(" ", BUDGET.sub(" ", text))
        )  # "under ₹5,000" isn't a measurement
        key = (
            calculator
            if calculator in ALL_TEMPLATES
            else (QuantityAIService().detect(requirement) or flow.detect_type(requirement, TEMPLATES))
        )
        if not key:
            return {
                **base,
                "complete": False,
                "message": t(language, "unknown"),
                "best_for_budget": self._products_within(budget, requirement),
            }
        template = ALL_TEMPLATES[key]
        reading = flow.read_description(template, requirement) if requirement.strip() else flow.Reading({})
        given, errors, notes = flow.clean_answers_noted(template, answers or {})
        if errors:
            raise BudgetError("Some answers aren't valid.", code="invalid_answers", details=errors)
        merged = {k: v for k, v in {**reading.answers, **given}.items() if v is not None}
        state = flow.resolve(template, merged)
        result = {
            **base,
            "calculator": key,
            "is_calculator": key in CALCULATORS,
            "name": template.name.get(language) or template.name["en"],
            "answers": merged,
            "interpretations": reading.notes + notes,
            "questions": [q.describe(language) for q in template.questions if q.applies(state.answers)],
            "missing": [q.key for q in state.missing],
            "assumptions": flow.describe_assumptions(template, state, language),
            "complete": state.complete,
            **builder.guidance(template, state, language),
        }
        if not state.complete:
            # the questions, and meanwhile products within the budget for the words used ("drill bits under 1000")
            result["best_for_budget"] = self._products_within(budget, requirement)
            return result
        needs = builder.materials_for(template, state.answers)
        lines = kit.need_lines(needs, language)
        full = self._price(lines, user, postal_code, address_id)
        full_total = Decimal(full["totals"]["grand_total"])
        swapped, dropped = [], []
        priced = full
        for _ in range(MAX_ROUNDS):
            total = Decimal(priced["totals"]["grand_total"])
            if total <= budget or not any(line["included"] for line in lines):
                break
            if self._swap_cheaper(lines, swapped, language):
                priced = self._price(lines, user, postal_code, address_id)
                continue
            if not self._drop_one(lines, dropped, language):
                break
            priced = self._price(lines, user, postal_code, address_id)
        total = Decimal(priced["totals"]["grand_total"])
        within = total <= budget and any(line["included"] and line["variant"] is not None for line in lines)
        if not within:  # nothing could be bought within the budget: an empty default plan, the kit as a scenario
            for line in lines:
                if line["included"]:
                    line["included"] = False
                    dropped.append(
                        {"key": line["material_key"], "label": line["label"], "reason": t(language, "dropped")}
                    )
            priced = self._price(lines, user, postal_code, address_id)
            total = Decimal(priced["totals"]["grand_total"])
        remaining = budget - total
        message = t(language, "fits", total=_rupees(total), left=_rupees(remaining), budget=_rupees(budget))
        if dropped or swapped:
            message = t(language, "trimmed", full=_rupees(full_total), budget=_rupees(budget)) + " " + message
        if not within:
            message = t(language, "nothing_fits", budget=_rupees(budget), full=_rupees(full_total))
        result.update(
            kit=priced,
            total=f"{total:.2f}",
            remaining=f"{remaining:.2f}",
            within_budget=within,
            message=message,
            swapped=swapped,
            dropped=dropped,
            full_kit_total=f"{full_total:.2f}",
            full_kit_over_budget=full_total > budget,
            savings={
                "vs_mrp": priced["totals"]["savings_vs_mrp"],
                "bulk": priced["totals"]["bulk_savings"],
                "offers": priced["totals"]["offer_discount"],
            },
            unavailable=[i["label"] for i in priced["items"] if i["status"] == "not_found"],
            cheaper_options=self._cheaper_options(lines),
            premium_options=self._premium_options(lines, remaining),
        )
        return result

    # --- Steps -------------------------------------------------------------------------------------------

    @staticmethod
    def _price(lines, user, postal_code, address_id) -> dict:
        rows = [
            kit.Row(
                line["material_key"],
                line["material_key"],
                line["label"],
                line["variant"],
                int(line["quantity"]),
                line["included"],
                line["details"],
                line["rationale"],
                line["unit"],
                line["is_optional"],
                line["is_estimate"],
                line.get("customer_set", False),
            )  # fmt: skip
            for line in lines
        ]
        return kit.price_rows(rows, user=user, postal_code=postal_code, address_id=address_id)

    def _swap_cheaper(self, lines, swapped, language) -> bool:
        """The most expensive ticked line that has a cheaper product of the same kind: swap it (one per round)."""
        from apps.orders.pricing import line_from_variant

        candidates = sorted(
            [
                line
                for line in lines
                if line["included"] and line["variant"] is not None and not line.get("budget_swapped")
            ],
            key=lambda line: -line_from_variant(line["variant"], int(line["quantity"])).line_total,
        )
        for line in candidates:
            line["budget_swapped"] = True  # tried once, whatever the outcome
            product = selectors.product_queryset().filter(pk=line["variant"].product_id).first()
            if product is None:
                continue
            current = line_from_variant(line["variant"], int(line["quantity"])).line_total
            for suggestion in self.recs.alternatives(product):
                alt = live().filter(pk=suggestion.product_id).first()
                variant = (
                    ProductVariant.objects.select_related("product")
                    .filter(pk=getattr(alt, "cheapest_variant_id", None))
                    .first()
                )
                if variant is None:
                    continue
                count, size = kit.regather(line["details"], variant)
                cost = line_from_variant(variant, count).line_total
                if cost < current:
                    swapped.append({"key": line["material_key"], "label": line["label"], "from": line["variant"].product.name, "to": variant.product.name,
                                    "saving": f"{current - cost:.2f}", "reason": t(language, "swapped", saving=_rupees(current - cost))})  # fmt: skip
                    line.update(variant=variant, quantity=count)
                    line["details"] = {
                        **line["details"],
                        "pack_amount": size,
                        "pack_explanation": "",
                        "product_id": variant.product_id,
                    }
                    return True
        return False

    @staticmethod
    def _drop_one(lines, dropped, language) -> bool:
        ticked = [line for line in lines if line["included"]]
        if not ticked:
            return False
        line = ticked[-1]  # templates list the main materials first: the last ticked line is the least essential
        line["included"] = False
        dropped.append({"key": line["material_key"], "label": line["label"], "reason": t(language, "dropped")})
        return True

    def _cheaper_options(self, lines) -> list[dict]:
        out = []
        for line in lines:
            if not line["included"] or line["variant"] is None:
                continue
            product = selectors.product_queryset().filter(pk=line["variant"].product_id).first()
            options = [s for s in self.recs.alternatives(product)] if product else []
            cheaper = next((s for s in options if "less." in s.reason), None)
            if cheaper:
                out.append({"key": line["material_key"], "product_id": cheaper.product_id, "reason": cheaper.reason})
        return out

    def _premium_options(self, lines, remaining: Decimal) -> list[dict]:
        """A better-rated product of the same kind, only when the swap still fits the budget."""
        from apps.orders.pricing import line_from_variant

        out = []
        for line in lines:
            if not line["included"] or line["variant"] is None or remaining <= 0:
                continue
            product = selectors.product_queryset().filter(pk=line["variant"].product_id).first()
            if product is None:
                continue
            current = line_from_variant(line["variant"], int(line["quantity"])).line_total
            category = product.subcategory_id or product.category_id
            for row in (
                live()
                .filter(subcategory_id=product.subcategory_id)
                .exclude(pk=product.pk)
                .order_by("-rating_avg", "-price")[:10]
                if category
                else []
            ):
                variant = ProductVariant.objects.select_related("product").filter(pk=row.cheapest_variant_id).first()
                if variant is None or row.rating_avg <= product.rating_avg:
                    continue
                count, _ = kit.regather(line["details"], variant)
                extra = line_from_variant(variant, count).line_total - current
                if Decimal("0") < extra <= remaining:
                    out.append(
                        {
                            "key": line["material_key"],
                            "product_id": row.pk,
                            "extra_cost": f"{extra:.2f}",
                            "reason": f"Rated {row.rating_avg:.1f}★; ₹{extra:,.0f} more, still within your budget.",
                        }
                    )
                    break
        return out

    def _products_within(self, budget: Decimal, text: str) -> list[dict]:
        from apps.ai.services.catalog_match import find_products

        words = re.sub(
            r"\b(under|below|within|budget|need|i|want|materials?|saman|samaan|chahiye|ke|andar|tak)\b",
            " ",
            text.lower(),
        )
        match = find_products(" ".join(words.split()), limit=12) if words.strip() else None
        ids = (
            [p.pk for p in match.products if p.price is not None and p.price <= budget]
            if match and match.products
            else []
        )
        if not ids:
            return [s.as_dict() for s in self.recs.within_budget(budget)]
        return [{"product_id": pid, "reason": f"Within ₹{budget:,.0f}."} for pid in ids]
