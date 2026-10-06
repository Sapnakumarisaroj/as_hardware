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
