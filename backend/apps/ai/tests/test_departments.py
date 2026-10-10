# ruff: noqa: E501 — fixture rows read better on one line
"""AI shopping for the shop's ten departments: Hinglish / Hindi words (search, voice), model text that must never
carry prices, stock or numbers of its own (intent budget and follow-up question, explanations, image
descriptions), compatibility questions with the customer's own sizes, and the carpentry / door / glass project
templates with their quantity rules and catalogue-only kits."""

import json
from decimal import Decimal

import pytest

from apps.ai.projects import flow, kit
from apps.ai.projects.templates import DOOR, GLASS_DOOR, KITCHEN, REPLACEMENT, TEMPLATES, WARDROBE
from apps.ai.quantity import formulas as F
from apps.ai.services import grounding, spoken
from apps.ai.services.assistant import HardwareAssistantService
from apps.ai.services.compatibility import CompatibilityAssistant, measures_in
from apps.ai.services.intent import IntentService
from apps.ai.services.voice import VoiceShoppingService
from apps.catalog.compatibility.rules import COMPATIBLE, NOT, UNKNOWN
from apps.catalog.models import OptionType, ProductSpecification
from apps.catalog.semantic.expand import expand
from apps.catalog.services import set_variant_options
from apps.core.testing import add_stock, create_category, create_product, create_store
from integrations.llm import ChatOptions, LLMProvider, LLMReply
from integrations.vision.base import clean_description, parse_answer

D = Decimal


class FakeProvider(LLMProvider):
    name = "fake"
    model = "fake-1"

    def __init__(self, replies):
        self.replies = list(replies)

    @property
    def available(self) -> bool:
        return True

    def chat(self, messages, options: ChatOptions | None = None) -> LLMReply:
        reply = self.replies.pop(0) if self.replies else {"message": "Sure."}
        return LLMReply(content=json.dumps(reply, ensure_ascii=False), provider=self.name, model=self.model)


# --- Words (no database) ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("said", "term"),
    [
        ("kabza", "hinge"), ("kabze chahiye", "hinge"), ("kabja wala", "hinge"), ("कब्जे", "hinge"),
        ("pench", "screws"), ("plai 18 mm", "plywood"), ("plaai", "plywood"), ("kil", "nails"), ("कील", "nails"),
        ("handal", "handle"), ("hendal", "handle"), ("mutthi", "handle"), ("chabi", "lock"), ("tala", "lock"),
        ("kunda", "latch"), ("kundi", "tower bolt"), ("chitkani", "tower bolt"), ("chatkani", "tower bolt"),
        ("aldrop", "aldrop"), ("aldrap", "tower bolt"), ("barma", "drill"), ("daraaz", "drawer channel"),
        ("daraz", "drawer channel"), ("almari", "wardrobe"), ("sunmica", "laminate"), ("sunmika", "contact adhesive"),
        ("nut bolt", "bolt"), ("hathoda", "hammer"), ("pechkas", "screwdriver"), ("dastane", "gloves"),
        ("chashma", "goggles"), ("joota", "safety shoes"), ("kanch", "glass"), ("kaanch ka darwaza", "glass door"),
        ("patch fitting", "patch fitting"), ("soft close", "soft close"), ("telescopic channel", "telescopic channel"),
        ("tandem box", "tandem box"), ("gola profile", "gola profile"),
    ],
)  # fmt: skip
def test_shop_words_in_hinglish_and_hindi_become_catalogue_words(said, term):
    assert term in expand(said).terms


def test_typo_correction_leaves_the_shops_own_words_alone():
    catalogue = frozenset({"hinge", "plywood", "kabja", "handle", "channel", "glass"})
    for word in ("kabza", "kabze", "plai", "handal", "daraz", "kanch"):
        found = expand(word, vocabulary=catalogue)
        assert word not in found.typos, (word, found.typos)


@pytest.mark.parametrize(
    ("said", "query", "quantity", "unit"),
    [
        ("do darjan kabze", "hinge", 24, "piece"),
        ("4 sheet plai 18 mm", "plywood 18 mm", 4, "piece"),
        ("50 pench", "screws", 50, ""),
        ("3 jodi daraz channel 18 inch", "drawer channel 18 inch", 3, "pair"),
        ("ek chitkani", "tower bolt", 1, ""),
        ("das handal", "handle", 10, ""),
    ],
)
def test_spoken_department_words_with_quantities(said, query, quantity, unit):
    [line] = spoken.parse(said).lines
    assert (line.query, line.quantity, line.unit) == (query, quantity, unit)


