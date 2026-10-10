# ruff: noqa: E501 — breakdown sentences in three languages read better on one line
"""Quantity formulas (Phase 20): the one place where amounts are worked out.

Used by the quantity calculators, the project builder's templates (Phase 19) and the assistant's paint
estimate (Phase 12). Each function returns an `Estimate`: the amount in natural units plus the steps that
explain it ("Wall area: 2 × (12 + 15) × 10 ft = 540 sq ft"). These are common rules of thumb for a shopping
list (labelled "estimated quantity"), not an engineering calculation; every constant is named here.
"""

import math
from dataclasses import dataclass, field

from .text import t
from .units import fmt

# --- Constants (typical Indian values; change here and every calculator follows) -------------------------

WALL_HEIGHT_FT = 10
DOOR_SQFT = 21  # 3 × 7 ft
WINDOW_SQFT = 12  # 4 × 3 ft
COATS = 2
EMULSION_SQFT_PER_L_PER_COAT = {"interior": 130, "exterior": 100}
PRIMER_SQFT_PER_L = 110
PUTTY_SQFT_PER_KG = {"minor": 50, "damaged": 11}  # patching cracks vs. two full coats

SQFT_PER_SQM = 10.7639
PLASTER_DRY_FACTOR = 1.33  # dry mortar volume per wet volume (voids, bulking of sand)
CEMENT_BAG_CUM = 0.0347  # one 50 kg bag, 1440 kg/m³
CFT_PER_CUM = 35.3147
PLASTER_RATIOS = {"1:4": (1, 4), "1:5": (1, 5), "1:6": (1, 6)}
BRICKWORK_BAGS_PER_SQFT = 0.03  # 9 inch wall in 1:6 mortar
REPAIR_BAGS_PER_SQFT = 0.01

TILE_ADHESIVE_SQFT_PER_BAG = 40  # 20 kg bag at 3–4 mm
GROUT_SQFT_PER_KG = 27  # 2–3 mm joints
SPACERS_PER_TILE = 3

WATERPROOF_SQFT_PER_L = 22  # two coats

WIRE_CUT_SHARE = 0.10  # extra for bends, joints and drops
PIPE_CUT_SHARE = 0.10
SOLVENT_JOINTS_PER_TIN = 30
FASTENER_SPARE_SHARE = 0.20


@dataclass
class Estimate:
    amount: float
    unit: str  # l | kg | m | pcs | sqft | cft
    steps: list[tuple[dict, str]] = field(default_factory=list)  # (label in three languages, value)


def _step(en: str, hi: str, hinglish: str, value: str) -> tuple[dict, str]:
    return t(en, hi, hinglish), value


class FormulaError(ValueError):
    """Answers that can't describe a real job (doors bigger than the walls…). `key` is the answer to fix."""

    def __init__(self, key: str, message: str):
        super().__init__(message)
        self.key = key


# --- Painting --------------------------------------------------------------------------------------------


def wall_area(
    length: float, width: float, height: float = WALL_HEIGHT_FT, doors: int = 1, windows: int = 1
) -> Estimate:
    gross = 2 * (length + width) * height
    openings = doors * DOOR_SQFT + windows * WINDOW_SQFT
    area = gross - openings
    if area <= 0:
        raise FormulaError("doors", "The doors and windows are bigger than the walls. Check the sizes.")
    steps = [
        _step(
            "Wall area",
            "दीवारों का क्षेत्रफल",
            "Deewar ka area",
            f"2 × ({fmt(length)} + {fmt(width)}) × {fmt(height)} ft = {fmt(gross)} sq ft",
        ),
        _step(
            "Doors and windows",
            "दरवाज़े और खिड़कियाँ",
            "Darwaze aur khidkiyan",
            f"{doors} × {DOOR_SQFT} + {windows} × {WINDOW_SQFT} = {fmt(openings)} sq ft",
        ),
        _step("Area to paint", "रंगने का क्षेत्रफल", "Paint karne ka area", f"{fmt(area)} sq ft"),
    ]
    return Estimate(area, "sqft", steps)


def paint_litres(area: float, surface: str = "interior", coats: int = COATS) -> Estimate:
    coverage = EMULSION_SQFT_PER_L_PER_COAT[surface]
    litres = area * coats / coverage
    return Estimate(litres, "l", [
        _step("Coverage", "कवरेज", "Coverage", f"~{coverage} sq ft per litre per coat"),
        _step("Paint needed", "ज़रूरी पेंट", "Zaroori paint", f"{fmt(area)} × {coats} coats ÷ {coverage} = {fmt(litres)} L"),
    ])  # fmt: skip


