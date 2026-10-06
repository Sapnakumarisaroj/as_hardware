# ruff: noqa: E501 — unit words in three languages read better on one line
"""Units for Quantity AI (Phase 20): convert safely, and read measurements out of the customer's words.

Every conversion is between units of the same kind (length, area, volume, weight, count); anything else is
refused. Whenever a value was converted or a unit was assumed ("12x15" without a unit → feet), an
*interpretation* is returned so the page can show it: "5 × 4 m = 16.4 × 13.1 ft".
"""

import re
from dataclasses import dataclass

# unit → (kind, factor to the kind's base unit). Bases: ft, sq ft, l, kg, pcs.
UNITS: dict[str, tuple[str, float]] = {
    "mm": ("length", 1 / 304.8),
    "cm": ("length", 1 / 30.48),
    "m": ("length", 1 / 0.3048),
    "inch": ("length", 1 / 12),
    "ft": ("length", 1.0),
    "sq ft": ("area", 1.0),
    "sq m": ("area", 10.7639),
    "cft": ("volume_solid", 1.0),
    "cu m": ("volume_solid", 35.3147),
    "l": ("volume", 1.0),
    "ml": ("volume", 0.001),
    "kg": ("weight", 1.0),
    "g": ("weight", 0.001),
    "pcs": ("count", 1.0),
    "bags": ("count", 1.0),
    "packs": ("count", 1.0),
}

ALIASES = {
    "millimetre": "mm", "millimeter": "mm", "millimetres": "mm", "millimeters": "mm", "मिमी": "mm",
    "centimetre": "cm", "centimeter": "cm", "centimetres": "cm", "centimeters": "cm", "सेमी": "cm",
    "metre": "m", "meter": "m", "metres": "m", "meters": "m", "mtr": "m", "mtrs": "m", "मीटर": "m",
    "in": "inch", "inches": "inch", '"': "inch", "इंच": "inch",
    "feet": "ft", "foot": "ft", "'": "ft", "फ़ुट": "ft", "फुट": "ft", "fit": "ft",
    "sqft": "sq ft", "sq.ft": "sq ft", "sq. ft": "sq ft", "square feet": "sq ft", "square foot": "sq ft", "वर्ग फ़ुट": "sq ft", "वर्ग फुट": "sq ft",
    "sqm": "sq m", "sq.m": "sq m", "square metre": "sq m", "square meter": "sq m", "square metres": "sq m", "square meters": "sq m", "वर्ग मीटर": "sq m",
    "litre": "l", "liter": "l", "litres": "l", "liters": "l", "ltr": "l", "लीटर": "l",
    "kilo": "kg", "kgs": "kg", "किलो": "kg",
    "gram": "g", "grams": "g", "gm": "g", "ग्राम": "g",
    "piece": "pcs", "pieces": "pcs", "nos": "pcs", "pc": "pcs",
    "bag": "bags", "bori": "bags", "बोरी": "bags",
    "pack": "packs", "packet": "packs", "packets": "packs",
}  # fmt: skip

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


class UnitError(ValueError):
    pass


def canonical(unit: str) -> str:
    unit = " ".join((unit or "").strip().lower().split())
    unit = ALIASES.get(unit, unit)
    if unit not in UNITS:
        raise UnitError(f"Unknown unit “{unit}”.")
    return unit


def kind_of(unit: str) -> str:
    return UNITS[canonical(unit)][0]


def convert(value: float, from_unit: str, to_unit: str) -> float:
    a, b = canonical(from_unit), canonical(to_unit)
    (kind_a, fa), (kind_b, fb) = UNITS[a], UNITS[b]
    if kind_a != kind_b:
        raise UnitError(f"{a} can't be converted to {b}.")
    return value * fa / fb


def units_for(unit: str) -> list[str]:
    """The units a customer may type for a question measured in `unit` (same kind)."""
    try:
        kind = kind_of(unit)
    except UnitError:
        return []
    preferred = {
        "length": ["ft", "m", "cm", "mm", "inch"],
        "area": ["sq ft", "sq m"],
        "volume": ["l", "ml"],
        "weight": ["kg", "g"],
    }
    return preferred.get(kind, [canonical(unit)])


def fmt(value: float, digits: int = 1) -> str:
    """12.0 → "12", 16.404 → "16.4" (for interpretations and breakdowns)."""
    rounded = round(value, digits)
    return str(int(rounded)) if rounded == int(rounded) else f"{rounded:.{digits}f}".rstrip("0").rstrip(".")


# --- Reading measurements from text ---------------------------------------------------------------------