# --- Grounding: numbers and money in model text ---------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["only 500/-", "Rs. 450", "rs 450", "INR 900", "₹५००", "500 rupaye", "iski कीमत कम है", "MRP is low", "daam kam"],
)
def test_money_is_recognised_in_every_form(text):
    assert grounding.mentions_money(text)


def test_numbers_are_compared_in_one_form():
    assert grounding.numbers_in("₹1,500 or ५०० or 2.50") == {"1500", "500", "2.5"}
    assert grounding.number_said(500.0, "around ५०० ka budget") and not grounding.number_said(800, "500 tak")
    assert grounding.grounded("Use 18 mm ply.", "kitchen 18 mm plai") and not grounding.grounded(
        "Use 19 mm ply.", "18 mm"
    )


def test_vision_descriptions_lose_prices_stock_codes_and_numbers():
    assert clean_description("A brass hinge. It costs ₹250 and is in stock.") == "A brass hinge."
    assert clean_description("A steel handle, 160 mm, SKU HDL-1.") == ""
    assert clean_description("Concealed cabinet hinge with a round cup. Available for delivery today!") == (
        "Concealed cabinet hinge with a round cup."
    )
    result = parse_answer(
        {"item": "hinge", "confidence": 0.8, "description": "Looks like a ५०० रुपये hinge. A concealed hinge."},
        provider="x",
        model="y",
    )
    assert result.description == "A concealed hinge."


@pytest.mark.django_db
def test_a_model_budget_is_used_only_when_the_customer_said_it():
    vague = "something nice for my new flat"
    made_up = IntentService(FakeProvider([{"intent": "BUDGET", "budget": 1500, "search_terms": []}])).understand(vague)
    assert made_up.budget is None
    said = IntentService(FakeProvider([{"intent": "BUDGET", "budget": 1500}])).understand(
        "kuch accha sa 1500 wala gift"
    )
    assert said.budget in (None, D("1500"))  # the rules may read it first; the model can never change it
    assert IntentService(FakeProvider([{"budget": True}])).understand(vague).budget is None


@pytest.mark.django_db
def test_a_model_follow_up_question_with_prices_or_numbers_is_replaced():
    vague = "I need stuff"
    priced = {"needs_clarification": True, "question": "Our 499/- hinges are on offer, want 4?", "search_terms": []}
    understood = IntentService(FakeProvider([priced])).understand(vague)
    assert understood.needs_clarification and "499" not in understood.question and "4" not in understood.question
    clean = {"needs_clarification": True, "question": "Which room is it for?", "search_terms": []}
    assert IntentService(FakeProvider([clean])).understand(vague).question == "Which room is it for?"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "explanation",
    [
        "Overlay hinges cost about 500/- each and need a 35 mm cup.",
        "Full overlay means the door covers the side panel; usually 18 mm thick boards are used.",
        "पूरा ओवरले हिंज लगभग ५०० रुपये का आता है।",
        "Full overlay covers the panel. Rs. 120 per pair.",
    ],
)
def test_explanations_with_money_or_numbers_of_their_own_are_dropped(explanation):
    provider = FakeProvider([{"intent": "GENERAL_HARDWARE_QUESTION", "search_terms": []}, {"message": explanation}])
    reply = HardwareAssistantService(provider).answer("what does galvanised mean")
    assert all(k.get("source") != "model" for k in reply.knowledge)
    assert explanation not in reply.message


@pytest.mark.django_db
def test_a_grounded_explanation_is_kept():
    text = "Galvanising coats steel with zinc so that it does not rust."
    provider = FakeProvider([{"intent": "GENERAL_HARDWARE_QUESTION", "search_terms": []}, {"message": text}])
    reply = HardwareAssistantService(provider).answer("what does galvanised mean")
    assert reply.knowledge and reply.knowledge[0]["text"] == text


# --- A furniture-hardware shop ------------------------------------------------------------------------