def primer_litres(area: float) -> Estimate:
    litres = area / PRIMER_SQFT_PER_L
    return Estimate(
        litres,
        "l",
        [
            _step(
                "Primer needed",
                "ज़रूरी प्राइमर",
                "Zaroori primer",
                f"{fmt(area)} ÷ {PRIMER_SQFT_PER_L} sq ft per litre = {fmt(litres)} L",
            )
        ],
    )


def putty_kg(area: float, condition: str) -> Estimate:
    per_kg = PUTTY_SQFT_PER_KG[condition]
    kg = area / per_kg
    return Estimate(
        kg,
        "kg",
        [_step("Putty needed", "ज़रूरी पुट्टी", "Zaroori putty", f"{fmt(area)} ÷ {per_kg} sq ft per kg = {fmt(kg)} kg")],
    )


# --- Plastering and masonry ------------------------------------------------------------------------------


def plaster(
    area_sqft: float, thickness_mm: float = 12, ratio: str = "1:5", wastage_pct: float = 5
) -> tuple[Estimate, Estimate]:
    """Cement (50 kg bags) and sand (cft) for cement plaster, by the dry-volume method."""
    cement_part, sand_part = PLASTER_RATIOS[ratio]
    wet = area_sqft / SQFT_PER_SQM * thickness_mm / 1000
    dry = wet * PLASTER_DRY_FACTOR * (1 + wastage_pct / 100)
    cement_cum = dry * cement_part / (cement_part + sand_part)
    sand_cum = dry * sand_part / (cement_part + sand_part)
    bags = cement_cum / CEMENT_BAG_CUM
    common = [
        _step("Area", "क्षेत्रफल", "Area", f"{fmt(area_sqft)} sq ft = {fmt(area_sqft / SQFT_PER_SQM)} sq m"),
        _step("Mortar (wet)", "गीला मसाला", "Geela masala", f"{fmt(area_sqft / SQFT_PER_SQM)} sq m × {fmt(thickness_mm)} mm = {fmt(wet, 3)} m³"),
        _step("Dry materials", "सूखा सामान", "Sookha saman", f"{fmt(wet, 3)} × {PLASTER_DRY_FACTOR} + {fmt(wastage_pct)} % wastage = {fmt(dry, 3)} m³"),
    ]  # fmt: skip
    cement = Estimate(
        bags,
        "pcs",
        [
            *common,
            _step(
                "Cement",
                "सीमेंट",
                "Cement",
                f"{ratio} → {fmt(cement_cum, 3)} m³ ÷ {CEMENT_BAG_CUM} m³ per bag = {fmt(bags)} bags",
            ),
        ],
    )
    sand = Estimate(
        sand_cum * CFT_PER_CUM,
        "cft",
        [*common, _step("Sand", "रेत", "Ret", f"{ratio} → {fmt(sand_cum, 3)} m³ = {fmt(sand_cum * CFT_PER_CUM)} cft")],
    )
    return cement, sand


def masonry_cement(area_sqft: float, work: str) -> Estimate:
    per_sqft = BRICKWORK_BAGS_PER_SQFT if work == "brickwork" else REPAIR_BAGS_PER_SQFT
    bags = area_sqft * per_sqft
    label = "9 inch brick wall, 1:6 mortar" if work == "brickwork" else "patch repairs"
    return Estimate(
        bags,
        "pcs",
        [
            _step(
                "Cement",
                "सीमेंट",
                "Cement",
                f"{fmt(area_sqft)} sq ft × {fmt(per_sqft * 100)} bags per 100 sq ft ({label}) = {fmt(bags)} bags",
            )
        ],
    )


# --- Tiling and flooring ---------------------------------------------------------------------------------


def floor_area(answers: dict) -> Estimate:
    if answers.get("area"):
        area = float(answers["area"])
        return Estimate(area, "sqft", [_step("Area", "क्षेत्रफल", "Area", f"{fmt(area)} sq ft")])
    length, width = float(answers["length"]), float(answers["width"])
    area = length * width
    return Estimate(
        area, "sqft", [_step("Area", "क्षेत्रफल", "Area", f"{fmt(length)} × {fmt(width)} ft = {fmt(area)} sq ft")]
    )


