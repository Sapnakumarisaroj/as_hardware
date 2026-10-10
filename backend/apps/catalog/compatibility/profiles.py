# ruff: noqa: E501 — pattern tables read better on one line
"""What a product *is* and what its listing says, for compatibility (Phase 21).

A profile is built only from the catalogue: the product's name, category, tags, specifications, variant names and
option values. A value that the listing doesn't state stays missing (None) — it is never guessed. Kinds are
recognised by `KINDS` (data, in order: the first match wins), so a new kind of product is one more entry.
"""

import re
from dataclasses import dataclass, field

# kind → (name patterns, category words or None for any category, excluded name words)
KINDS: list[tuple[str, tuple[str, ...], tuple[str, ...] | None, tuple[str, ...]]] = [
    ("drill_bit", (r"\bdrill\s+bits?\b", r"\bbit\s+set\b", r"\bbits?\b"), ("tool", "drill"), ()),
    ("drill", (r"\bdrill\b", r"\bdrill\s+driver\b", r"\bhammer\s+drill\b"), ("tool", "power"), ("bit",)),
    ("wall_plug", (r"\bwall\s+plugs?\b", r"\banchors?\b", r"\brawl\s*plugs?\b"), None, ()),
    # Glass door hardware (before hinges, handles and locks: a "glass door handle" is a glass fitting)
    (
        "glass_fitting",
        (
            r"\bpatch\s+fittings?\b",
            r"\bfloor\s+springs?\b",
            r"\bglass\s+(clamps?|connectors?|brackets?|hinges?|locks?)\b",
            r"\bglass\s+door\b.*\b(handles?|locks?|fittings?|hinges?)\b",
            r"\bshower\s+hinges?\b",
            r"\bspider\s+fittings?\b",
        ),
        None,
        ("sealant", "silicone", "goggle"),
    ),  # fmt: skip
    (
        "glass",
        (
            r"\b(toughened|tempered|float|clear|frosted|laminated)\s+glass\b",
            r"\bglass\s+(sheets?|panels?|panes?|partitions?)\b",
        ),
        None,
        (
            "fitting",
            "handle",
            "spring",
            "clamp",
            "sealant",
            "silicone",
            "hinge",
            "lock",
            "goggle",
            "connector",
            "cleaner",
        ),
    ),  # fmt: skip
    # Furniture and door hardware (approved departments: hinges/channels/handles, locks, boards)
    (
        "door_lock",
        (
            r"\bmortise\b.*\blocks?\b",
            r"\bmortice\b.*\blocks?\b",
            r"\bdoor\s+locks?\b",
            r"\b(knob|cylindrical|lever|tubular)\s+locks?\b",
            r"\bdead\s*bolts?\b",
        ),
        None,
        ("padlock", "glass"),
    ),  # fmt: skip
    (
        "door",
        (r"\bflush\s+doors?\b", r"\bdoor\s+(shutters?|leaf|leaves|panels?)\b", r"\b(wooden|membrane|panel)\s+doors?\b"),
        None,
        ("lock", "closer", "hinge", "handle", "stopper", "glass", "sliding", "fitting", "bolt", "spring", "kit"),
    ),  # fmt: skip
    ("hinge", (r"\bhinges?\b",), None, ("glass", "floor", "shower", "screw")),
    (
        "drawer_channel",
        (
            r"\bdrawer\s+(channels?|slides?|runners?)\b",
            r"\btelescopic\s+(channels?|slides?)\b",
            r"\bball[\s-]*bearing\s+(channels?|slides?)\b",
            r"\btandem\s+box",
            r"\bundermount\s+(channels?|slides?)\b",
        ),
        None,
        ("handle",),
    ),  # fmt: skip
    (
        "handle",
        (r"\bhandles?\b", r"\bknobs?\b"),
        None,
        ("lock", "glass", "hammer", "screwdriver", "drill", "saw", "brush", "roller", "spanner", "wrench", "trowel"),
    ),  # fmt: skip
    (
        "board",
        (r"\bplywood\b", r"\bply\b", r"\bmdf\b", r"\bhdhmr\b", r"\b(particle|block|pre-?laminated)\s*boards?\b"),
        None,
        ("adhesive", "glue", "screw", "cutter", "saw", "edge"),
    ),  # fmt: skip
    ("screw", (r"\bscrews?\b",), None, ("screwdriver",)),
    ("bolt", (r"\bbolts?\b",), None, ("tower", "door bolt")),
    ("spanner", (r"\bspanners?\b",), None, ()),
    ("pipe", (r"\bpipes?\b",), ("plumb", "pipe"), ("wrench", "tape", "sealant")),
    (
        "pipe_fitting",
        (
            r"\belbows?\b",
            r"\btees?\b",
            r"\bcouplers?\b",
            r"\bvalves?\b",
            r"\bunions?\b",
            r"\badapters?\b",
            r"\bconnectors?\b",
            r"\bbends?\b",
        ),
        ("plumb", "fitting"),
        (),
    ),  # fmt: skip
    ("tap", (r"\btaps?\b", r"\bfaucets?\b"), ("plumb", "sanitary", "bath"), ()),
    ("mcb", (r"\bmcbs?\b", r"\bcircuit\s+breakers?\b"), None, ()),
    ("switch", (r"\bswitch(es)?\b",), ("electric",), ("screwdriver",)),
    ("socket", (r"\bsockets?\b",), ("electric",), ("spanner",)),
    ("wire", (r"\bwires?\b", r"\bcables?\b"), ("wire", "cable", "electric"), ("tie", "stripper", "cutter")),
    ("bulb", (r"\bbulbs?\b", r"\blamps?\b"), ("electric", "light"), ()),
    ("holder", (r"\bholders?\b", r"\bbatten\s+holder\b"), ("electric", "light"), ()),
]