@pytest.fixture
def shop(db):
    store = create_store()
    cats = {key: create_category(name) for key, name in {
        "board": "Plywood, MDF & HDHMR", "fevicol": "Fevicol", "hinge": "Hinges, Channels & Handles",
        "lock": "Door Locks & Hardware", "general": "General Hardware & Tools", "glass": "Glass Door Hardware",
    }.items()}  # fmt: skip

    def make(key, name, cat, tags, variants, specs=(), unit="piece", price="300.00"):
        product, first = create_product(
            name=name, category=cats[cat], tags=tags, stock=200, store=store, unit=unit, price=price, mrp=price
        )
        for spec_name, value, spec_unit in specs:
            ProductSpecification.objects.create(product=product, name=spec_name, value=value, unit=spec_unit)
        made = [first]
        if variants:
            first.name = variants[0]
            first.save()
            for index, vname in enumerate(variants[1:], start=1):
                v = product.variants.create(sku=f"{product.sku}-{index}", name=vname, price=D(price), mrp=D(price))
                add_stock(v, 200, store=store)
                made.append(v)
        return key, (product, made)

    made = dict(
        [
            make("ply", "BWP Marine Plywood, 8 x 4 ft", "board", ["plywood", "ply", "marine plywood", "bwp", "kitchen"], ("12 mm", "18 mm", "6 mm"), price="4190.00"),
            make("hinge", "Soft-Close Concealed Hinge, Full Overlay (Pair)", "hinge", ["hinge", "concealed hinge", "auto hinge", "soft close", "kabja"],
                 ("Full overlay", "Half overlay"), [("Cup Diameter", "35", "mm"), ("Door Thickness", "15 - 22", "mm")], unit="pair", price="329.00"),
            make("butt", "Stainless Steel Butt Hinge 4 inch (Pack of 2)", "hinge", ["hinge", "butt hinge", "door hinge"], (), [("Door Thickness", "30 - 45", "mm")], unit="pack"),
            make("channel", "Telescopic Ball-Bearing Drawer Channel (Pair)", "hinge", ["drawer channel", "drawer slide", "telescopic channel", "drawer"],
                 ("18 inch", "12 inch", "24 inch"), unit="pair", price="399.00"),
            make("handle", "Aluminium Profile Cabinet Handle", "hinge", ["handle", "cabinet handle", "drawer handle"], ("160 mm", "224 mm"),
                 [("Centre to Centre", "160, 224", "mm"), ("Fixing Screw", "M4", ""), ("Screw Length", "25", "mm")], price="189.00"),
            make("screws", "Wood Screws, Countersunk (Box of 100)", "general", ["screw", "wood screw"], ("No. 8 x 25 mm", "No. 8 x 38 mm"), unit="box", price="129.00"),
            make("fevicol", "Fevicol SH Synthetic Resin Wood Adhesive", "fevicol", ["fevicol", "glue", "wood adhesive"], ("1 kg", "500 g")),
            make("mortise", "Mortise Door Lock with Lever Handles", "lock", ["door lock", "mortise lock", "lock", "taala"], ("Satin steel",),
                 [("Door Thickness", "35 - 45", "mm"), ("Backset", "60", "mm")], unit="set", price="1890.00"),
            make("tower", "Tower Bolt 8 inch", "lock", ["tower bolt", "door bolt", "latch"], ()),
            make("patch", "Glass Door Patch Fitting Set (Top + Bottom)", "glass", ["patch fitting", "glass door", "toughened glass"], ("Satin steel",),
                 [("Glass Thickness", "10 - 12", "mm")], unit="set", price="3190.00"),
            make("spring", "Floor Spring for Glass Doors", "glass", ["floor spring", "glass door"], (), [("Glass Thickness", "8 - 12", "mm")], price="5490.00"),
            make("pull", "Glass Door Pull Handle, Back-to-Back", "glass", ["glass door handle", "pull handle", "glass door"], ("600 mm",),
                 [("Glass Thickness", "8 - 12", "mm")], price="1890.00"),
            make("sealant", "Silicone Sealant, Clear, 280 ml", "general", ["silicone", "sealant", "glass"], ()),
        ]
    )  # fmt: skip
    thickness = OptionType.objects.create(name="Thickness", unit="mm")  # as in the demo catalogue
    for variant in made["ply"][1]:
        set_variant_options(variant, [{"option_type": thickness.pk, "value": variant.name}])
    return made


def _lines(template, answers, language="en"):
    state = flow.resolve(template, answers)
    assert state.complete, [q.key for q in state.missing]
    return {line["material_key"]: line for line in kit.need_lines(template.materials(state.answers), language)}


# --- Voice -------------------------------------------------------------------------------------------------


def test_voice_finds_the_product_for_the_hinglish_word(shop):
    [hinge] = VoiceShoppingService().command("do darjan kabze", language="hinglish").lines
    assert hinge["product_id"] == shop["hinge"][0].pk
    [ply] = VoiceShoppingService().command("4 sheet plai 18 mm", language="hinglish").lines
    assert ply["product_id"] == shop["ply"][0].pk and ply["quantity"] == 4
    assert ply["variant_id"] == next(v.pk for v in shop["ply"][1] if v.name == "18 mm")
    [screws] = VoiceShoppingService().command("50 pench", language="hinglish").lines
    assert screws["product_id"] == shop["screws"][0].pk


