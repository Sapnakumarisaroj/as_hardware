# ruff: noqa: E501 — the tables read better one item per line
"""The item kinds a photo is compared with (Phase 14).

Each kind is (label shown to the customer, catalogue search words, other names). Labels are generic
hardware items, not products: whether the shop *sells* one is decided afterwards by searching the
real catalogue. The shop's own category and subcategory names are added at run time, so a new
category is recognisable without editing this file.

NOT_HARDWARE kinds let a calibrated model say "this is a person / a pet / a screenshot" instead of
forcing the closest tool.
"""

import re

from django.db.models import Q

from apps.catalog.models import Category
from integrations.vision import Kind

TEMPLATES = ("a photo of a {}.", "a close-up photo of a {}.")
# Category names that describe a shelf, not a thing ("Electrical Tools"): they steal probability from real kinds.
GENERIC_WORDS = {"tool", "tools", "accessories", "equipment", "supplies", "materials", "hardware", "items", "products",
                 "misc", "other", "others", "distribution", "general", "essentials", "protective"}  # fmt: skip

HARDWARE: list[tuple[str, str, tuple[str, ...]]] = [
    # power tools
    ("electric drill", "drill", ("power drill", "drill machine", "corded drill")),
    ("impact drill", "impact drill", ("hammer drill", "concrete drill machine")),
    ("cordless drill", "cordless drill", ("battery drill driver", "cordless screwdriver drill")),
    ("drill bit", "drill bit", ("set of drill bits", "masonry drill bit", "metal drill bit")),
    ("angle grinder", "angle grinder", ("grinder", "cutting grinder")),
    ("jigsaw", "jigsaw", ("electric jigsaw",)),
    ("circular saw", "circular saw", ("power saw",)),
    ("glue gun", "glue gun", ("hot glue gun",)),
    ("heat gun", "heat gun", ()),
    ("soldering iron", "soldering iron", ()),
    # hand tools
    ("claw hammer", "hammer", ("hammer", "mallet")),
    ("screwdriver", "screwdriver", ("screwdriver set", "flat screwdriver", "phillips screwdriver")),
    ("spanner", "spanner", ("open end spanner", "combination spanner", "wrench")),
    ("adjustable wrench", "wrench", ("adjustable spanner",)),
    ("pipe wrench", "pipe wrench", ("plumber's wrench",)),
    ("pliers", "pliers", ("combination pliers", "nose pliers")),
    ("hacksaw", "hacksaw", ("metal saw", "hacksaw frame with blade")),
    ("hand saw", "saw", ("wood saw",)),
    ("measuring tape", "measuring tape", ("tape measure", "steel measuring tape")),
    ("spirit level", "spirit level", ("bubble level",)),
    ("utility knife", "cutter", ("box cutter", "paper cutter knife")),
    ("chisel", "chisel", ("wood chisel",)),
    ("allen key set", "allen key", ("hex key set",)),
    ("toolbox", "tool box", ("tool kit box",)),
    ("ladder", "ladder", ("aluminium ladder", "step ladder")),
    ("shovel", "shovel", ("spade",)),
    ("trowel", "trowel", ("plastering trowel",)),
    ("paint brush", "paint brush", ("painting brush",)),
    ("paint roller", "paint roller", ("roller brush",)),
    ("paint bucket", "paint", ("tin of paint", "can of wall paint")),
    ("putty knife", "putty knife", ("scraper",)),
    ("sandpaper", "sandpaper", ("emery paper",)),
    # fixings
    ("screws", "screw", ("wood screws", "box of screws")),
    ("nails", "nail", ("box of nails",)),
    ("wall plugs", "wall plug", ("plastic wall anchors", "rawl plugs")),
    ("nuts and bolts", "bolt", ("hex bolt with nut", "bolts")),
    ("door hinge", "hinge", ("hinges",)),
    ("padlock", "padlock", ("lock",)),
    ("door handle", "door handle", ("door lock handle",)),
    # plumbing
    ("water tap", "tap", ("faucet", "pillar tap", "bathroom tap", "kitchen tap")),
    ("shower head", "shower", ("hand shower",)),
    ("ball valve", "valve", ("water valve", "brass ball valve")),
    ("plastic water pipe", "pipe", ("pvc pipe", "cpvc pipe", "upvc pipe")),
    ("pipe fittings", "fitting", ("pipe elbow", "pipe tee", "pipe coupling")),
    ("braided hose connector", "connector", ("flexible water connector", "tap connector hose")),
    ("thread seal tape", "ptfe tape", ("teflon tape", "ptfe tape roll")),
    ("silicone sealant", "silicone sealant", ("sealant tube", "caulk cartridge")),
    ("garden hose", "hose", ("water hose pipe",)),
    ("sink", "sink", ("wash basin",)),
    # electrical
    ("led bulb", "led bulb", ("light bulb", "lamp bulb")),
    ("tube light", "led batten", ("led batten", "fluorescent tube light")),
    ("ceiling fan", "ceiling fan", ("fan",)),
    ("electrical switch", "switch", ("modular switch", "light switch")),
    ("electrical socket", "socket", ("power socket", "wall outlet", "plug point")),
    ("circuit breaker", "mcb", ("mcb", "miniature circuit breaker")),
    ("electrical wire", "wire", ("copper wire coil", "electric cable", "wire roll")),
    ("extension board", "extension board", ("power strip", "extension cord")),
    ("multimeter", "multimeter", ("digital multimeter",)),
    ("voltage tester", "tester", ("line tester screwdriver", "neon tester")),
    ("insulation tape", "insulation tape", ("electrical tape",)),
    ("cable ties", "cable tie", ("zip ties",)),
    ("battery", "battery", ("batteries",)),
    ("torch", "torch", ("flashlight",)),
    # building, gluing, safety
    ("cement bag", "cement", ("bag of cement",)),
    ("tile adhesive", "tile adhesive", ("bag of tile adhesive",)),
    ("floor tiles", "tile", ("ceramic tiles",)),
    ("wood glue", "adhesive", ("fevicol", "adhesive bottle")),
    ("safety helmet", "helmet", ("hard hat", "construction helmet")),
    ("safety goggles", "goggles", ("safety glasses",)),
    ("work gloves", "gloves", ("safety gloves",)),
    ("dust mask", "mask", ("n95 mask", "respirator mask")),
    ("safety shoes", "safety shoes", ("work boots", "steel toe shoes")),
]