# Wood screw gauge → shank diameter (mm), the common Indian/British sizes.
SCREW_GAUGE_MM = {4: 2.8, 5: 3.1, 6: 3.5, 7: 3.8, 8: 4.2, 9: 4.5, 10: 4.8, 12: 5.5, 14: 6.3}
NUMBER = r"(\d+(?:\.\d+)?)"
MM_PER_INCH = 25.4
# Drawer channels are sold by nominal inch length; the trade's millimetre equivalents (a "18 inch" channel is a
# 450 mm channel). Other inch lengths are converted exactly.
CHANNEL_INCH_MM = {10: 250, 12: 300, 14: 350, 16: 400, 18: 450, 20: 500, 22: 550, 24: 600}
OVERLAYS = {
    "full": r"\bfull\s*(overlay|cover)\b|\bstraight\b",
    "half": r"\bhalf\s*(overlay|cover)\b|\bhalf\s*crank",
    "inset": r"\binset\b|\bin-?set\b|\bfull\s*crank",
}


@dataclass
class Profile:
    product: object
    variant: object | None
    kind: str | None
    values: dict = field(default_factory=dict)  # normalised facts (see build); missing = not in the listing
    sources: dict = field(default_factory=dict)  # fact → where it was read ("spec Chuck Size", "variant 1/2 inch")

    @property
    def name(self) -> str:
        if self.variant is not None and self.variant.name:
            return f"{self.product.name} ({self.variant.name})"
        return self.product.name


def kind_of(product) -> str | None:
    name = product.name.lower()
    category = " ".join(filter(None, [product.category.name, getattr(product.subcategory, "name", "") or ""])).lower()
    for kind, patterns, categories, excluded in KINDS:
        if any(word in name for word in excluded):
            continue
        if categories is not None and not any(word in category or word in name for word in categories):
            continue
        if any(re.search(pattern, name) for pattern in patterns):
            return kind
    return None


def _spec(product, *keys) -> tuple[str, str] | None:
    """(value with unit, spec name) of the first specification found among `keys`."""
    by_key = {s.key: s for s in product.specifications.all()}
    for key in keys:
        if key in by_key:
            s = by_key[key]
            return f"{s.value} {s.unit}".strip(), s.name
    return None