def tiles(area: float, tile_sqft: float, label: str, wastage_pct: float = 10) -> Estimate:
    exact = area / tile_sqft
    count = math.ceil(round(exact * (1 + wastage_pct / 100), 6))
    return Estimate(count, "pcs", [
        _step("Tile size", "टाइल का साइज़", "Tile size", f"{label} = {fmt(tile_sqft, 2)} sq ft each"),
        _step("Tiles to cover the area", "क्षेत्र भरने के लिए टाइल", "Area ke liye tiles", f"{fmt(area)} ÷ {fmt(tile_sqft, 2)} = {fmt(exact)}"),
        _step("With wastage (cuts, breakage)", "कटाई / टूट-फूट के साथ", "Cutting / toot-phoot ke saath", f"+{fmt(wastage_pct)} % → {count} tiles"),
    ])  # fmt: skip


def tile_adhesive_bags(area: float) -> Estimate:
    bags = area * 1.05 / TILE_ADHESIVE_SQFT_PER_BAG
    return Estimate(
        bags,
        "pcs",
        [
            _step(
                "Adhesive",
                "एडहेसिव",
                "Adhesive",
                f"{fmt(area)} sq ft + 5 % ÷ {TILE_ADHESIVE_SQFT_PER_BAG} sq ft per 20 kg bag = {fmt(bags)} bags",
            )
        ],
    )


def grout_kg(area: float) -> Estimate:
    kg = area / GROUT_SQFT_PER_KG
    return Estimate(
        kg, "kg", [_step("Grout", "ग्राउट", "Grout", f"{fmt(area)} ÷ {GROUT_SQFT_PER_KG} sq ft per kg = {fmt(kg)} kg")]
    )


def spacers(tile_count: int) -> Estimate:
    count = tile_count * SPACERS_PER_TILE
    return Estimate(
        count, "pcs", [_step("Spacers", "स्पेसर", "Spacer", f"{tile_count} tiles × {SPACERS_PER_TILE} = {count}")]
    )


def flooring_sqft(area: float, wastage_pct: float = 10) -> Estimate:
    total = area * (1 + wastage_pct / 100)
    return Estimate(
        total,
        "sqft",
        [
            _step(
                "Flooring with wastage",
                "बर्बादी सहित फ़्लोरिंग",
                "Wastage ke saath flooring",
                f"{fmt(area)} sq ft + {fmt(wastage_pct)} % = {fmt(total)} sq ft",
            )
        ],
    )


# --- Waterproofing ---------------------------------------------------------------------------------------


def waterproofing_litres(area: float) -> Estimate:
    litres = area / WATERPROOF_SQFT_PER_L
    return Estimate(
        litres,
        "l",
        [
            _step(
                "Coating",
                "कोटिंग",
                "Coating",
                f"{fmt(area)} sq ft ÷ {WATERPROOF_SQFT_PER_L} sq ft per litre (2 coats) = {fmt(litres)} L",
            )
        ],
    )


def crack_filler_kg(area: float) -> Estimate:
    kg = max(1.0, area / 100)
    return Estimate(
        kg, "kg", [_step("Crack filler", "क्रैक फ़िलर", "Crack filler", f"about 1 kg per 100 sq ft = {fmt(kg)} kg")]
    )


# --- Wiring and pipes ------------------------------------------------------------------------------------


def wire_metres(metres: float, runs: str = "total") -> Estimate:
    base = metres * 2 if runs == "route" else metres
    total = base * (1 + WIRE_CUT_SHARE)
    steps = []
    if runs == "route":
        steps.append(
            _step("Phase + neutral", "फ़ेज़ + न्यूट्रल", "Phase + neutral", f"{fmt(metres)} m route × 2 = {fmt(base)} m")
        )
    steps.append(
        _step(
            "With bends and joints",
            "मोड़ और जोड़ के साथ",
            "Mod aur jod ke saath",
            f"{fmt(base)} m + {fmt(WIRE_CUT_SHARE * 100)} % = {fmt(total)} m",
        )
    )
    return Estimate(total, "m", steps)


def pipe_metres(metres: float) -> Estimate:
    total = metres * (1 + PIPE_CUT_SHARE)
    return Estimate(
        total,
        "m",
        [
            _step(
                "Pipe with cuts",
                "कटाई सहित पाइप",
                "Cutting ke saath pipe",
                f"{fmt(metres)} m + {fmt(PIPE_CUT_SHARE * 100)} % = {fmt(total)} m",
            )
        ],
    )