# --- Compatibility questions with the customer's own sizes ---------------------------------------------


def test_sizes_are_read_with_what_they_measure():
    assert measures_in("will it fit 18 mm ply") == {"board_mm": 18}
    assert measures_in("kya ye १० mm kaanch pe lagega") == {"glass_mm": 10}
    assert measures_in("35 mm door ke liye") == {"door_mm": 35}
    assert measures_in("18 mm or 12 mm board") == {}  # two sizes: never paired with the wrong one
    assert measures_in("will it fit") == {}


def test_a_product_against_the_customers_size(shop):
    assistant = CompatibilityAssistant()
    reply = assistant.answer("Will the glass door patch fitting set work with 8 mm glass?")
    assert reply.compatibility["verdict"] == NOT and "10–12 mm" in reply.message
    reply = assistant.answer(
        "kya ye 18 mm shutter pe lagega?", language="hinglish", context_product_id=shop["hinge"][0].pk
    )
    assert reply.compatibility["verdict"] == COMPATIBLE and reply.compatibility["measures"] == {"board_mm": 18}
    reply = assistant.answer("will it fit a 35 mm door", context_product_id=shop["tower"][0].pk)
    assert reply.compatibility.get("verdict") != COMPATIBLE  # no rule for tower bolts: no invented verdict


# --- Quantity rules ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("height", "count"), [(600, 2), (900, 2), (901, 3), (1500, 3), (2100, 4), (2400, 5)])
def test_hinges_per_door_by_height(height, count):
    assert F.hinges_per_door(height) == count


def test_board_sheets_edge_band_and_screws():
    area = F.panel_area([("Sides", 2, 560, 720), ("Top and bottom", 2, 600, 560)])
    assert round(area.amount, 3) == round((2 * 560 * 720 + 2 * 600 * 560) / 1_000_000, 3)
    assert F.board_sheets(2.97, 0).amount == 1 and F.board_sheets(2.97, 15).amount == 2
    assert round(F.edge_band([("Shutter", 1, 500, 700)]).amount, 2) == round(2.4 * 1.1, 2)
    assert F.hinge_screws(6).amount == 24 and F.hinge_screws(6, F.SCREWS_PER_BUTT_HINGE).amount == 36
    assert F.channels(3).amount == 6 and F.handles(4, 2).amount == 6


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Modular kitchen with 6 cabinets, 8 shutters and 3 drawers", "modular_kitchen"),
        ("kitchen ke 5 cabinet 18 mm plai se banane hain", "modular_kitchen"),
        ("6 ft wardrobe with 3 shutters", "wardrobe"),
        ("4 feet ki almari banani hai", "wardrobe"),
        ("fit a mortise lock on 2 doors", "door_lock"),
        ("naya darwaza lagana hai, taala aur kabze chahiye", "door_lock"),
        ("glass door with 10 mm toughened glass", "glass_door"),
        ("office kaanch partition", "glass_door"),
        ("replace 4 broken soft close hinges", "hinge_replacement"),
        ("2 jodi daraz channel badalne hain", "hinge_replacement"),
        ("assemble a new wardrobe", "furniture_repair"),
    ],
)
def test_carpentry_project_types(text, expected):
    assert flow.detect_type(text) == expected


def test_the_description_fills_the_answers():
    assert flow.extract_answers(KITCHEN, "Modular kitchen with 6 cabinets, 8 shutters and 3 drawers, 18 mm ply") == {
        "cabinets": 6, "shutters": 8, "drawers": 3, "board": "plywood", "board_mm": "18",
    }  # fmt: skip
    assert flow.extract_answers(REPLACEMENT, "2 jodi daraz channel badalne hain, 18 inch") == {
        "part": "channel", "count": 2, "channel_length": 457.2,
    }  # fmt: skip
    assert flow.extract_answers(GLASS_DOOR, "glass door, 12 mm glass")["glass_mm"] == "12"


