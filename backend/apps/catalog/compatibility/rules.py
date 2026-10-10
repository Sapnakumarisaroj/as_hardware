# ruff: noqa: E501 — explanations read better on one line
"""Compatibility rules (Phase 21): one function per pair of product kinds, deterministic, from listing facts only.

Each rule gets two profiles (in the order it was registered for) and returns a `Finding`:

- COMPATIBLE: every fact the rule needs is in both listings and they agree;
- POSSIBLY_COMPATIBLE: they agree only for some variants, or something that matters isn't stated on one side;
- NOT_COMPATIBLE: the listings state facts that rule it out;
- INSUFFICIENT_INFORMATION: a fact the rule can't do without is missing.

Adding a rule = one `@rule("kind_a", "kind_b")` function. Constants are named here, with where they come from.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from .profiles import Profile

COMPATIBLE = "COMPATIBLE"
POSSIBLY = "POSSIBLY_COMPATIBLE"
NOT = "NOT_COMPATIBLE"
UNKNOWN = "INSUFFICIENT_INFORMATION"
ORDER = {COMPATIBLE: 0, POSSIBLY: 1, UNKNOWN: 2, NOT: 3}

# Wire cross-section (sq mm, copper, in conduit) → highest MCB rating it is protected by (amps). Typical Indian
# house-wiring practice; the electrician confirms it for the actual run.
WIRE_MAX_MCB = {1.0: 6, 1.5: 10, 2.5: 16, 4.0: 25, 6.0: 32, 10.0: 40}
# Hex bolt metric thread → spanner across-flats size (ISO 4032/4014).
BOLT_SPANNER_MM = {5: 8, 6: 10, 8: 13, 10: 17, 12: 19, 16: 24, 20: 30}
# Screw shank diameter that suits a plastic wall plug: about 60–85 % of the plug's diameter (manufacturers' tables:
# 6 mm plug → 3.5–5 mm screws, 8 mm → 4.5–6 mm).
PLUG_SCREW_SHARE = (0.58, 0.85)


@dataclass
class Check:
    name: str
    status: str  # pass | fail | missing | warn
    detail: str


@dataclass
class Finding:
    verdict: str
    reason: str
    checks: list[Check] = field(default_factory=list)
    matching_variants: list[dict] = field(default_factory=list)  # [{a, b, label}] variant pairs that work


Rule = Callable[[Profile, Profile], Finding]
RULES: dict[tuple[str, str], Rule] = {}


def rule(kind_a: str, kind_b: str):
    def register(fn: Rule) -> Rule:
        RULES[(kind_a, kind_b)] = fn
        return fn

    return register


def find_rule(kind_a: str | None, kind_b: str | None) -> tuple[Rule | None, bool]:
    """(rule, swapped): swapped when the rule was registered for (b, a)."""
    if (kind_a, kind_b) in RULES:
        return RULES[(kind_a, kind_b)], False
    if (kind_b, kind_a) in RULES:
        return RULES[(kind_b, kind_a)], True
    return None, False


def related_kinds(kind: str | None) -> list[str]:
    return sorted({b for a, b in RULES if a == kind} | {a for a, b in RULES if b == kind})


def _mm(value: float) -> str:
    return f"{value:g} mm"


def _missing(profile: Profile, what: str) -> Check:
    return Check(what, "missing", f"{profile.product.name}: {what} isn't in the listing")


def _worst(checks: list[Check]) -> str:
    if any(c.status == "fail" for c in checks):
        return NOT
    if any(c.status == "missing" for c in checks):
        return UNKNOWN
    if any(c.status == "warn" for c in checks):
        return POSSIBLY
    return COMPATIBLE


# --- Drills, bits, plugs, screws ----------------------------------------------------------------------------


@rule("drill", "drill_bit")
def drill_and_bit(drill: Profile, bit: Profile) -> Finding:
    checks = []
    chuck = drill.values.get("chuck_mm")
    sizes = bit.values.get("bit_mm") or []
    if chuck is None:
        checks.append(_missing(drill, "chuck size"))
    if not sizes:
        checks.append(_missing(bit, "bit sizes"))
    if chuck is not None and sizes:
        fit = [s for s in sizes if s <= chuck]
        if len(fit) == len(sizes):
            checks.append(
                Check("chuck", "pass", f"The {_mm(chuck)} chuck takes every bit in the set (up to {_mm(max(sizes))}).")
            )
        elif fit:
            checks.append(
                Check(
                    "chuck",
                    "warn",
                    f"The {_mm(chuck)} chuck takes the bits up to {_mm(max(fit))}; the {', '.join(_mm(s) for s in sizes if s > chuck)} won't fit.",
                )
            )
        else:
            checks.append(
                Check("chuck", "fail", f"The smallest bit ({_mm(min(sizes))}) is bigger than the {_mm(chuck)} chuck.")
            )
    if bit.values.get("bit_use") == "masonry":
        impact = drill.values.get("impact")
        if impact is True:
            checks.append(
                Check("hammer action", "pass", "Masonry bits need hammer (impact) action, and this drill has it.")
            )
        elif impact is False:
            checks.append(
                Check(
                    "hammer action",
                    "warn",
                    "Masonry bits need hammer action for concrete and brick; this drill has none.",
                )
            )
        else:
            checks.append(
                Check(
                    "hammer action",
                    "warn",
                    "Masonry bits need hammer action; the drill's listing doesn't say it has it.",
                )
            )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks)


@rule("drill_bit", "wall_plug")
def bit_and_plug(bit: Profile, plug: Profile) -> Finding:
    checks = []
    diameter = plug.values.get("plug_mm")
    sizes = bit.values.get("bit_mm") or []
    span = bit.values.get("bit_range")
    if diameter is None:
        checks.append(_missing(plug, "plug diameter"))
    if not sizes:
        checks.append(_missing(bit, "bit sizes"))
    if diameter is not None and sizes:
        listed = len(sizes) > 2 or (span and span[0] == span[1])
        if diameter in sizes:
            checks.append(
                Check("hole size", "pass", f"The set has a {_mm(diameter)} bit for the {_mm(diameter)} plug.")
            )
        elif not listed and span and span[0] <= diameter <= span[1]:
            checks.append(
                Check(
                    "hole size",
                    "warn",
                    f"The set covers {_mm(span[0])}–{_mm(span[1])}; check it includes {_mm(diameter)}.",
                )
            )
        else:
            checks.append(
                Check("hole size", "fail", f"No {_mm(diameter)} bit in the set ({', '.join(_mm(s) for s in sizes)}).")
            )
    use = bit.values.get("bit_use")
    if use == "metal":
        checks.append(
            Check(
                "wall",
                "warn",
                "These are metal (HSS) bits; for brick or concrete walls use carbide-tipped masonry bits.",
            )
        )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks)


@rule("wall_plug", "screw")
def plug_and_screw(plug: Profile, screw: Profile) -> Finding:
    checks = []
    diameter = plug.values.get("plug_mm")
    screws = screw.values.get("screw_mms") or []
    if diameter is None:
        checks.append(_missing(plug, "plug diameter"))
    if not screws:
        checks.append(_missing(screw, "screw diameter"))
    matching = []
    if diameter is not None and screws:
        low, high = diameter * PLUG_SCREW_SHARE[0], diameter * PLUG_SCREW_SHARE[1]
        good = [s for s in screws if low <= s <= high]
        per = screw.values.get("per_variant", {})
        for variant_id, facts in per.items():
            if facts.get("screw_mm") and low <= facts["screw_mm"] <= high:
                matching.append({"a": None, "b": variant_id, "label": f"{facts['screw_mm']:g} mm screws"})
        if len(good) == len(screws):
            checks.append(
                Check(
                    "screw size",
                    "pass",
                    f"{', '.join(_mm(s) for s in screws)} screws suit a {_mm(diameter)} plug ({_mm(round(low, 1))}–{_mm(round(high, 1))}).",
                )
            )
        elif good:
            checks.append(
                Check(
                    "screw size",
                    "warn",
                    f"Only the {', '.join(_mm(s) for s in good)} screws suit a {_mm(diameter)} plug.",
                )
            )
        else:
            checks.append(
                Check(
                    "screw size",
                    "fail",
                    f"{', '.join(_mm(s) for s in screws)} screws don't suit a {_mm(diameter)} plug (needs {_mm(round(low, 1))}–{_mm(round(high, 1))}).",
                )
            )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks, matching)


@rule("bolt", "spanner")
def bolt_and_spanner(bolt: Profile, spanner: Profile) -> Finding:
    checks = []
    thread = bolt.values.get("metric_thread")
    span = spanner.values.get("spanner_range")
    if thread is None:
        checks.append(_missing(bolt, "thread size"))
    if span is None:
        checks.append(_missing(spanner, "spanner sizes"))
    if thread is not None and span is not None:
        needed = BOLT_SPANNER_MM.get(thread)
        if needed is None:
            checks.append(Check("spanner size", "missing", f"No standard spanner size known for M{thread}."))
        elif span[0] <= needed <= span[1]:
            checks.append(
                Check(
                    "spanner size",
                    "warn",
                    f"An M{thread} bolt needs a {_mm(needed)} spanner; the set covers {_mm(span[0])}–{_mm(span[1])} (check it has {_mm(needed)}).",
                )
            )
        else:
            checks.append(
                Check(
                    "spanner size",
                    "fail",
                    f"An M{thread} bolt needs a {_mm(needed)} spanner; the set covers {_mm(span[0])}–{_mm(span[1])}.",
                )
            )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks)


# --- Plumbing ----------------------------------------------------------------------------------------------


def _sizes_check(a: Profile, b: Profile, what: str) -> tuple[Check | None, list[dict]]:
    """Nominal sizes ("1/2", "3/4") of two products; with several variants, the pairs that match."""
    sizes_a, sizes_b = a.values.get("sizes") or set(), b.values.get("sizes") or set()
    if not sizes_a:
        return _missing(a, f"{what} size"), []
    if not sizes_b:
        return _missing(b, f"{what} size"), []
    common = sizes_a & sizes_b
    pairs = []
    per_a, per_b = a.values.get("per_variant", {}), b.values.get("per_variant", {})
    for va, fa in per_a.items() if a.variant is None else [(a.variant.pk, {"sizes": sizes_a})]:
        for vb, fb in per_b.items() if b.variant is None else [(b.variant.pk, {"sizes": sizes_b})]:
            for size in sorted(fa.get("sizes", set()) & fb.get("sizes", set())):
                pairs.append({"a": va, "b": vb, "label": f'{size}"'})
    if not common:
        return Check(
            f"{what} size",
            "fail",
            f"Sizes don't match: {', '.join(sorted(sizes_a))} vs {', '.join(sorted(sizes_b))} inch.",
        ), []
    if sizes_a == sizes_b == common and len(common) == 1:
        return Check(f"{what} size", "pass", f"Both are {next(iter(common))} inch."), pairs
    return Check(
        f"{what} size", "warn", f"They match only in {', '.join(sorted(common))} inch: choose that size for both."
    ), pairs


def _material_check(a: Profile, b: Profile) -> Check:
    ma, mb = a.values.get("material"), b.values.get("material")
    if not ma:
        return _missing(a, "material")
    if not mb:
        return _missing(b, "material")
    family = {"cpvc": "cpvc", "upvc": "upvc", "pvc": "upvc", "ppr": "ppr", "gi": "gi", "brass": "metal", "ss": "metal"}
    fa = next((v for k, v in family.items() if k in ma.split() or ma.startswith(k)), ma)
    fb = next((v for k, v in family.items() if k in mb.split() or mb.startswith(k)), mb)
    if fa == fb:
        return Check("material", "pass", f"Both are {ma.upper()}.")
    if "metal" in (fa, fb):
        return Check(
            "material",
            "warn",
            f"{ma.upper()} and {mb.upper()} join through a threaded adapter (FTA/MTA), not directly.",
        )
    return Check("material", "fail", f"{ma.upper()} and {mb.upper()} can't be solvent-joined to each other.")


@rule("pipe", "pipe_fitting")
def pipe_and_fitting(pipe: Profile, fitting: Profile) -> Finding:
    checks = [_material_check(pipe, fitting)]
    size_check, pairs = _sizes_check(pipe, fitting, "pipe")
    checks.append(size_check)
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks, pairs)


@rule("pipe", "pipe")
def pipe_and_pipe(a: Profile, b: Profile) -> Finding:
    return pipe_and_fitting(a, b)


@rule("pipe_fitting", "pipe_fitting")
def fitting_and_fitting(a: Profile, b: Profile) -> Finding:
    return pipe_and_fitting(a, b)


@rule("tap", "pipe_fitting")
def tap_and_fitting(tap: Profile, fitting: Profile) -> Finding:
    size_check, pairs = _sizes_check(tap, fitting, "thread")
    checks = [size_check]
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks, pairs)


# --- Electrical --------------------------------------------------------------------------------------------


@rule("mcb", "wire")
def mcb_and_wire(mcb: Profile, wire: Profile) -> Finding:
    checks, pairs = [], []
    ratings = mcb.values.get("amps") or []
    sections = wire.values.get("cross_sections") or []
    if not ratings:
        checks.append(_missing(mcb, "current rating"))
    if not sections:
        checks.append(_missing(wire, "cross-section"))
    if ratings and sections:
        ok = [(r, s) for r in ratings for s in sections if WIRE_MAX_MCB.get(s, 0) >= r]
        per_m, per_w = mcb.values.get("per_variant", {}), wire.values.get("per_variant", {})
        for vm, fm in per_m.items():
            for vw, fw in per_w.items():
                if (
                    fm.get("amps")
                    and fw.get("cross_section")
                    and WIRE_MAX_MCB.get(fw["cross_section"], 0) >= max(fm["amps"])
                ):
                    pairs.append(
                        {"a": vm, "b": vw, "label": f"{max(fm['amps']):g} A with {fw['cross_section']:g} sq mm"}
                    )
        if len(ok) == len(ratings) * len(sections):
            checks.append(Check("wire size", "pass", "The wire is thick enough for the MCB rating."))
        elif ok:
            checks.append(
                Check(
                    "wire size",
                    "warn",
                    "Only some combinations work: "
                    + "; ".join(f"{r:g} A MCB with {s:g} sq mm or thicker" for r, s in ok[:3])
                    + ".",
                )
            )
        else:
            worst = max(ratings)
            needed = min((s for s, a in WIRE_MAX_MCB.items() if a >= worst), default=None)
            checks.append(
                Check(
                    "wire size",
                    "fail",
                    f"A {worst:g} A MCB needs {needed:g} sq mm wire or thicker; this is {', '.join(f'{s:g}' for s in sections)} sq mm."
                    if needed
                    else f"No wire size listed for a {worst:g} A MCB.",
                )
            )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks, pairs)


def _rating_rule(device: Profile, load: Profile, device_name: str, load_name: str) -> Finding:
    checks = []
    device_amps, load_amps = device.values.get("amps") or [], load.values.get("amps") or []
    if not device_amps:
        checks.append(_missing(device, "current rating"))
    if not load_amps:
        checks.append(_missing(load, "current rating"))
    if device_amps and load_amps:
        if max(device_amps) >= max(load_amps):
            checks.append(
                Check(
                    "current",
                    "pass",
                    f"The {max(device_amps):g} A {device_name} handles the {max(load_amps):g} A {load_name}.",
                )
            )
        else:
            checks.append(
                Check(
                    "current",
                    "fail",
                    f"A {max(device_amps):g} A {device_name} can't control a {max(load_amps):g} A {load_name}; use a {max(load_amps):g} A {device_name}.",
                )
            )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks)


@rule("switch", "socket")
def switch_and_socket(switch: Profile, socket: Profile) -> Finding:
    return _rating_rule(switch, socket, "switch", "socket")


@rule("switch", "wire")
def switch_and_wire(switch: Profile, wire: Profile) -> Finding:
    checks = []
    device_amps, sections = switch.values.get("amps") or [], wire.values.get("cross_sections") or []
    if not device_amps:
        checks.append(_missing(switch, "current rating"))
    if not sections:
        checks.append(_missing(wire, "cross-section"))
    if device_amps and sections:
        thin = [s for s in sections if WIRE_MAX_MCB.get(s, 0) < max(device_amps)]
        if not thin:
            checks.append(
                Check("wire size", "pass", f"The wire carries the {max(device_amps):g} A the switch is rated for.")
            )
        elif len(thin) < len(sections):
            checks.append(
                Check(
                    "wire size",
                    "warn",
                    f"Use {', '.join(f'{s:g}' for s in sections if s not in thin)} sq mm for a {max(device_amps):g} A circuit.",
                )
            )
        else:
            checks.append(
                Check(
                    "wire size",
                    "fail",
                    f"{', '.join(f'{s:g}' for s in thin)} sq mm is too thin for a {max(device_amps):g} A circuit.",
                )
            )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks)


@rule("socket", "wire")
def socket_and_wire(socket: Profile, wire: Profile) -> Finding:
    return switch_and_wire(socket, wire)


@rule("bulb", "holder")
def bulb_and_holder(bulb: Profile, holder: Profile) -> Finding:
    checks = []
    a, b = bulb.values.get("base"), holder.values.get("base")
    if not a:
        checks.append(_missing(bulb, "base type"))
    if not b:
        checks.append(_missing(holder, "base type"))
    if a and b:
        checks.append(Check("base", "pass" if a == b else "fail", f"Bulb base {a}, holder {b}."))
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks)


# --- Furniture, door and glass hardware ----------------------------------------------------------------------
# Every verdict below compares numbers the two listings state (ProductSpecification rows, variant names); a number
# that isn't listed makes the check "missing" (INSUFFICIENT_INFORMATION: "check with us"), never a guess.

# A hinge's / lock's door-thickness range and a glass fitting's glass-thickness range are inclusive.
# A screw fixed into the face of a board must be shorter than the board, or its tip comes out the other side
# ("blind" fixing: hinge plates, channels, handles' wood screws).
# A handle's machine screw must reach through the shutter and grip the handle's thread: at least this much longer
# than the shutter (rule of thumb, about 1.5 × an M4 thread).
HANDLE_THREAD_GRIP_MM = 6
# A telescopic channel needs this much free depth behind it inside the cabinet (rule of thumb).
CHANNEL_REAR_CLEARANCE_MM = 10
# A mortise lock's case sits behind its backset; the door stile must be at least this much wider than the backset.
MORTISE_CASE_MARGIN_MM = 15


def _range_text(span: tuple[float, float]) -> str:
    return _mm(span[0]) if span[0] == span[1] else f"{span[0]:g}–{_mm(span[1])}"


def _fits(value: float, span: tuple[float, float]) -> bool:
    return span[0] <= value <= span[1]


def _thickness_check(
    holder: Profile, panel: Profile, range_key: str, what: str, panel_word: str
) -> tuple[Check, list[dict]]:
    """`holder`'s listed thickness range (hinge, lock, glass fitting) against `panel`'s thicknesses (board, door,
    glass), variant by variant. Matching pairs are {a: None (any holder variant), b: panel variant}."""
    span = holder.values.get(range_key)
    thicknesses = panel.values.get("thicknesses") or []
    if span is None:
        return _missing(holder, f"{what} it takes"), []
    if not thicknesses:
        return _missing(panel, f"{panel_word} thickness"), []
    good = [t for t in thicknesses if _fits(t, span)]
    pairs = []
    per = panel.values.get("per_variant", {}) if panel.variant is None else {}
    for variant_id, facts in per.items():
        if facts.get("thickness_mm") is not None and _fits(facts["thickness_mm"], span):
            pairs.append({"a": None, "b": variant_id, "label": f"{_mm(facts['thickness_mm'])} {panel_word}"})
    takes = f"{holder.product.name} takes {_range_text(span)} {what}"
    if len(good) == len(thicknesses):
        return Check(
            "thickness", "pass", f"{takes}; this {panel_word} is {', '.join(_mm(t) for t in thicknesses)}."
        ), pairs
    if good:
        return Check("thickness", "warn", f"{takes}: choose the {', '.join(_mm(t) for t in good)} {panel_word}."), pairs
    return Check("thickness", "fail", f"{takes}; this {panel_word} is {', '.join(_mm(t) for t in thicknesses)}."), pairs


@rule("hinge", "board")
def hinge_and_board(hinge: Profile, board: Profile) -> Finding:
    """A hinge on a shutter cut from this board: the board's thickness within the hinge's door-thickness range."""
    check, pairs = _thickness_check(hinge, board, "door_range", "door thickness", "board")
    checks = [check]
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks, pairs)


@rule("hinge", "door")
def hinge_and_door(hinge: Profile, door: Profile) -> Finding:
    check, pairs = _thickness_check(hinge, door, "door_range", "door thickness", "door")
    checks = [check]
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks, pairs)


@rule("door_lock", "door")
def lock_and_door(lock: Profile, door: Profile) -> Finding:
    check, pairs = _thickness_check(lock, door, "door_range", "door thickness", "door")
    checks = [check]
    backset, stile = lock.values.get("backset_mm"), door.values.get("stile_mm")
    if backset is not None and stile is not None:
        need = backset + MORTISE_CASE_MARGIN_MM
        status = "pass" if stile >= need else "fail"
        checks.append(
            Check(
                "backset",
                status,
                f"A {_mm(backset)} backset needs a stile of about {_mm(need)}; this door's stile is {_mm(stile)}.",
            )
        )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks, pairs)


@rule("glass_fitting", "glass")
def glass_fitting_and_glass(fitting: Profile, glass: Profile) -> Finding:
    check, pairs = _thickness_check(fitting, glass, "glass_range", "glass thickness", "glass")
    checks = [check]
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks, pairs)


@rule("glass_fitting", "glass_fitting")
def glass_fittings_together(a: Profile, b: Profile) -> Finding:
    """Two fittings on the same glass: the glass thickness both take."""
    span_a, span_b = a.values.get("glass_range"), b.values.get("glass_range")
    checks = []
    if span_a is None:
        checks.append(_missing(a, "glass thickness it takes"))
    if span_b is None:
        checks.append(_missing(b, "glass thickness it takes"))
    if span_a is not None and span_b is not None:
        low, high = max(span_a[0], span_b[0]), min(span_a[1], span_b[1])
        if low > high:
            checks.append(
                Check(
                    "glass thickness",
                    "fail",
                    f"{a.product.name} takes {_range_text(span_a)} glass and {b.product.name} {_range_text(span_b)}: no glass suits both.",
                )
            )
        elif span_a == span_b:
            checks.append(Check("glass thickness", "pass", f"Both take {_range_text(span_a)} glass."))
        else:
            checks.append(
                Check(
                    "glass thickness",
                    "warn",
                    f"Both fit only {_range_text((low, high))} glass ({a.product.name}: {_range_text(span_a)}, {b.product.name}: {_range_text(span_b)}).",
                )
            )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks)


@rule("screw", "board")
def screw_and_board(screw: Profile, board: Profile) -> Finding:
    """Screws fixed into the face of a board (hinge plates, channels): shorter than the board."""
    lengths = screw.values.get("screw_lens") or []
    thicknesses = board.values.get("thicknesses") or []
    checks, pairs = [], []
    if not lengths:
        checks.append(_missing(screw, "screw length"))
    if not thicknesses:
        checks.append(_missing(board, "board thickness"))
    if lengths and thicknesses:
        fits = {n: [t for t in thicknesses if n < t] for n in lengths}  # screw length → boards it stays inside
        for variant_id, facts in (screw.values.get("per_variant", {}) if screw.variant is None else {}).items():
            if fits.get(facts.get("screw_len_mm")):
                pairs.append({"a": variant_id, "b": None, "label": f"{_mm(facts['screw_len_mm'])} screws"})
        board_text = ", ".join(_mm(t) for t in thicknesses)
        if all(len(boards) == len(thicknesses) for boards in fits.values()):
            checks.append(
                Check(
                    "screw length",
                    "pass",
                    f"{', '.join(_mm(n) for n in lengths)} screws stay inside a {board_text} board when fixed into its face.",
                )
            )
        elif any(fits.values()):
            inside = "; ".join(
                f"{_mm(n)} screws stay inside the {', '.join(_mm(t) for t in boards)} board"
                for n, boards in fits.items()
                if boards
            )
            checks.append(
                Check(
                    "screw length", "warn", f"For fixing into the face: {inside}; in a thinner board they come through."
                )
            )
        else:
            checks.append(
                Check(
                    "screw length",
                    "warn",
                    f"{', '.join(_mm(n) for n in lengths)} screws are longer than a {board_text} board: right for joining boards edge to face, too long for fixing hardware to its face.",
                )
            )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks, pairs)


@rule("hinge", "hinge")
def hinge_replacement(old: Profile, new: Profile) -> Finding:
    """One hinge in place of another: same cup size (the hole in the shutter) and the same overlay."""
    checks = []
    cup_a, cup_b = old.values.get("cup_mm"), new.values.get("cup_mm")
    if cup_a is None:
        checks.append(_missing(old, "cup size"))
    if cup_b is None:
        checks.append(_missing(new, "cup size"))
    if cup_a is not None and cup_b is not None:
        checks.append(
            Check(
                "cup",
                "pass" if cup_a == cup_b else "fail",
                f"Cup sizes: {_mm(cup_a)} and {_mm(cup_b)}."
                + ("" if cup_a == cup_b else " The shutter's hole won't take it."),
            )
        )
    over_a, over_b = set(old.values.get("overlays") or []), set(new.values.get("overlays") or [])
    if over_a and over_b:
        common = over_a & over_b
        if not common:
            checks.append(
                Check("overlay", "fail", f"Overlay: {', '.join(sorted(over_a))} vs {', '.join(sorted(over_b))}.")
            )
        elif over_a != over_b or len(common) > 1:
            checks.append(Check("overlay", "warn", f"Choose the same overlay for both: {', '.join(sorted(common))}."))
        else:
            checks.append(Check("overlay", "pass", f"Both are {next(iter(common))} overlay."))
    elif cup_a is not None and cup_b is not None:
        checks.append(
            Check("overlay", "warn", "Check that the overlay (full, half or inset) is the same as the old hinge.")
        )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks)


@rule("drawer_channel", "drawer_channel")
def channel_replacement(old: Profile, new: Profile) -> Finding:
    """One pair of channels in place of another: the same length."""
    a, b = old.values.get("channel_lengths") or [], new.values.get("channel_lengths") or []
    checks, pairs = [], []
    if not a:
        checks.append(_missing(old, "channel length"))
    if not b:
        checks.append(_missing(new, "channel length"))
    if a and b:
        common = sorted(set(a) & set(b))
        for variant_id, facts in (new.values.get("per_variant", {}) if new.variant is None else {}).items():
            if facts.get("channel_mm") in common:
                pairs.append({"a": None, "b": variant_id, "label": f"{_mm(facts['channel_mm'])} channels"})
        if not common:
            checks.append(
                Check(
                    "length",
                    "fail",
                    f"Lengths don't match: {', '.join(_mm(n) for n in a)} vs {', '.join(_mm(n) for n in b)}.",
                )
            )
        elif len(a) == len(b) == len(common) == 1:
            checks.append(Check("length", "pass", f"Both are {_mm(common[0])} long."))
        else:
            checks.append(
                Check("length", "warn", f"Choose the same length for both: {', '.join(_mm(n) for n in common)}.")
            )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks, pairs)


@rule("handle", "handle")
def handle_replacement(old: Profile, new: Profile) -> Finding:
    """A handle in place of another: the same centre-to-centre distance uses the existing holes."""
    a, b = (
        old.values.get("ccs") or old.values.get("cc_list") or [],
        new.values.get("ccs") or new.values.get("cc_list") or [],
    )
    checks, pairs = [], []
    if not a:
        checks.append(_missing(old, "centre-to-centre distance"))
    if not b:
        checks.append(_missing(new, "centre-to-centre distance"))
    if a and b:
        common = sorted(set(a) & set(b))
        for variant_id, facts in (new.values.get("per_variant", {}) if new.variant is None else {}).items():
            if facts.get("cc_mm") in common:
                pairs.append({"a": None, "b": variant_id, "label": f"{_mm(facts['cc_mm'])} centre to centre"})
        if not common:
            checks.append(
                Check(
                    "holes",
                    "fail",
                    f"Centre-to-centre {', '.join(_mm(n) for n in a)} vs {', '.join(_mm(n) for n in b)}: new holes are needed.",
                )
            )
        elif len(a) == len(b) == len(common) == 1:
            checks.append(Check("holes", "pass", f"Both are {_mm(common[0])} centre to centre: the old holes fit."))
        else:
            checks.append(
                Check(
                    "holes",
                    "warn",
                    f"Choose {', '.join(_mm(n) for n in common)} centre to centre to use the old holes.",
                )
            )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks, pairs)


@rule("handle", "screw")
def handle_and_screw(handle: Profile, screw: Profile) -> Finding:
    """A handle's fixing thread (e.g. M4) and the screws' thread."""
    thread = handle.values.get("handle_thread")
    threads = screw.values.get("metric_threads") or []
    checks = []
    if thread is None:
        checks.append(_missing(handle, "fixing screw size"))
    elif not threads:
        if screw.values.get("screw_mms"):  # gauge wood screws: no metric thread
            checks.append(Check("thread", "fail", f"The handle takes M{thread} machine screws; these are wood screws."))
        else:
            checks.append(_missing(screw, "thread size"))
    elif thread in threads:
        checks.append(
            Check(
                "thread",
                "pass" if threads == [thread] else "warn",
                f"The handle takes M{thread}; choose the M{thread} screws."
                if threads != [thread]
                else f"Both are M{thread}.",
            )
        )
    else:
        checks.append(
            Check(
                "thread", "fail", f"The handle takes M{thread}; these screws are {', '.join(f'M{n}' for n in threads)}."
            )
        )
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks)


@rule("handle", "board")
def handle_and_board(handle: Profile, board: Profile) -> Finding:
    """The handle's own screws must go through the shutter and still grip the handle."""
    length = handle.values.get("handle_screw_len")
    thicknesses = board.values.get("thicknesses") or []
    checks, pairs = [], []
    if length is None:
        checks.append(_missing(handle, "length of its screws"))
    if not thicknesses:
        checks.append(_missing(board, "board thickness"))
    if length is not None and thicknesses:
        limit = length - HANDLE_THREAD_GRIP_MM
        good = [t for t in thicknesses if t <= limit]
        for variant_id, facts in (board.values.get("per_variant", {}) if board.variant is None else {}).items():
            if facts.get("thickness_mm") is not None and facts["thickness_mm"] <= limit:
                pairs.append({"a": None, "b": variant_id, "label": f"{_mm(facts['thickness_mm'])} board"})
        text = f"The handle's {_mm(length)} screws suit shutters up to {_mm(limit)}"
        status = "pass" if len(good) == len(thicknesses) else ("warn" if good else "fail")
        checks.append(Check("screw length", status, f"{text}; this board is {', '.join(_mm(t) for t in thicknesses)}."))
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks, pairs)


