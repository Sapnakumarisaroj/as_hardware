"""Compatibility for the shop's own departments: hinges ↔ board / shutter thickness, screws ↔ board thickness,
drawer channels ↔ cabinet depth and replacement length, handles (centre-to-centre, fixing screw), locks ↔ door
thickness, glass fittings ↔ glass thickness. Verdicts only from listed specifications; a missing one is
INSUFFICIENT_INFORMATION, never a guess, and explanations only use the listings' numbers."""

import re

import pytest

from apps.catalog.compatibility import profiles, rules
from apps.catalog.compatibility.rules import COMPATIBLE, NOT, POSSIBLY, UNKNOWN
from apps.catalog.compatibility.service import CompatibilityService
from apps.catalog.models import ProductSpecification
from apps.core.testing import add_stock, create_category, create_product, create_store

D = __import__("decimal").Decimal


@pytest.fixture
def fittings(db):
    store = create_store()
    hinges, boards = create_category("Hinges, Channels & Handles"), create_category("Plywood, MDF & HDHMR")
    locks, glass, general = (
        create_category("Door Locks & Hardware"),
        create_category("Glass Door Hardware"),
        create_category("General Hardware & Tools"),
    )

    def make(name, category, specs=(), variants=()):
        product, first = create_product(name=name, category=category, stock=20, store=store)
        for spec_name, value, unit in specs:
            ProductSpecification.objects.create(product=product, name=spec_name, value=value, unit=unit)
        made = [first]
        if variants:
            first.name = variants[0]
            first.save()
            for index, vname in enumerate(variants[1:], start=1):
                v = product.variants.create(sku=f"{product.sku}-{index}", name=vname, price=D("100"), mrp=D("120"))
                add_stock(v, 20, store=store)
                made.append(v)
        return product, made

    out = {}
    out["hinge"] = make(
        "Soft-Close Concealed Hinge (Pair)",
        hinges,
        [("Cup Diameter", "35", "mm"), ("Door Thickness", "15 - 22", "mm")],
        ("Full overlay", "Half overlay"),
    )
    out["hinge_nospec"] = make("Concealed Hinge Basic", hinges, [("Cup Diameter", "35", "mm")], ("Full overlay",))
    out["hinge_26"] = make("Mini Concealed Hinge 26 mm", hinges, [("Cup Diameter", "26", "mm")], ("Full overlay",))
    out["ply"] = make("BWP Marine Plywood, 8 x 4 ft", boards, variants=("12 mm", "18 mm", "6 mm"))
    out["ply25"] = make("Block Board 25 mm", boards, [("Thickness", "25", "mm")])
    out["channel"] = make(
        "Telescopic Ball-Bearing Drawer Channel (Pair)", hinges, variants=("18 inch", "12 inch", "24 inch")
    )
    out["channel_450"] = make("Soft Close Drawer Slide", hinges, variants=("450 mm",))
    out["handle"] = make(
        "Aluminium Profile Cabinet Handle",
        hinges,
        [("Centre to Centre", "160, 224", "mm"), ("Fixing Screw", "M4", ""), ("Screw Length", "25", "mm")],
        ("160 mm", "224 mm"),
    )
    out["handle_96"] = make("Steel D Handle", hinges, [("Centre to Centre", "96", "mm")], ("96 mm",))
    out["screws"] = make("Wood Screws, Countersunk (Box of 100)", general, variants=("No. 8 x 25 mm", "No. 8 x 38 mm"))
    out["short_screws"] = make("Hinge Screws (Box of 200)", general, variants=("No. 6 x 15 mm",))
    out["m4"] = make("Machine Screws M4", general, variants=("M4 x 25 mm",))
    out["mortise"] = make(
        "Mortise Door Lock with Lever Handles", locks, [("Door Thickness", "35 - 45", "mm"), ("Backset", "60", "mm")]
    )
    out["knob"] = make("Cylindrical Knob Lock, Bedroom", locks)
    out["door"] = make("Flush Door Shutter", locks, [("Stile Width", "100", "mm")], ("32 mm", "40 mm"))
    out["patch"] = make("Glass Door Patch Fitting Set", glass, [("Glass Thickness", "10 - 12", "mm")])
    out["pull"] = make("Glass Door Pull Handle, Back-to-Back", glass, [("Glass Thickness", "8 - 12", "mm")])
    out["spring"] = make("Floor Spring for Glass Doors", glass)
    out["glass8"] = make("Clear Toughened Glass 8 mm", glass, [("Thickness", "8", "mm")])
    out["hammer"] = make("Claw Hammer, Fibreglass Handle", general)
    out["tower"] = make("Tower Bolt 8 inch", locks)
    return out