def mm_values(text: str) -> list[float]:
    """ "5, 6, 8, 10, 12 mm" → [5, 6, 8, 10, 12]; "13 mm" → [13]."""
    if not re.search(r"mm\b", text, re.IGNORECASE):
        return []
    return [float(n) for n in re.findall(NUMBER, text)]


def mm_range(text: str) -> tuple[float, float] | None:
    """ "1.5 - 6.5 mm" → (1.5, 6.5); a list "5, 6, 8 mm" → (5, 8)."""
    values = mm_values(text)
    return (min(values), max(values)) if values else None


def amps(text: str) -> list[float]:
    """ "6 A" → [6]; "6/16A" → [6, 16]."""
    match = re.search(r"(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)\s*a\b", text, re.IGNORECASE)
    return [float(n) for n in re.findall(NUMBER, match.group(1))] if match else []


def nominal_sizes(text: str) -> set[str]:
    """Nominal pipe/thread sizes: "1/2 inch", "3/4\"", "1 inch", "1/2 x 1/2 inch" → {"1/2"}, …"""
    text = text.lower()
    sizes = set(re.findall(r"(\d+/\d+)\s*(?:x\s*\d+/\d+\s*)?(?:inch|in\b|\"|”)", text))
    sizes |= set(re.findall(r"(\d+/\d+)\s*x\s*\d+/\d+", text))
    sizes |= {m for m in re.findall(r"(?<![/\d.])(\d)\s*(?:inch|in\b|\"|”)", text)}  # "1 inch", not the 2 of "1/2"
    return sizes


def channel_length_mm(text: str) -> float | None:
    """ "18 inch" → 450 (the trade's nominal size), "450 mm" → 450; None when no length is stated."""
    if match := re.search(r"(\d+(?:\.\d+)?)\s*(?:inch(?:es)?|in\b|\"|”)", text.lower()):
        inches = float(match.group(1))
        return (
            float(CHANNEL_INCH_MM.get(int(inches), round(inches * MM_PER_INCH)))
            if inches == int(inches)
            else round(inches * MM_PER_INCH)
        )
    values = [v for v in mm_values(text) if v >= 150]  # a channel is at least 150 mm; smaller numbers are not lengths
    return values[0] if values else None


def overlay_of(text: str) -> str | None:
    """Concealed-hinge overlay named in a listing text: full, half or inset."""
    return next((name for name, pattern in OVERLAYS.items() if re.search(pattern, text, re.IGNORECASE)), None)


# Variant facts that become lists for a whole product (every variant's value): single key → list key.
PLURALS = {
    "thickness_mm": "thicknesses",
    "channel_mm": "channel_lengths",
    "overlay": "overlays",
    "cc_mm": "ccs",
    "screw_len_mm": "screw_lens",
    "metric_thread": "metric_threads",
}


def _variant_texts(variant) -> list[str]:
    return [variant.name or ""] + [o.value.value for o in variant.option_values.all()]


