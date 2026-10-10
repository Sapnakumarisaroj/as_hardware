# ruff: noqa: E501
"""Search quality benchmark: keyword search vs hybrid search on labelled queries.

The labels are written for the demo catalogue (`seed_demo_data`): each query lists product-name
fragments that a customer would accept as a good answer. A query counts as *found* when one of them
is in the top 10, and its rank is the position of the first one. Run:

    python manage.py benchmark_search [--verbose]

Numbers on a catalogue with other products are not comparable (the labels would not match).
"""

from django.test.utils import override_settings

from .. import selectors
from ..search import KeywordSearchBackend
from .backend import HybridSearchBackend

TOP = 10

# (query, [accepted product-name fragments]); grouped by what they test.
QUERIES: list[tuple[str, list[str]]] = [
    # the examples from the brief
    ("machine for drilling concrete", ["Impact Drill", "Masonry Drill Bit"]),
    ("water leakage fixing material", ["PTFE", "Silicone Sealant"]),
    ("wire for AC", ["Copper Wire"]),
    ("thing to hang shelf on wall", ["Wall Plugs", "Wood Screws"]),
    ("bathroom tap repair items", ["Pillar Tap", "PTFE", "Silicone Sealant", "Connector"]),
    ("Mujhe diwar me hole karne ka saman chahiye", ["Impact Drill", "Masonry Drill Bit"]),
    # describing what it does
    ("something to cut metal pipe", ["Hacksaw"]),
    ("tool to tighten nuts and bolts", ["Spanner", "Wrench"]),
    ("protect my eyes from dust while drilling", ["Goggles"]),
    ("cover for head at construction site", ["Helmet"]),
    ("light for my room", ["LED Bulb", "LED Batten"]),
    ("cooling for the room", ["Ceiling Fan"]),
    ("check if electric current is present", ["Multimeter", "Line Tester"]),
    ("glue for furniture", ["Wood Adhesive"]),
    ("stick floor tiles", ["Tile Adhesive"]),
    ("cement for plastering wall", ["Cement"]),
    ("measure length of wall", ["Measuring Tape"]),
    ("hit a nail into wood", ["Hammer"]),
    ("pipe for hot water", ["CPVC"]),
    ("mask for cement dust", ["N95"]),
    ("hand protection while working", ["Gloves"]),
    ("control water flow in a pipe", ["Ball Valve"]),
    ("trip switch for overload protection", ["MCB"]),
    ("point to plug in charger", ["Socket"]),
    # typos
    ("drll machine", ["Drill"]),
    ("silicon sealent", ["Silicone Sealant"]),
    ("screwdrivr set", ["Screwdriver"]),
    ("hamer", ["Hammer"]),
    ("mutimeter", ["Multimeter"]),
    # Hinglish
    ("nal tapak raha hai", ["Pillar Tap", "PTFE"]),
    ("bijli ka tar", ["Copper Wire"]),
    ("pankha", ["Ceiling Fan"]),
    ("paani ka pipe", ["CPVC", "UPVC"]),
    ("lakdi jodne ka gum", ["Wood Adhesive"]),
    ("safety joote", ["Safety Shoes"]),
    ("diwar me kil thokna", ["Hammer"]),
    # Hindi
    ("दीवार में छेद करने की मशीन", ["Impact Drill", "Masonry Drill Bit"]),
    ("नल टपक रहा है", ["Pillar Tap", "PTFE"]),
    ("बल्ब", ["LED Bulb"]),
    ("पंखा", ["Ceiling Fan"]),
    # the shop's departments in Hinglish and Hindi (approved taxonomy, 2026-10)
    ("kabza chahiye", ["Concealed Hinge", "Butt Hinge"]),
    ("soft close kabze", ["Concealed Hinge"]),
    ("कब्जे", ["Concealed Hinge", "Butt Hinge"]),
    ("18 mm plai", ["Plywood"]),
    ("plaai sheet", ["Plywood"]),
    ("sunmica ka gond", ["Contact Adhesive"]),
    ("pench", ["Wood Screws"]),
    ("nut bolt", ["Hex Bolt"]),
    ("daraz channel", ["Drawer Channel"]),
    ("telescopic channel", ["Drawer Channel"]),
    ("almari ka handal", ["Cabinet Handle", "Wardrobe"]),
    ("chitkani", ["Tower Bolt"]),
    ("darwaze ka tala chabi", ["Door Lock", "Knob Lock"]),
    ("barma machine", ["Drill"]),
    ("hathoda", ["Hammer"]),
    ("pechkas", ["Screwdriver"]),
    ("dastane", ["Gloves"]),
    ("chashma", ["Goggles"]),
    ("kaanch ka darwaza fitting", ["Patch Fitting", "Floor Spring", "Glass Door"]),
    ("patch fitting", ["Patch Fitting"]),
    # control: exact names must keep working
    ("pipe wrench", ["Pipe Wrench"]),
    ("led bulb", ["LED Bulb"]),
    ("wood screws", ["Wood Screws"]),
]