# --- Against the customer's own measurements --------------------------------------------------------------
# "Will this hinge fit 18 mm ply?", a kitchen kit's 18 mm shutters, a 500 mm deep cabinet, 10 mm glass. The
# measurement is the customer's; the other side is the listing. Keys: board_mm, door_mm, glass_mm, depth_mm.
MEASURES = ("board_mm", "door_mm", "glass_mm", "depth_mm")
Measure = Callable[[Profile, dict], Finding | None]
MEASURE_RULES: dict[str, Measure] = {}


def measure_rule(kind: str):
    def register(fn: Measure) -> Measure:
        MEASURE_RULES[kind] = fn
        return fn

    return register


def _measure_finding(checks: list[Check]) -> Finding:
    verdict = _worst(checks)
    return Finding(verdict, _reason(verdict, checks), checks)


def _range_measure(profile: Profile, span_key: str, value: float, what: str, measured: str) -> Finding:
    span = profile.values.get(span_key)
    if span is None:
        return _measure_finding([_missing(profile, f"{what} it takes")])
    ok = _fits(value, span)
    return _measure_finding(
        [
            Check(
                "thickness",
                "pass" if ok else "fail",
                f"{profile.product.name} takes {_range_text(span)} {what}; your {measured} is {_mm(value)}.",
            )
        ]
    )