def check(a, b, va=None, vb=None):
    return CompatibilityService().check(a, b, va, vb)


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def test_kinds_of_the_shops_departments(fittings):
    kinds = {key: profiles.kind_of(product) for key, (product, _) in fittings.items()}
    assert kinds["hinge"] == "hinge" and kinds["ply"] == "board" and kinds["ply25"] == "board"
    assert kinds["channel"] == kinds["channel_450"] == "drawer_channel"
    assert kinds["handle"] == "handle" and kinds["mortise"] == kinds["knob"] == "door_lock" and kinds["door"] == "door"
    assert kinds["patch"] == kinds["pull"] == kinds["spring"] == "glass_fitting" and kinds["glass8"] == "glass"
    assert kinds["hammer"] is None  # "Fibreglass Handle" is a hammer, not a cabinet handle
    assert kinds["tower"] is None  # a tower bolt is not a hex bolt


def test_profiles_read_only_listed_sizes(fittings):
    hinge = profiles.build(fittings["hinge"][0])
    assert (
        hinge.values["cup_mm"] == 35
        and hinge.values["door_range"] == (15, 22)
        and set(hinge.values["overlays"]) == {"full", "half"}
    )
    assert profiles.build(fittings["ply"][0]).values["thicknesses"] == [6, 12, 18]
    assert profiles.build(fittings["channel"][0]).values["channel_lengths"] == [
        300,
        450,
        600,
    ]  # trade sizes of 12/18/24 inch
    handle = profiles.build(fittings["handle"][0])
    assert (
        handle.values["ccs"] == [160, 224]
        and handle.values["handle_thread"] == 4
        and handle.values["handle_screw_len"] == 25
    )
    assert "door_range" not in profiles.build(fittings["knob"][0]).values  # not listed: never guessed
    assert "door_range" not in profiles.build(fittings["hinge_nospec"][0]).values


@pytest.mark.parametrize(
    ("a", "b", "verdict", "words"),
    [
        ("hinge", "ply", POSSIBLY, "choose the 18 mm board"),
        ("hinge", "ply25", NOT, "15–22 mm"),
        ("hinge_nospec", "ply", UNKNOWN, "door thickness it takes isn't in the listing"),
        ("screws", "ply", POSSIBLY, "longer than"),
        ("short_screws", "ply", POSSIBLY, "15 mm screws stay inside the 18 mm board"),
        ("hinge", "hinge_26", NOT, "won't take it"),
        ("hinge", "hinge_nospec", POSSIBLY, "same overlay"),
        ("channel", "channel_450", POSSIBLY, "450 mm"),
        ("handle", "handle_96", NOT, "new holes"),
        ("handle", "m4", COMPATIBLE, "M4"),
        ("handle", "screws", NOT, "wood screws"),
        ("mortise", "door", POSSIBLY, "choose the 40 mm door"),
        ("knob", "door", UNKNOWN, "isn't in the listing"),
        ("patch", "pull", POSSIBLY, "Both fit only 10–12 mm glass"),
        ("patch", "glass8", NOT, "10–12 mm"),
        ("pull", "glass8", COMPATIBLE, "8–12 mm"),
        ("spring", "pull", UNKNOWN, "isn't in the listing"),
    ],
)
def test_rules(fittings, a, b, verdict, words):
    result = check(fittings[a][0], fittings[b][0])
    assert result.verdict == verdict, result.reason
    assert words in result.reason
    # explanations only carry numbers from the two listings (names, specifications, variants)
    listed = " ".join(
        [p.name for p in (fittings[a][0], fittings[b][0])]
        + [f"{s.value} {s.unit}" for p in (fittings[a][0], fittings[b][0]) for s in p.specifications.all()]
        + [v.name for p in (fittings[a][0], fittings[b][0]) for v in p.variants.all()]
    )
    allowed = numbers(listed) | {"300", "450", "600"}  # channel inch sizes in millimetres
    assert numbers(result.reason) <= allowed | {str(int(n) + rules.MORTISE_CASE_MARGIN_MM) for n in numbers(listed)}