def test_kitchen_kit_uses_real_products_that_fit(shop):
    lines = _lines(KITCHEN, {"cabinets": 4, "shutters": 6, "drawers": 2})
    board = lines["board"]
    assert board["variant"].product_id == shop["ply"][0].pk and board["variant"].name == "18 mm"
    hinges = lines["hinges"]  # 6 shutters × 2 hinges (720 mm) = 12 hinges = 6 pairs
    assert (
        hinges["details"]["need_amount"] == 12
        and hinges["quantity"] == 6
        and hinges["variant"].product_id == shop["hinge"][0].pk
    )
    assert hinges["details"]["fit"]["verdict"] == COMPATIBLE
    channels = lines["channels"]  # 540 mm deep cabinets: the longest channel that fits is 18 inch (450 mm)
    assert (
        channels["variant"].name == "18 inch"
        and channels["quantity"] == 2
        and channels["details"]["fit"]["verdict"] in (COMPATIBLE, "POSSIBLY_COMPATIBLE")
    )
    assert lines["handles"]["quantity"] == 8 and lines["handles"]["variant"].product_id == shop["handle"][0].pk
    screws = lines["screws"]  # 4 × 16 carcass + 12 × 4 hinge + 2 × 12 channel screws = 136 → 2 boxes of 100
    assert screws["details"]["need_amount"] == 136 and screws["quantity"] == 2
    assert lines["edge_band"]["details"]["status"] == "not_found" and lines["edge_band"]["variant"] is None
    assert not lines["back_panel"]["included"] and lines["back_panel"]["variant"].name == "6 mm"


def test_shutter_thickness_the_hinges_dont_take_is_flagged(shop):
    lines = _lines(KITCHEN, {"cabinets": 1, "shutters": 1, "board_mm": "25"})
    assert (
        lines["hinges"]["details"]["fit"]["verdict"] == NOT
        and "15–22 mm" in lines["hinges"]["details"]["fit"]["reason"]
    )


def test_wardrobe_door_glass_and_replacement_kits(shop):
    wardrobe = _lines(WARDROBE, {"width": 6, "shutters": 3})
    assert wardrobe["hinges"]["details"]["need_amount"] == 15  # 7 ft = 2134 mm shutters: 5 each (above 2100 mm)
    door = _lines(DOOR, {"job": "door", "lock_type": "mortise", "doors": 2})
    assert (
        door["lock"]["variant"].product_id == shop["mortise"][0].pk
        and door["lock"]["details"]["fit"]["verdict"] == COMPATIBLE
    )
    assert door["hinges"]["variant"].product_id == shop["butt"][0].pk and door["hinges"]["details"]["need_amount"] == 8
    assert door["hinges"]["quantity"] == 4  # packs of 2
    assert door["screws"]["details"]["need_amount"] == 48
    thin = _lines(DOOR, {"job": "lock", "lock_type": "mortise", "door_mm": 30})
    assert thin["lock"]["details"]["fit"]["verdict"] == NOT
    glass = _lines(GLASS_DOOR, {"glass_mm": "8", "panels": 1})
    assert (
        glass["patch"]["details"]["fit"]["verdict"] == NOT
        and glass["pull_handle"]["details"]["fit"]["verdict"] == COMPATIBLE
    )
    assert glass["clamps"]["details"]["status"] == "not_found"  # not in the catalogue: nothing invented
    channels = _lines(REPLACEMENT, {"part": "channel", "count": 2, "channel_length": 457.2})
    assert channels["channels"]["variant"].name == "18 inch" and channels["channels"]["quantity"] == 2
    hinges = _lines(REPLACEMENT, {"part": "hinge", "count": 4, "overlay": "half"})
    assert hinges["hinges"]["variant"].name == "Half overlay" and hinges["hinges"]["quantity"] == 2
    handles = _lines(REPLACEMENT, {"part": "handle", "count": 3, "cc_mm": 224})
    assert handles["handles"]["variant"].name == "224 mm"


def test_a_spec_the_listing_lacks_is_never_guessed(shop):
    hinge = shop["hinge"][0]
    hinge.specifications.filter(key="door-thickness").delete()
    lines = _lines(KITCHEN, {"cabinets": 1, "shutters": 1})
    assert lines["hinges"]["details"]["fit"]["verdict"] == UNKNOWN


def test_project_api_prices_the_kit_from_the_catalogue(auth_client, shop):
    response = auth_client.post("/api/ai/projects/", {"description": "fit a mortise lock on 2 doors"}, format="json")
    assert response.status_code == 201, response.json()
    data = response.json()
    assert data["project_type"] == "door_lock" and data["complete"]
    lock = next(i for i in data["kit"]["items"] if i["material_key"] == "lock")
    assert lock["price"]["unit_price"] == "1890.00" and lock["quantity"] == 2 and lock["fit"]["verdict"] == COMPATIBLE
    assert "door_lock" in TEMPLATES