@measure_rule("hinge")
def hinge_measure(hinge: Profile, measures: dict) -> Finding | None:
    value = measures.get("board_mm") or measures.get("door_mm")
    return None if value is None else _range_measure(hinge, "door_range", float(value), "door thickness", "shutter")


@measure_rule("door_lock")
def lock_measure(lock: Profile, measures: dict) -> Finding | None:
    value = measures.get("door_mm")
    return None if value is None else _range_measure(lock, "door_range", float(value), "door thickness", "door")


@measure_rule("glass_fitting")
def glass_measure(fitting: Profile, measures: dict) -> Finding | None:
    value = measures.get("glass_mm")
    return None if value is None else _range_measure(fitting, "glass_range", float(value), "glass thickness", "glass")


@measure_rule("screw")
def screw_measure(screw: Profile, measures: dict) -> Finding | None:
    value = measures.get("board_mm")
    if value is None:
        return None
    lengths = screw.values.get("screw_lens") or []
    if not lengths:
        return _measure_finding([_missing(screw, "screw length")])
    value = float(value)
    short = [n for n in lengths if n < value]
    if len(short) == len(lengths):
        return _measure_finding(
            [
                Check(
                    "screw length",
                    "pass",
                    f"{', '.join(_mm(n) for n in lengths)} screws stay inside your {_mm(value)} board.",
                )
            ]
        )
    if short:
        return _measure_finding(
            [
                Check(
                    "screw length",
                    "warn",
                    f"For your {_mm(value)} board use the {', '.join(_mm(n) for n in short)} screws.",
                )
            ]
        )
    return _measure_finding(
        [
            Check(
                "screw length",
                "warn",
                f"{', '.join(_mm(n) for n in lengths)} screws are longer than your {_mm(value)} board: they come through if fixed into its face.",
            )
        ]
    )