def solvent_tins(elbows: int, tees: int, pipe_lengths: int) -> Estimate:
    joints = elbows * 2 + tees * 3 + max(0, pipe_lengths - 1) * 2
    tins = max(1, math.ceil(joints / SOLVENT_JOINTS_PER_TIN))
    return Estimate(
        tins,
        "pcs",
        [
            _step(
                "Solvent cement",
                "सॉल्वेंट सीमेंट",
                "Solvent cement",
                f"{joints} joints ÷ {SOLVENT_JOINTS_PER_TIN} per tin = {tins}",
            )
        ],
    )


# --- Fasteners -------------------------------------------------------------------------------------------


def fasteners(holes: int) -> Estimate:
    count = math.ceil(holes * (1 + FASTENER_SPARE_SHARE))
    return Estimate(
        count, "pcs", [_step("Holes", "छेद", "Chhed", f"{holes} + {fmt(FASTENER_SPARE_SHARE * 100)} % spare = {count}")]
    )


# --- Furniture, kitchens, doors (the shop's hinge / channel / handle / board departments) ------------------
# Rules of thumb a carpenter uses for a shopping list; the plan labels every amount "estimate".

# Hinges per door by door (shutter) height: up to 900 mm → 2, up to 1500 → 3, up to 2100 → 4, taller → 5.
HINGES_BY_HEIGHT_MM = ((900, 2), (1500, 3), (2100, 4))
HINGES_ABOVE = 5
SCREWS_PER_CONCEALED_HINGE = 4  # 2 in the cup, 2 in the mounting plate
SCREWS_PER_BUTT_HINGE = 6  # 3 per leaf
SCREWS_PER_CHANNEL_PAIR = 12  # about 6 per channel: 3 into the cabinet side, 3 into the drawer
CARCASS_SCREWS_PER_CABINET = 16  # 4 per joint, 4 joints (sides to top and bottom)
SHEET_SQM = 2.97  # one 8 × 4 ft sheet (2440 × 1220 mm)
BOARD_WASTAGE_PCT = 15  # cutting, grain direction and offcuts
EDGE_BAND_EXTRA = 0.10
# A standard kitchen base cabinet (width × height × depth, mm) when the customer doesn't give sizes.
KITCHEN_CABINET_MM = (600, 720, 560)
WARDROBE_RAIL_FT = 4  # one hanging rail per 4 ft of width or part of it


def hinges_per_door(height_mm: float) -> int:
    for limit, count in HINGES_BY_HEIGHT_MM:
        if height_mm <= limit:
            return count
    return HINGES_ABOVE


def hinges(doors: int, height_mm: float) -> Estimate:
    each = hinges_per_door(height_mm)
    total = doors * each
    return Estimate(total, "pcs", [
        _step("Hinges per door", "हर दरवाज़े पर कब्ज़े", "Har darwaze par kabze",
              f"{fmt(height_mm)} mm high → {each} (2 up to 900 mm, 3 up to 1500, 4 up to 2100, 5 above)"),
        _step("Hinges", "कब्ज़े", "Kabze", f"{doors} × {each} = {total}"),
    ])  # fmt: skip


def hinge_screws(hinge_count: int, per_hinge: int = SCREWS_PER_CONCEALED_HINGE) -> Estimate:
    total = hinge_count * per_hinge
    return Estimate(
        total,
        "pcs",
        [_step("Hinge screws", "कब्ज़ों के स्क्रू", "Kabze ke screw", f"{hinge_count} hinges × {per_hinge} = {total}")],
    )


def channels(drawers: int) -> Estimate:
    total = drawers * 2
    return Estimate(
        total,
        "pcs",
        [
            _step(
                "Drawer channels",
                "दराज़ चैनल",
                "Daraz channel",
                f"{drawers} drawers × 1 pair (2 channels) = {total} channels",
            )
        ],
    )


def channel_screws(drawers: int) -> Estimate:
    total = drawers * SCREWS_PER_CHANNEL_PAIR
    return Estimate(
        total,
        "pcs",
        [
            _step(
                "Channel screws",
                "चैनल के स्क्रू",
                "Channel ke screw",
                f"{drawers} pairs × {SCREWS_PER_CHANNEL_PAIR} = {total}",
            )
        ],
    )


def handles(shutters: int, drawers: int = 0) -> Estimate:
    total = shutters + drawers
    return Estimate(
        total, "pcs", [_step("Handles", "हैंडल", "Handle", f"{shutters} shutters + {drawers} drawers = {total}")]
    )