# Written after the synonym table and NOT used to tune it: they avoid its trigger words, so they show
# what the embedding model itself adds beyond the tables.
HELD_OUT: list[tuple[str, list[str]]] = [
    ("equipment to determine if a circuit has power", ["Multimeter", "Line Tester"]),
    ("footwear for factory workers", ["Safety Shoes"]),
    ("keep my fingers safe from sharp edges", ["Gloves"]),
    ("tool for turning hex fasteners", ["Spanner", "Wrench"]),
    ("bonding compound for ceramic floor", ["Tile Adhesive"]),
    ("caulk for around the sink", ["Silicone Sealant"]),
    ("illumination for a workshop ceiling", ["LED Batten", "LED Bulb"]),
    ("rechargeable power tool for fastening screws", ["Cordless Drill"]),
    ("fastener that grips inside masonry", ["Wall Plugs"]),
    ("threaded fastener with a nut", ["Hex Bolt"]),
    ("material to wrap threads on pipe joints", ["PTFE"]),
    ("head gear for scaffolding work", ["Helmet"]),
    ("filter for inhaling fine particles", ["N95"]),
    ("copper conductor for home installation", ["Copper Wire"]),
    ("stainless line joining tap to supply", ["Connector"]),
    ("rotating machine to circulate air", ["Ceiling Fan"]),
    ("gadget for driving screws by hand", ["Screwdriver"]),
    ("pack of small plastic anchors", ["Wall Plugs"]),
    ("tool used to hammer things", ["Hammer"]),
    ("dimension gauge roll", ["Measuring Tape"]),
]

SETS = {"main": QUERIES, "held_out": HELD_OUT}


def _top_names(result) -> list[str]:
    qs = result.queryset.order_by(*selectors.ORDERINGS["relevance"])
    return list(qs.values_list("name", flat=True)[:TOP])


def _rank(names: list[str], accepted: list[str]) -> int | None:
    for position, name in enumerate(names, start=1):
        if any(fragment.lower() in name.lower() for fragment in accepted):
            return position
    return None


def _summary(ranks: list[int | None]) -> dict:
    total = len(ranks)
    found = [r for r in ranks if r]
    return {
        "total": total,
        "found": len(found),
        "hit1": sum(1 for r in found if r <= 1) / total,
        "hit3": sum(1 for r in found if r <= 3) / total,
        "hit5": sum(1 for r in found if r <= 5) / total,
        "mrr": sum(1 / r for r in found) / total,
    }


def run(queries=None) -> dict:
    """keyword: Phase 4 search. related: + synonyms, Hindi/Hinglish words, typo correction (no model).
    hybrid: + the configured embedder (SEMANTIC_EMBEDDER)."""
    keyword, hybrid = KeywordSearchBackend(), HybridSearchBackend()
    rows, ranks = [], {"keyword": [], "related": [], "hybrid": []}
    for query, accepted in queries or QUERIES:
        base = selectors.product_queryset()
        names = {"keyword": _top_names(keyword.search(base, query))}
        with override_settings(SEMANTIC_EMBEDDER="none"):
            names["related"] = _top_names(hybrid.search(base, query))
        names["hybrid"] = _top_names(hybrid.search(base, query))
        row = {"query": query}
        for mode, top in names.items():
            row[f"{mode}_rank"] = _rank(top, accepted)
            row[f"{mode}_top"] = top[:3]
            ranks[mode].append(row[f"{mode}_rank"])
        rows.append(row)
    return {"queries": rows, **{mode: _summary(values) for mode, values in ranks.items()}}