def channel_for_depth(lengths: list[float], depth_mm: float) -> float | None:
    """The longest listed channel length that fits a cabinet `depth_mm` deep inside (rear clearance kept)."""
    fitting = [n for n in lengths if n + CHANNEL_REAR_CLEARANCE_MM <= depth_mm]
    return max(fitting) if fitting else None


@measure_rule("drawer_channel")
def channel_measure(channel: Profile, measures: dict) -> Finding | None:
    value = measures.get("depth_mm")
    if value is None:
        return None
    lengths = channel.values.get("channel_lengths") or []
    if not lengths:
        return _measure_finding([_missing(channel, "channel length")])
    value = float(value)
    best = channel_for_depth(lengths, value)
    listed = ", ".join(_mm(n) for n in lengths)
    if best is None:
        return _measure_finding(
            [Check("length", "fail", f"Every listed length ({listed}) is too long for a {_mm(value)} deep cabinet.")]
        )
    if len(lengths) == 1:
        return _measure_finding([Check("length", "pass", f"A {_mm(best)} channel fits a {_mm(value)} deep cabinet.")])
    return _measure_finding(
        [
            Check(
                "length",
                "warn" if channel.variant is None else "pass",
                f"For a {_mm(value)} deep cabinet choose the {_mm(best)} channels.",
            )
        ]
    )