NOT_HARDWARE: list[tuple[str, tuple[str, ...]]] = [
    ("a person", ("person", "face", "selfie", "people")),
    ("an animal", ("dog", "cat", "pet", "bird")),
    ("food", ("plate of food", "fruit", "drink")),
    ("a plant", ("plant", "flower", "tree")),
    ("a vehicle", ("car", "motorbike", "scooter")),
    ("a document or screenshot", ("document", "screenshot", "page of text")),
    ("a room or building", ("room", "building", "street", "landscape")),
    ("a phone or computer", ("mobile phone", "laptop", "computer screen")),
    ("clothes", ("shirt", "clothing", "shoes")),
]

NOT_HARDWARE_LABELS = frozenset(label for label, _ in NOT_HARDWARE)


def _prompts(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(t.format(name) for name in names for t in TEMPLATES)


def _base_kinds() -> list[Kind]:
    kinds = [Kind(label, _prompts((label, *other)), search) for label, search, other in HARDWARE]
    kinds += [
        Kind(label, tuple(f"a photo of {label}." for label in (label, *other)), "") for label, other in NOT_HARDWARE
    ]
    return kinds


def _singular(word: str) -> str:
    if word.endswith(("ches", "shes", "xes", "sses")):
        return word[:-2]  # "wrenches" → "wrench"
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def catalogue_kinds(known: set[str]) -> list[Kind]:
    """Specific subcategory names not already covered ("Sealants" when "silicone sealant" exists is skipped).

    Top-level categories and shelf names ("Electrical Tools", "Taps & Faucets") are left out: a photo
    shows one thing, and broad names only blur the probabilities of the specific kinds."""
    out = []
    names = Category.objects.filter(Q(is_active=True), parent__isnull=False).values_list("name", flat=True)
    for name in sorted(set(names)):
        key = _singular(name.lower())
        if set(key.split()) & GENERIC_WORDS or any(sep in key for sep in ("&", ",", "/")):
            continue
        if any(re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", k) for k in known):
            continue  # "sealant" is covered by "silicone sealant"; "torque wrench" is not covered by "wrench"
        known.add(key)
        out.append(Kind(name.lower(), _prompts((name.lower(),)), name.lower()))
    return out


def all_kinds() -> list[Kind]:
    base = _base_kinds()
    known = {_singular(k.label) for k in base} | {_singular(k.search) for k in base if k.search}
    return base + catalogue_kinds(known)


def is_hardware_label(label: str) -> bool:
    return label not in NOT_HARDWARE_LABELS