NUMBER = r"(\d+(?:\.\d+)?)"
LENGTH_UNIT = r"(mm|cm|m|mtrs?|metres?|meters?|ft|feet|foot|fit|inch(?:es)?|in|'|\"|मीटर|फ़ुट|फुट|इंच|मिमी|सेमी)"
AREA_UNIT = r"(sq\.?\s*ft|sqft|square\s+(?:feet|foot|ft)|sq\.?\s*m(?:tr|etres?|eters?)?|sqm|square\s+met(?:re|er)s?|वर्ग\s*फ\S*ट|वर्ग\s*मीटर)"
DIMENSIONS = re.compile(
    rf"{NUMBER}\s*{LENGTH_UNIT}?\s*(?:x|×|\*|by|बाई)\s*{NUMBER}\s*{LENGTH_UNIT}?(?:\s*(?:x|×|\*|by)\s*{NUMBER}\s*{LENGTH_UNIT}?)?",
    re.IGNORECASE,
)
AREA = re.compile(rf"{NUMBER}\s*{AREA_UNIT}(?![a-z])", re.IGNORECASE)
LENGTH = re.compile(rf"{NUMBER}\s*{LENGTH_UNIT}(?![a-z])", re.IGNORECASE)


@dataclass
class Reading:
    key: str  # what it answers: length / width / height / area / metres
    value: float  # in the question's unit
    note: str = ""  # the interpretation shown to the customer ("" when nothing needed explaining)


def normalise(text: str) -> str:
    return " ".join((text or "").translate(DEVANAGARI_DIGITS).split())


def _unit(raw: str | None, default: str) -> tuple[str, bool]:
    if not raw:
        return default, True
    try:
        return canonical(raw), False
    except UnitError:
        return default, True


def read_dimensions(text: str, *, unit: str = "ft") -> list[Reading]:
    """ "12x15", "12 x 15 ft", "5m x 4m", "10x12x9" (with height) → length/width(/height) in `unit`.
    A size without any unit is read as feet, and the page says so."""
    match = DIMENSIONS.search(normalise(text))
    if not match:
        return []
    nums = [match.group(1), match.group(3), match.group(5)]
    raw_units = [match.group(2), match.group(4), match.group(6)]
    given = next((u for u in reversed(raw_units) if u), None)  # "5 x 4 m": the last unit applies to all
    out = []
    shown = []
    assumed_any = False
    for key, num, raw in zip(("length", "width", "height"), nums, raw_units, strict=True):
        if num is None:
            continue
        source, assumed = _unit(raw or given, "ft")
        assumed_any = assumed_any or assumed
        value = convert(float(num), source, unit)
        shown.append((float(num), source, value))
        out.append(Reading(key, round(value, 2)))
    if not out:
        return []
    if assumed_any:
        note = f"{' × '.join(fmt(s[0]) for s in shown)} read as feet"
    elif any(s[1] != unit for s in shown):
        note = f"{' × '.join(fmt(s[0]) + ' ' + s[1] for s in shown)} = {' × '.join(fmt(s[2]) for s in shown)} {unit}"
    else:
        note = ""
    out[0].note = note
    return out


def read_area(text: str, *, unit: str = "sq ft") -> Reading | None:
    match = AREA.search(normalise(text))
    if not match:
        return None
    raw = match.group(2).lower()
    source = "sq m" if ("मीटर" in raw or ("f" not in raw and "फ" not in raw)) else "sq ft"
    value = convert(float(match.group(1)), source, unit)
    note = "" if source == unit else f"{fmt(float(match.group(1)))} {source} = {fmt(value)} {unit}"
    return Reading("area", round(value, 2), note)


def read_length(text: str, *, unit: str = "m") -> Reading | None:
    """A run of wire or pipe: "100 feet", "30 m", "30 मीटर" (not a room size, not "sq ft", not "1.5 sq mm")."""
    cleaned = AREA.sub(" ", DIMENSIONS.sub(" ", normalise(text)))
    for match in LENGTH.finditer(cleaned):
        raw = match.group(2)
        if raw in ("'", '"') or re.match(r"(mm|cm|in|inch)", raw, re.IGNORECASE):
            continue  # sizes of a part ("1/2 inch", "25 mm"), not a run length
        before = cleaned[: match.start()].rstrip()
        if before.endswith("sq"):
            continue
        source = canonical(raw)
        value = convert(float(match.group(1)), source, unit)
        note = "" if source == unit else f"{fmt(float(match.group(1)))} {source} = {fmt(value)} {unit}"
        return Reading("metres", round(value, 2), note)
    return None
