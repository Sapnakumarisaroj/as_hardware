"""Grounding checks for model-written text.

A language model may phrase things, but it is never the source of a price, a stock level, a SKU, a size or a
total. Every piece of model text that reaches a customer passes these checks first; text that fails is dropped
and the fixed (rule-based) text stands.

- `numbers_in`: the numbers a text contains, in one canonical form ("₹1,500" → "1500", "५००" → "500").
- `ungrounded_numbers`: numbers in a model's text that none of the given sources (the customer's own words,
  the product names, the engine's facts) contain.
- `mentions_money`: rupee amounts and price words in English, Hinglish and Hindi ("500/-", "Rs.", "INR",
  "rupaye", "₹", "कीमत").
- `grounded`: both checks together.
"""

import re

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
MONEY = re.compile(
    r"₹|\brs\b\.?|\binr\b|\brupees?\b|\brupaye\b|\brupay\b|\brupiya\b|\brupaiye\b|रुपये|रुपए|रुपया|रु\.|"
    r"\d\s*/-|\bprice[sd]?\b|\bpricing\b|\bmrp\b|\bdaam\b|\bkeemat\b|\bkimat\b|कीमत|दाम|मूल्य",
    re.IGNORECASE,
)


def normalise_digits(text: str) -> str:
    return (text or "").translate(DEVANAGARI_DIGITS)


def _canonical(raw: str) -> str:
    value = raw.replace(",", "")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value.lstrip("0") or "0"


def numbers_in(text: str) -> set[str]:
    """Every number in `text`, canonical: thousands commas dropped, "2.50" → "2.5", Devanagari digits read."""
    return {_canonical(raw.rstrip(",")) for raw in _NUMBER.findall(normalise_digits(text))}


def number_said(value, text: str) -> bool:
    """Whether the number `value` (int, float, Decimal or str) appears in `text`."""
    return _canonical(f"{value}") in numbers_in(text) if value is not None else False


def ungrounded_numbers(candidate: str, *sources: str) -> set[str]:
    allowed: set[str] = set()
    for source in sources:
        allowed |= numbers_in(source)
    return numbers_in(candidate) - allowed


def mentions_money(text: str) -> bool:
    return bool(MONEY.search(normalise_digits(text)))


def grounded(candidate: str, *sources: str) -> bool:
    """No money talk, and no number the sources don't contain."""
    return not mentions_money(candidate) and not ungrounded_numbers(candidate, *sources)