def test_a_variant_decides_and_matching_variants_are_named(fittings):
    hinge, (ply, ply_v) = fittings["hinge"][0], fittings["ply"]
    eighteen = next(v for v in ply_v if v.name == "18 mm")
    assert check(hinge, ply, None, eighteen).verdict == COMPATIBLE
    assert check(hinge, ply, None, next(v for v in ply_v if v.name == "6 mm")).verdict == NOT
    result = check(hinge, ply)
    assert [m["b"] for m in result.matching_variants] == [eighteen.pk]
    swapped = check(ply, hinge)  # the same rule either way round
    assert swapped.verdict == POSSIBLY and [m["a"] for m in swapped.matching_variants] == [eighteen.pk]


@pytest.mark.parametrize(
    ("key", "measures", "verdict", "words"),
    [
        ("hinge", {"board_mm": 18}, COMPATIBLE, "your shutter is 18 mm"),
        ("hinge", {"board_mm": 25}, NOT, "15–22 mm"),
        ("hinge_nospec", {"board_mm": 18}, UNKNOWN, "isn't in the listing"),
        ("mortise", {"door_mm": 35}, COMPATIBLE, "35–45 mm"),
        ("mortise", {"door_mm": 30}, NOT, "your door is 30 mm"),
        ("knob", {"door_mm": 35}, UNKNOWN, "isn't in the listing"),
        ("patch", {"glass_mm": 12}, COMPATIBLE, "10–12 mm"),
        ("patch", {"glass_mm": 8}, NOT, "your glass is 8 mm"),
        ("spring", {"glass_mm": 10}, UNKNOWN, "isn't in the listing"),
        ("channel", {"depth_mm": 500}, POSSIBLY, "choose the 450 mm channels"),
        ("channel", {"depth_mm": 280}, NOT, "too long"),
        ("screws", {"board_mm": 18}, POSSIBLY, "come through"),
        ("short_screws", {"board_mm": 18}, COMPATIBLE, "stay inside"),
        ("handle", {"board_mm": 18}, COMPATIBLE, "up to 19 mm"),
        ("handle", {"board_mm": 25}, NOT, "up to 19 mm"),
    ],
)
def test_against_the_customers_own_sizes(fittings, key, measures, verdict, words):
    result = CompatibilityService.check_measurements(fittings[key][0], None, measures)
    assert result.verdict == verdict and words in result.reason, result.reason
    assert result.as_dict()["product_b"] is None


def test_measurements_that_no_rule_reads_give_no_verdict(fittings):
    assert CompatibilityService.check_measurements(fittings["ply"][0], None, {"board_mm": 18}) is None
    assert CompatibilityService.check_measurements(fittings["hinge"][0], None, {"glass_mm": 10}) is None
    assert CompatibilityService.check_measurements(fittings["hinge"][0], None, {"colour": "red"}) is None


def test_the_fitting_variant_is_chosen_for_a_cabinet_depth(fittings):
    channel, variants = fittings["channel"]
    fitting = CompatibilityService().fitting_variants(channel, variants, {"depth_mm": 500})
    assert [v.name for v in fitting] == ["18 inch"]
    assert rules.channel_for_depth([300, 450, 600], 610) == 600 and rules.channel_for_depth([300], 290) is None
    # nothing fits: every variant stays, and the line's own check says why
    assert CompatibilityService().fitting_variants(channel, variants, {"depth_mm": 200}) == variants


def test_kit_lines_warn_about_hardware_that_does_not_fit(fittings):
    hinge_v, ply25_v = fittings["hinge"][1][0], fittings["ply25"][1][0]
    problems = CompatibilityService().check_lines([{"key": 1, "variant": hinge_v}, {"key": 2, "variant": ply25_v}])
    assert len(problems) == 1 and problems[0]["verdict"] == NOT and "won't work" in problems[0]["message"]