def panel_area(parts: list[tuple[str, int, float, float]]) -> Estimate:
    """Board area of (label, count, width mm, height mm) pieces, in square metres."""
    steps, total = [], 0.0
    for label, count, width, height in parts:
        if count <= 0:
            continue
        area = count * width * height / 1_000_000
        total += area
        steps.append(_step(label, label, label, f"{count} × {fmt(width)} × {fmt(height)} mm = {fmt(area, 2)} sq m"))
    steps.append(_step("Board area", "बोर्ड का क्षेत्रफल", "Board ka area", f"{fmt(total, 2)} sq m"))
    return Estimate(total, "sqm", steps)


def board_sheets(area_sqm: float, wastage_pct: float = BOARD_WASTAGE_PCT) -> Estimate:
    with_waste = area_sqm * (1 + wastage_pct / 100)
    sheets = max(1, math.ceil(round(with_waste / SHEET_SQM, 6)))
    return Estimate(sheets, "pcs", [
        _step("With wastage", "बर्बादी सहित", "Wastage ke saath", f"{fmt(area_sqm, 2)} sq m + {fmt(wastage_pct)} % = {fmt(with_waste, 2)} sq m"),
        _step("Sheets (8 × 4 ft)", "शीट (8 × 4 फ़ुट)", "Sheet (8 × 4 ft)", f"{fmt(with_waste, 2)} ÷ {SHEET_SQM} sq m per sheet = {sheets}"),
    ])  # fmt: skip


def edge_band(parts: list[tuple[str, int, float, float]], *, all_sides: bool = True) -> Estimate:
    """Edge band (metres) for (label, count, width mm, height mm) pieces: all four edges, or the front edge only
    (`all_sides=False`: carcass panels, `width` is the visible edge)."""
    metres = 0.0
    for _label, count, width, height in parts:
        metres += count * (2 * (width + height) if all_sides else width) / 1000
    total = metres * (1 + EDGE_BAND_EXTRA)
    return Estimate(
        total,
        "m",
        [
            _step(
                "Edge band",
                "एज बैंड",
                "Edge band",
                f"{fmt(metres)} m of edges + {fmt(EDGE_BAND_EXTRA * 100)} % = {fmt(total)} m",
            )
        ],
    )


def carcass_screws(cabinets: int) -> Estimate:
    total = cabinets * CARCASS_SCREWS_PER_CABINET
    return Estimate(
        total,
        "pcs",
        [
            _step(
                "Assembly screws",
                "जोड़ने के स्क्रू",
                "Jodne ke screw",
                f"{cabinets} cabinets × {CARCASS_SCREWS_PER_CABINET} = {total}",
            )
        ],
    )


def wardrobe_rails(width_mm: float) -> Estimate:
    width_ft = width_mm / 304.8
    rails = max(1, math.ceil(round(width_ft / WARDROBE_RAIL_FT, 6)))
    return Estimate(
        rails,
        "pcs",
        [
            _step(
                "Hanging rails",
                "हैंगिंग रॉड",
                "Hanging rod",
                f"{fmt(width_ft)} ft ÷ {WARDROBE_RAIL_FT} ft per rail = {rails}",
            )
        ],
    )


GLASS_CLAMPS_PER_PANEL = 4  # a fixed glass panel: 2 clamps at the floor, 2 at the wall or ceiling
GLASS_PIECES_PER_SEALANT_TUBE = 2  # one 280 ml tube seals the edges of about two door-size panels


def glass_clamps(panels: int) -> Estimate:
    total = panels * GLASS_CLAMPS_PER_PANEL
    return Estimate(
        total,
        "pcs",
        [
            _step(
                "Glass clamps", "ग्लास क्लैंप", "Glass clamp", f"{panels} fixed panels × {GLASS_CLAMPS_PER_PANEL} = {total}"
            )
        ],
    )


def sealant_tubes(pieces: int) -> Estimate:
    tubes = max(1, math.ceil(pieces / GLASS_PIECES_PER_SEALANT_TUBE))
    return Estimate(
        tubes,
        "pcs",
        [
            _step(
                "Sealant",
                "सीलेंट",
                "Sealant",
                f"{pieces} glass pieces ÷ {GLASS_PIECES_PER_SEALANT_TUBE} per tube = {tubes}",
            )
        ],
    )
