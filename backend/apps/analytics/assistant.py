"""Business assistant (Phase 24): questions about the shop answered from the reports.

    ask(user, "How much did we sell last month?", store_ids=[…]) → answer

1. Understanding (rules first): the question is matched to one of a fixed list of intents, each of
   which reads one whitelisted report (`reports.REPORTS`). The period ("today", "last month",
   "last 7 days", "September", "is mahine" …), a store named in the question, "top 5" and "compared
   with the previous period" are read from the words. No SQL is ever written or run from the
   question, by rules or by a model.
2. When the rules find no intent and a language model is configured (`LLM_PROVIDER`), the model may
   pick one intent key from the list; anything else is refused. Only the question goes to the model.
3. Numbers come from the report. The answer sentence is built from them; a model may reword it,
   but the rewording is used only if every number in it appears in the facts it was given (no
   invented figures) and it is never given customer names or table rows.
4. Store managers are limited to their stores before anything runs; naming another store doesn't
   widen that.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.dashboard.scope import MAX_RANGE_DAYS, local_day_start
from integrations.llm import ChatOptions, LLMError, get_llm_provider

from . import reports
from .reports import MONEY, PERCENT, Scope

MAX_QUESTION = 300
MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan", "जनवरी"),
            ("february", "feb", "फ़रवरी", "फरवरी"),
            ("march", "mar", "मार्च"),
            ("april", "apr", "अप्रैल"),
            ("may", "मई"),
            ("june", "jun", "जून"),
            ("july", "jul", "जुलाई"),
            ("august", "aug", "अगस्त"),
            ("september", "sep", "sept", "सितंबर", "सितम्बर"),
            ("october", "oct", "अक्टूबर"),
            ("november", "nov", "नवंबर", "नवम्बर"),
            ("december", "dec", "दिसंबर", "दिसम्बर"),
        ),
        start=1,
    )
    for name in names
}


@dataclass(frozen=True)
class Intent:
    key: str
    label: str
    report: str
    patterns: tuple[str, ...]
    kpis: tuple[str, ...]  # quoted in the answer, in order
    table: str = ""  # shown under the answer
    example: str = ""
    lead: str = ""  # said first, before the numbers
    exact: bool = False  # never reworded by a model (the wording matters more than the tone)


# Order matters: the first intent whose pattern matches wins, so specific ones come first.
INTENTS: tuple[Intent, ...] = (
    Intent(
        "profit",
        "Profit and margin",
        "margin",
        (r"\b(profit|margin|munafa|munaafa|kamai\s+kitni\s+bachi)\b", r"मुनाफ़?ा", r"\bmarkup\b"),
        ("mrp_value", "selling_value", "promotions", "realisation", "gross_margin"),
        "categories",
        "What is our profit margin this month?",
        "Profit and gross margin can't be calculated yet: purchase costs aren't recorded. What the data does show:",
        exact=True,
    ),
    Intent(
        "slow_products",
        "Slow-moving products",
        "products",
        (r"\b(slow|not\s+selling|dead\s+stock|least\s+sold|worst\s+selling|nahi\s+bik\w*)\b", r"नहीं\s+बिक"),
        ("products_sold", "units"),
        "slow",
        "Which products are not selling?",
    ),
    Intent(
        "top_products",
        "Best-selling products",
        "products",
        (
            r"\b(top|best|most)\b.*\b(product|products|item|items|seller|sellers|selling|sold)\b",
            r"\bbest\s*sellers?\b",
            r"\bsabse\s+(zyada|jyada)\s+bik\w*",
            r"सबसे\s+ज़?्यादा\s+बिक",
        ),
        ("units", "sales", "top_product"),
        "top",
        "What are our top 10 products this month?",
    ),
    Intent(
        "low_stock",
        "Low stock",
        "inventory",
        (
            r"\b(low\s+(on\s+)?stock|out\s+of\s+stock|stock\s*out|reorder|restock|running\s+(out|low)|khatam)\b",
            r"स्टॉक\s+(कम|ख़?त्म)",
        ),
        ("low_stock", "out_of_stock"),
        "attention",
        "Which items are low on stock?",
    ),
    Intent(
        "inventory",
        "Inventory",
        "inventory",
        (r"\b(stock|inventory|stock\s+value|godown|maal)\b", r"स्टॉक"),
        ("units", "value", "low_stock", "out_of_stock"),
        "stores",
        "What is our stock value?",
    ),
    Intent(
        "categories",
        "Categories",
        "categories",
        (r"\b(category|categories|department|departments)\b", r"श्रेणी"),
        ("sales", "top_category", "top_share"),
        "categories",
        "Which category sells the most?",
    ),
    Intent(
        "brands",
        "Brands",
        "brands",
        (r"\b(brand|brands|company\s+wise)\b", r"ब्रांड"),
        ("sales", "top_brand"),
        "brands",
        "Which brands sold best last month?",
    ),
    Intent(
        "riders",
        "Delivery partners",
        "riders",
        (r"\b(rider|riders|delivery\s+(partner|partners|boy|boys)|driver|drivers)\b", r"राइडर"),
        ("riders", "jobs", "delivered", "failed", "cod"),
        "riders",
        "How are our riders performing?",
    ),
    Intent(
        "delivery",
        "Delivery performance",
        "delivery",
        (
            r"\b(on[\s-]?time|late|delay\w*|fast\s+delivery|delivery\s+(performance|time|speed)|deliver\w*\s+(late|on\s+time)|eta)\b",
            r"\bdelivery\b.*\b(kitn\w*|how)\b",
        ),
        ("delivered", "on_time_rate", "fast_on_time_rate", "fast_promised", "fast_actual", "failed_attempts"),
        "types",
        "How is fast delivery performing?",
    ),
    Intent(
        "refunds",
        "Returns, refunds and cancellations",
        "returns",
        (r"\b(return|returns|returned|refund|refunds|cancel\w*|wapas|wapsi)\b", r"वापस|रिफंड|रद्द"),
        ("cancelled", "cancellation_rate", "returns", "return_rate", "refunds_processed"),
        "return_reasons",
        "Why are orders being cancelled?",
    ),
    Intent(
        "offers",
        "Offers and coupons",
        "offers",
        (r"\b(coupon|coupons|offer|offers|discount|discounts|promotion\w*|credits?)\b", r"छूट|ऑफ़र|कूपन"),
        ("orders_with_discount", "offer_discount", "coupon_discount", "credits_used"),
        "coupons",
        "How much discount did we give with coupons?",
    ),
    Intent(
        "customers",
        "Customers",
        "customers",
        (r"\b(customer|customers|buyer|buyers|repeat|returning|loyal|grahak)\b", r"ग्राहक"),
        ("customers", "new_customers", "returning_customers", "repeat_rate", "value_per_customer"),
        "segments",
        "How many new customers did we get this month?",
    ),
    Intent(
        "stores",
        "Stores",
        "stores",
        (r"\b(store|stores|warehouse|warehouses|branch|branches|location|locations|dukan)\b", r"दुकान|स्टोर"),
        ("stores", "best_store", "revenue"),
        "stores",
        "Which store has the highest revenue?",
    ),
    Intent(
        "aov",
        "Average order value",
        "sales",
        (r"\b(average\s+order|aov|basket\s+size|order\s+value)\b",),
        ("average_order_value", "paid_orders", "revenue"),
        "",
        "What is our average order value?",
    ),
    Intent(
        "orders",
        "Orders",
        "orders",
        (r"\b(how\s+many\s+orders|orders?|order\s+count|kitne\s+order)\b", r"ऑर्डर"),
        ("orders", "delivered", "in_progress", "cancelled", "cancellation_rate"),
        "statuses",
        "How many orders did we get today?",
    ),
    Intent(
        "revenue",
        "Sales and revenue",
        "sales",
        (
            r"\b(revenue|sales|sale|sold|sell|selling|turnover|income|earn\w*|kamai|bikri|bikree|business)\b",
            r"बिक्री|कमाई|आमदनी",
        ),
        ("revenue", "net_revenue", "paid_orders", "average_order_value", "refunded"),
        "payment_methods",
        "How much did we sell last month?",
    ),
)
INTENT_BY_KEY = {intent.key: intent for intent in INTENTS}
SUGGESTIONS = [intent.example for intent in INTENTS if intent.example][:8]


@dataclass
class Reading:
    intent: Intent | None
    first: date
    last: date
    period_label: str
    compare: bool = False
    top: int | None = None
    store_name: str = ""
    source: str = "rules"
    notes: list[str] = field(default_factory=list)


# --- Period ------------------------------------------------------------------------------------------


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def read_period(text: str, today: date) -> tuple[date, date, str] | None:
    t = text.lower()
    dates = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", t)
    if len(dates) >= 2:
        try:
            a, b = sorted(date.fromisoformat(d) for d in dates[:2])
            return a, b, f"{a.isoformat()} to {b.isoformat()}"
        except ValueError:
            pass
    if re.search(r"\b(today|aaj)\b|आज", t):
        return today, today, "today"
    if re.search(r"\b(yesterday|kal)\b|कल", t):
        day = today - timedelta(days=1)
        return day, day, "yesterday"
    if m := re.search(
        r"\b(?:last|past|pichhle|pichle|previous)\s+(\d{1,3})\s+(day|days|din|week|weeks|month|months)\b", t
    ):
        n, unit = int(m.group(1)), m.group(2)
        days = n * (7 if unit.startswith("week") else 30 if unit.startswith("month") else 1)
        days = min(max(days, 1), MAX_RANGE_DAYS)
        return today - timedelta(days=days - 1), today, f"the last {days} days"
    if re.search(r"\b(this|current)\s+week\b|\bis\s+hafte\b|इस\s+हफ़?्ते", t):
        return today - timedelta(days=today.weekday()), today, "this week"
    if re.search(r"\b(last|previous)\s+week\b|\bpichh?le\s+hafte\b|पिछले\s+हफ़?्ते", t):
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=6), "last week"
    if re.search(r"\b(last|previous)\s+month\b|\bpichh?le\s+mahine\b|पिछले\s+महीने", t):
        prev = today.replace(day=1) - timedelta(days=1)
        a, b = _month_bounds(prev.year, prev.month)
        return a, b, prev.strftime("%B %Y")
    if re.search(r"\b(this|current)\s+month\b|\bis\s+mahine\b|इस\s+महीने|\bmtd\b", t):
        return today.replace(day=1), today, "this month"
    if re.search(r"\b(this|current)\s+year\b|\bytd\b|\bis\s+saal\b|इस\s+साल", t):
        first = today.replace(month=1, day=1)
        return max(first, today - timedelta(days=MAX_RANGE_DAYS - 1)), today, "this year"
    for word, month in MONTHS.items():
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", t) and not (
            word == "may" and re.search(r"\bmay\s+(i|we|you)\b", t)
        ):
            year = today.year if month <= today.month else today.year - 1
            a, b = _month_bounds(year, month)
            return a, min(b, today), date(year, month, 1).strftime("%B %Y")
    return None


# --- Understanding ------------------------------------------------------------------------------------


def _match_intent(text: str) -> Intent | None:
    t = text.lower()
    for intent in INTENTS:
        if any(re.search(p, t) for p in intent.patterns):
            return intent
    return None


def _ask_model(text: str) -> Intent | None:
    provider = get_llm_provider()
    if not provider.available:
        return None
    choices = "\n".join(f"- {i.key}: {i.label} (e.g. {i.example})" for i in INTENTS)
    messages = [
        {
            "role": "system",
            "content": "You route a shop owner's question to one report. Answer only with JSON "
            '{"intent": "<key>"} using a key from the list, or {"intent": ""} if none fits.\n' + choices,
        },
        {"role": "user", "content": text},
    ]
    try:
        key = str(
            provider.chat(messages, ChatOptions(json=True, max_tokens=40, temperature=0)).json().get("intent", "")
        )
    except (LLMError, AttributeError, TypeError, ValueError):
        return None
    return INTENT_BY_KEY.get(key.strip())


def understand(text: str, *, stores: list, today: date | None = None, use_model: bool = True) -> Reading:
    """`stores`: (id, name) pairs the user may see, to recognise a store named in the question."""
    today = today or timezone.localdate()
    intent = _match_intent(text)
    source = "rules"
    if intent is None and use_model:
        intent = _ask_model(text)
        source = "ai" if intent else "rules"
    period = read_period(text, today)
    first, last, label = period or (today - timedelta(days=29), today, "the last 30 days")
    reading = Reading(intent, first, last, label, source=source)
    reading.compare = bool(
        re.search(r"\b(compar\w*|vs\.?|versus|growth|grew|change|previous\s+period|than\s+last)\b", text.lower())
    )
    if m := re.search(r"\btop\s+(\d{1,2})\b", text.lower()):
        reading.top = max(1, min(int(m.group(1)), 50))
    lowered = text.lower()
    for _store_id, name in stores:
        words = [
            w
            for w in re.findall(r"[a-z0-9]+", name.lower())
            if len(w) > 3 and w not in {"demo", "store", "dark", "warehouse"}
        ]
        if name.lower() in lowered or any(re.search(rf"\b{re.escape(w)}\b", lowered) for w in words):
            reading.store_name = name
            reading.notes.append(f"Only {name}.")
            break
    return reading


# --- Answering ------------------------------------------------------------------------------------------


def inr(amount: Decimal) -> str:
    """₹ with Indian digit grouping: 1234567.5 → ₹12,34,567.50."""
    sign = "-" if amount < 0 else ""
    whole, _, paise = f"{abs(amount):.2f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}₹{','.join([*groups, tail])}.{paise}"


def _display(value, fmt: str) -> str:
    if value is None:
        return "not available"
    if fmt == MONEY:
        return inr(Decimal(value))
    if fmt == PERCENT:
        return f"{value}%"
    if fmt == "minutes":
        return f"{value} min"
    return f"{value:,}" if isinstance(value, int) else str(value)


def _sentence(intent: Intent, kpis: dict, label: str) -> str:
    parts = [f"{kpis[k]['label']}: {_display(kpis[k]['value'], kpis[k]['format'])}" for k in intent.kpis if k in kpis]
    lead = f"{intent.lead} " if intent.lead else ""
    return f"{lead}{intent.label} for {label} — " + "; ".join(parts) + "."


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def _reworded(question: str, facts: str) -> str | None:
    """A friendlier sentence from the model, accepted only if it adds no number of its own."""
    provider = get_llm_provider()
    if not provider.available:
        return None
    messages = [
        {
            "role": "system",
            "content": "You are a shop's business assistant. Answer the owner's question in 1-3 short "
            "sentences using ONLY these facts. Do not add, estimate or calculate any other number, do not judge the "
            'results (no "strong", "good", "poor"), keep each figure with its own label, and say "not available" '
            "where a fact says so.\nFacts: " + facts,
        },
        {"role": "user", "content": question},
    ]
    try:
        reply = provider.chat(messages, ChatOptions(max_tokens=160, temperature=0.2)).content.strip()
    except LLMError:
        return None
    allowed, used = _numbers(facts), _numbers(reply)
    if not reply or not used or not used <= allowed:  # must quote the facts and add nothing
        return None
    return reply[:600]


def answer(question: str, *, store_ids, stores: list, today: date | None = None, use_model: bool = True) -> dict:
    """Read the question, run its report for the period and the user's stores, and answer from it."""
    question = " ".join((question or "").split())[:MAX_QUESTION]
    reading = understand(question, stores=stores, today=today, use_model=use_model)
    base = {
        "question": question,
        "understood": reading.intent is not None,
        "suggestions": SUGGESTIONS,
    }
    if reading.intent is None:
        return {
            **base,
            "intent": None,
            "text": "I can answer questions about sales, orders, products, categories, brands, stock, fast delivery, "
            "riders, customers, returns and refunds, offers and coupons, stores, and price realisation. Try one of the "
            "suggestions.",
            "source": "rules",
        }
    scope_ids = store_ids
    if reading.store_name:
        named = [pk for pk, name in stores if name == reading.store_name]
        scope_ids = named if store_ids is None else [pk for pk in named if pk in store_ids]
    days = (reading.last - reading.first).days + 1
    period = "day" if days <= 45 else "week" if days <= 180 else "month"
    scope = Scope(
        scope_ids,
        reading.first,
        reading.last,
        local_day_start(reading.first),
        local_day_start(reading.last + timedelta(days=1)),
        period,
    )
    data = reports.build(reading.intent.report, scope)
    kpis = {k["key"]: k for k in data["kpis"]}
    text = _sentence(reading.intent, kpis, reading.period_label)
    comparison = None
    if reading.compare:
        prev_last = reading.first - timedelta(days=1)
        prev_first = prev_last - timedelta(days=days - 1)
        prev_scope = Scope(
            scope_ids,
            prev_first,
            prev_last,
            local_day_start(prev_first),
            local_day_start(prev_last + timedelta(days=1)),
            period,
        )
        before = {k["key"]: k for k in reports.build(reading.intent.report, prev_scope)["kpis"]}
        main = next(
            (k for k in reading.intent.kpis if k in kpis and kpis[k]["format"] in (MONEY, "count", "number")), None
        )
        if main and before.get(main):
            now_v, prev_v = Decimal(str(kpis[main]["value"] or 0)), Decimal(str(before[main]["value"] or 0))
            change = round(float((now_v - prev_v) * 100 / prev_v), 1) if prev_v else None
            comparison = {
                "kpi": main,
                "label": kpis[main]["label"],
                "current": kpis[main]["value"],
                "previous": before[main]["value"],
                "change_percent": change,
                "format": kpis[main]["format"],
                "previous_period": {"from": prev_first.isoformat(), "to": prev_last.isoformat()},
            }
            text += (
                f" Previous {days} days ({prev_first.isoformat()} to {prev_last.isoformat()}): "
                f"{_display(before[main]['value'], kpis[main]['format'])}"
                + (f" ({'+' if change >= 0 else ''}{change}%)." if change is not None else ".")
            )
    table = next((t for t in data["tables"] if t["key"] == reading.intent.table), None)
    if table is not None:
        table = {**table, "rows": table["rows"][: reading.top or 10]}
    source = reading.source
    if use_model and not reading.intent.exact:
        better = _reworded(question, text)
        if better:
            text, source = better, "ai"
    link = (
        f"/admin/reports?report={reading.intent.report}&from={reading.first.isoformat()}&to={reading.last.isoformat()}"
    )
    return {
        **base,
        "intent": reading.intent.key,
        "intent_label": reading.intent.label,
        "report": reading.intent.report,
        "period": {"from": reading.first.isoformat(), "to": reading.last.isoformat(), "label": reading.period_label},
        "store": reading.store_name or None,
        "text": text,
        "kpis": [kpis[k] for k in reading.intent.kpis if k in kpis],
        "comparison": comparison,
        "table": table,
        "notes": reading.notes + data["notes"],
        "link": link,
        "source": source,
    }