@measure_rule("handle")
def handle_measure(handle: Profile, measures: dict) -> Finding | None:
    value = measures.get("board_mm") or measures.get("door_mm")
    if value is None:
        return None
    length = handle.values.get("handle_screw_len")
    if length is None:
        return _measure_finding([_missing(handle, "length of its screws")])
    limit = length - HANDLE_THREAD_GRIP_MM
    ok = float(value) <= limit
    return _measure_finding(
        [
            Check(
                "screw length",
                "pass" if ok else "fail",
                f"The handle's {_mm(length)} screws suit shutters up to {_mm(limit)}; yours is {_mm(float(value))}.",
            )
        ]
    )


# Among several variants that fit, the best one by this fact (the longest channel that fits the depth).
MEASURE_BEST: dict[str, Callable[[Profile], float]] = {"drawer_channel": lambda p: p.values.get("channel_mm") or 0}


def check_measures(profile: Profile, measures: dict) -> Finding | None:
    """The product against the customer's measurements; None when no rule reads any of them."""
    fn = MEASURE_RULES.get(profile.kind)
    clean = {k: v for k, v in (measures or {}).items() if k in MEASURES and v not in (None, "")}
    return fn(profile, clean) if fn and clean else None


# --- Reasons -----------------------------------------------------------------------------------------------


def _reason(verdict: str, checks: list[Check]) -> str:
    if verdict == UNKNOWN:
        missing = [c.detail for c in checks if c.status == "missing"]
        return "Not enough information to confirm compatibility. " + "; ".join(missing) + "."
    order = {"fail": 0, "warn": 1, "pass": 2, "missing": 3}
    first = sorted(checks, key=lambda c: order[c.status])
    if verdict == COMPATIBLE:
        return " ".join(c.detail for c in checks if c.status == "pass")
    return " ".join(c.detail for c in first if c.status in ("fail", "warn"))