def build(product, variant=None) -> Profile:
    """Facts for one product, or one of its variants when given (variant facts win over product-wide ones)."""
    profile = Profile(product, variant, kind_of(product))
    values, sources = profile.values, profile.sources
    variants = [variant] if variant is not None else [v for v in product.variants.all() if v.is_active]

    def put(key, value, source):
        if value not in (None, [], set(), ""):
            values[key] = value
            sources[key] = source

    if found := _spec(product, "chuck-size", "chuck-capacity", "chuck"):
        put("chuck_mm", (mm_values(found[0]) or [None])[0], f"spec {found[1]}")
    if found := _spec(product, "impact-function", "hammer-function", "impact"):
        put("impact", found[0].strip().lower() in ("yes", "true", "1", "y"), f"spec {found[1]}")
    if found := _spec(product, "sizes", "size", "diameter", "bit-size"):
        if profile.kind == "drill_bit":
            put("bit_mm", mm_values(found[0]), f"spec {found[1]}")
            put("bit_range", mm_range(found[0]), f"spec {found[1]}")
        elif profile.kind == "wall_plug":
            put("plug_mm", (mm_values(found[0]) or [None])[0], f"spec {found[1]}")
        elif profile.kind == "spanner":
            put("spanner_range", mm_range(found[0]), f"spec {found[1]}")
    if profile.kind == "wall_plug" and "plug_mm" not in values:
        match = re.search(rf"{NUMBER}\s*mm", product.name, re.IGNORECASE)
        put("plug_mm", float(match.group(1)) if match else None, "name")
    if found := _spec(product, "material"):
        put("material", found[0].lower(), f"spec {found[1]}")
    if profile.kind == "drill_bit" and "material" in values:
        material = values["material"]
        put(
            "bit_use",
            "masonry" if ("carbide" in material or "tct" in material) else ("metal" if "hss" in material else None),
            sources["material"],
        )
    if profile.kind == "drill_bit" and "bit_use" not in values and "masonry" in product.name.lower():
        put("bit_use", "masonry", "name")
    if profile.kind in ("pipe", "pipe_fitting") and "material" not in values:
        for word in ("cpvc", "upvc", "ppr", "gi", "brass"):
            if re.search(rf"\b{word}\b", product.name.lower()):
                put("material", word, "name")
                break
    if found := _spec(product, "thread", "thread-size", "inlet-size", "outlet-size"):
        put("thread_sizes", nominal_sizes(found[0]), f"spec {found[1]}")
        if match := re.search(r"\bm(\d+)\b", found[0].lower()):
            put("metric_thread", int(match.group(1)), f"spec {found[1]}")
    if found := _spec(product, "current-rating", "rating", "current"):
        put("amps", amps(found[0]), f"spec {found[1]}")
    if found := _spec(product, "base", "cap", "lamp-base"):
        put("base", found[0].upper().split()[0], f"spec {found[1]}")
    if found := _spec(product, "voltage"):
        put("volts", (mm_values(found[0] + " mm") or [None])[0], f"spec {found[1]}")

    # Furniture, door and glass hardware: only what the listing states, in millimetres.
    kind = profile.kind
    if kind in ("hinge", "door_lock") and (
        found := _spec(product, "door-thickness", "shutter-thickness", "panel-thickness")
    ):
        put("door_range", mm_range(found[0]), f"spec {found[1]}")
    if kind == "hinge":
        if found := _spec(product, "cup-diameter", "cup-size", "cup"):
            put("cup_mm", (mm_values(found[0]) or [None])[0], f"spec {found[1]}")
        put("overlay", overlay_of(product.name), "name")
    if kind == "glass_fitting" and (found := _spec(product, "glass-thickness")):
        put("glass_range", mm_range(found[0]), f"spec {found[1]}")
    if kind == "door_lock" and (found := _spec(product, "backset")):
        put("backset_mm", (mm_values(found[0]) or [None])[0], f"spec {found[1]}")
    if kind == "door" and (found := _spec(product, "stile-width", "door-stile")):
        put("stile_mm", (mm_values(found[0]) or [None])[0], f"spec {found[1]}")
    if kind in ("board", "door", "glass") and (
        found := _spec(product, "thickness", "board-thickness", "glass-thickness")
    ):
        put("thickness_mm", (mm_values(found[0]) or [None])[0], f"spec {found[1]}")
    if kind == "drawer_channel" and (found := _spec(product, "channel-length", "slide-length", "length")):
        put("channel_mm", channel_length_mm(found[0]), f"spec {found[1]}")
    if kind == "screw" and (found := _spec(product, "screw-length", "length")):
        put("screw_len_mm", (mm_values(found[0]) or [None])[0], f"spec {found[1]}")
    if kind == "handle":
        if found := _spec(
            product, "centre-to-centre", "center-to-center", "c-c", "cc", "hole-distance", "hole-spacing"
        ):
            put("cc_list", mm_values(found[0]), f"spec {found[1]}")
        if found := _spec(product, "screw-size", "fixing-screw", "screw-thread"):
            match = re.search(r"\bm(\d+)\b", found[0].lower())
            put("handle_thread", int(match.group(1)) if match else None, f"spec {found[1]}")
        if found := _spec(product, "screw-length", "fixing-screw-length"):
            put("handle_screw_len", (mm_values(found[0]) or [None])[0], f"spec {found[1]}")

    # Variant facts (sizes, current, cross-section, screw size). With several variants, each one's set is kept
    # in `per_variant` so a check can say which variants match.
    per_variant = {}
    for v in variants:
        texts = _variant_texts(v)
        joined = " ".join(texts)
        facts = {}
        if sizes := nominal_sizes(joined):
            facts["sizes"] = sizes
        if (current := amps(joined)) and profile.kind in ("mcb", "switch", "socket"):
            facts["amps"] = current
        if match := re.search(rf"{NUMBER}\s*sq\.?\s*mm", joined, re.IGNORECASE):
            facts["cross_section"] = float(match.group(1))
        if match := re.search(r"no\.?\s*(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*mm", joined, re.IGNORECASE):
            gauge = int(match.group(1))
            facts["screw_mm"] = SCREW_GAUGE_MM.get(gauge)
            facts["screw_len_mm"] = float(match.group(2))
        elif profile.kind == "screw" and (match := re.search(rf"{NUMBER}\s*x\s*{NUMBER}\s*mm", joined, re.IGNORECASE)):
            facts["screw_mm"], facts["screw_len_mm"] = float(match.group(1)), float(match.group(2))
        if kind == "screw" and (match := re.search(r"\bm(\d+)\s*x", joined, re.IGNORECASE)):
            facts["metric_thread"] = int(match.group(1))
        if kind in ("board", "door", "glass") and (thickness := mm_values(joined)):
            facts["thickness_mm"] = thickness[0]
        if kind == "drawer_channel":
            facts["channel_mm"] = channel_length_mm(joined)
        if kind == "hinge":
            facts["overlay"] = overlay_of(joined)
        if (
            kind == "handle"
            and values.get("cc_list")
            and (sizes_mm := mm_values(joined))
            and sizes_mm[0] in values["cc_list"]
        ):
            facts["cc_mm"] = sizes_mm[0]  # the variant's size is one of the centre-to-centre sizes the listing states
        per_variant[v.pk] = {k: val for k, val in facts.items() if val is not None}
    values["per_variant"] = per_variant
    if variant is not None:
        for key, val in per_variant.get(variant.pk, {}).items():
            put(key, val, f"variant {variant.name or variant.sku}")
    else:
        merged_sizes = set().union(*[f.get("sizes", set()) for f in per_variant.values()]) if per_variant else set()
        put("sizes", merged_sizes, "variants")
        if profile.kind in ("mcb", "switch", "socket") and "amps" not in values:
            put("amps", sorted({a for f in per_variant.values() for a in f.get("amps", [])}), "variants")
        sections = sorted({f["cross_section"] for f in per_variant.values() if "cross_section" in f})
        if sections:
            put("cross_sections", sections, "variants")
        screws = sorted({f["screw_mm"] for f in per_variant.values() if f.get("screw_mm")})
        if screws:
            put("screw_mms", screws, "variants")
    if "cross_section" in values:
        values["cross_sections"] = [values["cross_section"]]
    if "screw_mm" in values:
        values["screw_mms"] = [values["screw_mm"]]
    for key, plural in PLURALS.items():
        if variant is None and plural not in values:
            listed = sorted({f[key] for f in per_variant.values() if key in f})
            put(plural, listed, "variants")
        if plural not in values and key in values:
            values[plural], sources[plural] = [values[key]], sources[key]
        if variant is not None and key in values:
            values[plural], sources[plural] = [values[key]], sources[key]
    if profile.kind in ("pipe", "pipe_fitting", "tap") and not values.get("sizes") and values.get("thread_sizes"):
        put("sizes", values["thread_sizes"], sources["thread_sizes"])
    return profile
