"""Quantity AI (Phase 20): units, formulas, pack optimisation, the calculator flow (questions, assumptions,
interpretations), catalogue-only products, bulk tiers, offers and coupons, stock, delivery, the customer's
changes, add to cart, saving as a project, the project builder and voice using the same service, the AI
helper and its fallback, permissions and edge cases."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.ai.models import Project
from apps.ai.projects import templates as T
from apps.ai.quantity import formulas as F
from apps.ai.quantity import packs, service, units
from apps.ai.quantity.service import QuantityAIService
from apps.ai.services.voice import VoiceShoppingService
from apps.carts.models import CartItem
from apps.catalog.models import OptionType
from apps.catalog.services import set_price_tiers, set_variant_options
from apps.core.testing import add_stock, create_address, create_category, create_coupon, create_product, create_store
from apps.offers.models import Offer
from integrations.llm import LLMError, LLMProvider, LLMReply

URL = "/api/ai/quantity/"
CART = "/api/ai/quantity/add-to-cart/"
SAVE = "/api/ai/quantity/save/"
D = Decimal


# --- Units (no database) ---------------------------------------------------------------------------------


def test_units_convert_only_within_a_kind():
    assert units.convert(5, "m", "ft") == pytest.approx(16.404, rel=1e-3)
    assert units.convert(28, "sq m", "sq ft") == pytest.approx(301.39, rel=1e-3)
    assert units.convert(600, "mm", "inch") == pytest.approx(23.62, rel=1e-3)
    assert units.convert(500, "g", "kg") == 0.5
    assert units.convert(2, "metres", "feet") == pytest.approx(6.5617, rel=1e-3)
    with pytest.raises(units.UnitError):
        units.convert(5, "kg", "m")
    with pytest.raises(units.UnitError):
        units.canonical("furlong")
    assert units.units_for("ft") == ["ft", "m", "cm", "mm", "inch"]
    assert units.units_for("sq ft") == ["sq ft", "sq m"]


def test_measurements_are_read_with_their_interpretation():
    plain = units.read_dimensions("paint my 12x15 room")
    assert [(r.key, r.value) for r in plain] == [("length", 12), ("width", 15)] and plain[
        0
    ].note == "12 × 15 read as feet"
    metric = units.read_dimensions("a 5 m x 4 m bedroom")
    assert [r.value for r in metric] == [16.4, 13.12] and metric[0].note == "5 m × 4 m = 16.4 × 13.1 ft"
    assert [r.key for r in units.read_dimensions("10x12x9 ft")] == ["length", "width", "height"]
    area = units.read_area("tiles for 28 sq m")
    assert area.value == pytest.approx(301.39, rel=1e-3) and area.note == "28 sq m = 301.4 sq ft"
    assert units.read_area("500 sq ft plastering").note == ""
    wire = units.read_length("I need 100 feet of wire")
    assert wire.value == 30.48 and wire.note == "100 ft = 30.5 m"
    assert units.read_area("2.5 sq mm wire") is None  # a cross-section, not an area
    assert units.read_length("1/2 inch pipe, 25 mm") is None  # part sizes, not a run
    assert units.read_length("मुझे ५० मीटर पाइप चाहिए").value == 50


# --- Formulas --------------------------------------------------------------------------------------------


def test_formulas_and_their_breakdown():
    walls = F.wall_area(12, 15, 10, doors=1, windows=2)
    assert walls.amount == 540 - 21 - 24
    assert walls.steps[0][1] == "2 × (12 + 15) × 10 ft = 540 sq ft"
    with pytest.raises(F.FormulaError) as error:
        F.wall_area(3, 3, 3, doors=5, windows=5)
    assert error.value.key == "doors"
    assert F.paint_litres(507).amount == pytest.approx(507 * 2 / 130)
    cement, sand = F.plaster(500)
    # 500 sq ft = 46.45 m², 12 mm → 0.557 m³ wet × 1.33 × 1.05 → 1:5 → cement ÷ 0.0347 m³ a bag
    assert cement.amount == pytest.approx(3.74, abs=0.01) and sand.amount == pytest.approx(22.9, abs=0.1)
    assert cement.steps[-1][1].startswith("1:5 →") and cement.unit == "pcs" and sand.unit == "cft"
    assert F.plaster(500, ratio="1:4")[0].amount > cement.amount
    assert F.tiles(300, 4, "2 × 2 ft", 10).amount == 83  # 75 tiles + 10 % → 82.5 → 83
    assert F.tiles(300, 4, "2 × 2 ft", 0).amount == 75
    assert F.wire_metres(30, "route").amount == pytest.approx(66)  # phase + neutral, + 10 %
    assert F.wire_metres(30).amount == pytest.approx(33)
    assert F.solvent_tins(4, 1, 5).amount == 1  # 8 + 3 + 8 joints
    assert F.fasteners(10).amount == 12


def test_project_builder_and_quantity_ai_use_the_same_formulas():
    answers = {"length": 12, "width": 15, "surface": "interior", "condition": "good"}
    state = service.flow.resolve(T.CALCULATORS["painting"], answers)
    calc = {n.key: n.amount for n in T.CALCULATORS["painting"].materials(state.answers)}
    project = {n.key: n.amount for n in T.TEMPLATES["painting"].materials(state.answers)}
    assert calc == project and calc["emulsion"] == F.paint_litres(F.wall_area(12, 15).amount).amount
    plaster_project = T.TEMPLATES["construction"].materials(
        {"work": "plastering", "area": 500, "thickness_mm": 12, "ratio": "1:5"}
    )
    plaster_calc = T.CALCULATORS["plastering"].materials(
        {"area": 500, "thickness_mm": 12, "ratio": "1:5", "wastage": 5}
    )
    assert plaster_project[0].amount == plaster_calc[0].amount


# --- Fixtures --------------------------------------------------------------------------------------------


@pytest.fixture
def shop(db):
    store = create_store()
    civil, paint_cat, wires = create_category("Cement"), create_category("Paints"), create_category("Wires")
    bag = OptionType.objects.create(name="Bag size", unit="kg")
    cross = OptionType.objects.create(name="Cross-section", unit="sq mm")

    cement, cement_50 = create_product(name="PPC Cement", price="450.00", mrp="500.00", category=civil, stock=300,
                                       store=store, unit="bag", max_order_quantity=100)  # fmt: skip
    cement_50.name = "50 kg bag"
    cement_50.save()
    cement_25 = cement.variants.create(sku="PPC-25", name="25 kg bag", price=D("240.00"), mrp=D("260.00"))
    add_stock(cement_25, 100, store=store)
    set_variant_options(cement_50, [{"option_type": bag.pk, "value": "50 kg"}])
    set_variant_options(cement_25, [{"option_type": bag.pk, "value": "25 kg"}])
    tiers = [("10", "415.00"), ("30", "405.00"), ("50", "395.00"), ("70", "389.00")]
    set_price_tiers(cement_50, [{"min_quantity": int(q), "unit_price": p} for q, p in tiers])

    emulsion, e4 = create_product(
        name="Interior Emulsion Paint", price="999.00", mrp="1150.00", category=paint_cat, stock=40, store=store
    )
    e4.name = "4 L"
    e4.save()
    e1 = emulsion.variants.create(sku="EM-1", name="1 L", price=D("279.00"), mrp=D("320.00"))
    e10 = emulsion.variants.create(sku="EM-10", name="10 L", price=D("2349.00"), mrp=D("2700.00"))
    add_stock(e1, 50, store=store)
    add_stock(e10, 20, store=store)
    primer, p4 = create_product(
        name="Wall Primer", price="649.00", mrp="780.00", category=paint_cat, stock=30, store=store
    )
    p4.name = "4 L"
    p4.save()
    p1 = primer.variants.create(sku="PR-1", name="1 L", price=D("179.00"), mrp=D("220.00"))
    add_stock(p1, 30, store=store)
    roller, roller_v = create_product(
        name="Paint Roller 9 inch", price="349.00", category=paint_cat, stock=10, store=store
    )

    wire, w15 = create_product(
        name="Copper Wire 90 m", price="1749.00", mrp="2100.00", category=wires, stock=60, store=store, unit="coil"
    )
    w15.name = "1.5 sq mm"
    w15.save()
    w25 = wire.variants.create(sku="W-25", name="2.5 sq mm", price=D("2799.00"), mrp=D("3300.00"))
    add_stock(w25, 3, store=store)
    set_variant_options(w15, [{"option_type": cross.pk, "value": "1.5 sq mm"}])
    set_variant_options(w25, [{"option_type": cross.pk, "value": "2.5 sq mm"}])
    return locals()


def _estimate(client, **body):
    return client.post(URL, body, format="json")


def _item(data, key):
    return next(i for i in data["kit"]["items"] if i["material_key"] == key)


# --- Pack optimisation -----------------------------------------------------------------------------------


def test_packs_cheapest_combination_that_covers_the_need(shop, settings):
    options = [(shop["e4"], 4.0), (shop["e1"], 1.0), (shop["e10"], 10.0)]
    stock = {v.pk: 100 for v, _ in options}
    best = packs.optimise(options, 7.5, "l", stock=stock, limit=50)
    assert [(p.variant.pk, p.count) for p in best.parts] == [(shop["e4"].pk, 2)]
    assert best.cost == D("1998.00") and "2 × 4 L = ₹1,998 covers 7.5 L (cheapest way" in best.explanation
    mixed = packs.optimise(options, 4.6, "l", stock=stock, limit=50)  # 4 L + 1 L beats 5 × 1 L and 2 × 4 L
    assert [(p.variant.pk, p.count) for p in mixed.parts] == [(shop["e4"].pk, 1), (shop["e1"].pk, 1)]
    settings.QUANTITY_PACK_RULE = "fewest_packs"
    fewest = packs.optimise(options, 7.5, "l", stock=stock, limit=50)
    assert [(p.variant.pk, p.count) for p in fewest.parts] == [
        (shop["e10"].pk, 1)
    ] and "fewest packs" in fewest.explanation


def test_packs_prefer_what_is_in_stock_and_within_the_order_limit(shop):
    options = [(shop["e4"], 4.0), (shop["e1"], 1.0)]
    no_4l = packs.optimise(options, 7.5, "l", stock={shop["e4"].pk: 0, shop["e1"].pk: 50}, limit=50)
    assert [(p.variant.pk, p.count) for p in no_4l.parts] == [(shop["e1"].pk, 8)]
    # nothing fits within an order limit of 1: the cheapest cover is still returned, and the kit flags it
    limited = packs.optimise(options, 7.5, "l", stock={shop["e4"].pk: 50, shop["e1"].pk: 50}, limit=1)
    assert limited.covers >= 7.5 and max(p.count for p in limited.parts) > 1
    unknown = packs.optimise([(shop["roller_v"], None)], 3, "l", stock={}, limit=50)
    assert unknown.covers is None and unknown.parts[0].count == 1


# --- The calculator through the API ----------------------------------------------------------------------


def test_plastering_requirement_becomes_real_products_with_a_breakdown(api_client, shop):
    data = _estimate(api_client, text="I need materials for 500 sq ft plastering").json()
    assert data["calculator"] == "plastering" and data["complete"] and data["understood_by"] == "rules"
    assert data["label"] == "Estimated quantity" and data["title"] == "Plastering · 500 sq ft"
    assert [a["key"] for a in data["assumptions"]] == ["thickness_mm", "ratio", "wastage"]
    assert data["verify"] == "Verify measurements with a qualified professional before purchasing."
    cement = _item(data, "cement")
    assert cement["variant"]["id"] == shop["cement_50"].pk and cement["quantity"] == 4 and cement["is_estimate"]
    assert cement["product"]["name"] == "PPC Cement"
    sand = _item(data, "sand")
    assert sand["status"] == "not_found" and sand["variant"] is None and not sand["included"]
    material = next(m for m in data["materials"] if m["key"] == "cement")
    assert material["need"]["amount"] == pytest.approx(3.74, abs=0.01) and material["covers"] == 4
    assert [s["label"] for s in material["steps"]] == ["Area", "Mortar (wet)", "Dry materials", "Cement"]
    assert material["recommended"] == "4 × 50 kg bag"
    assert data["kit"]["can_add_to_cart"] and data["kit"]["totals"]["subtotal"] == "1800.00"
    assert data["kit"]["delivery"]["checked"] is False  # no PIN yet


def test_hinglish_requirement_and_only_missing_questions(api_client, shop):
    data = _estimate(api_client, text="Mujhe 500 sq ft ke liye plastering ka saman chahiye").json()
    assert data["language"] == "hinglish" and data["complete"] and data["name"] == "Plaster"
    data = _estimate(api_client, text="Mere 12x15 kamre ki putai karni hai").json()
    assert data["calculator"] == "painting" and data["missing"] == ["condition"]
    assert {"key": "length", "text": "12 × 15 read as feet"} in data["interpretations"]
    asked = next(q for q in data["questions"] if q["key"] == "condition")
    assert asked["kind"] == "choice" and data["kit"] is None
    assert {q["key"]: q["units"] for q in data["questions"]}["length"] == ["ft", "m", "cm", "mm", "inch"]
    data = _estimate(api_client, text="Mere 12x15 kamre ki putai karni hai", answers={"condition": "good"}).json()
    assert data["complete"] and _item(data, "emulsion")["variant"]["id"] == shop["e4"].pk


def test_room_paint_asks_size_then_uses_any_unit(api_client, shop):
    data = _estimate(api_client, text="How much paint do I need for a room?").json()
    assert data["calculator"] == "painting" and data["missing"] == ["length", "width", "condition"]
    assert {a["key"] for a in data["assumptions"]} == {"height", "doors", "windows"}
    answers = {"length": {"value": 5, "unit": "m"}, "width": {"value": 4, "unit": "m"}, "condition": "good", "doors": 2}
    data = _estimate(api_client, text="How much paint do I need for a room?", answers=answers).json()
    assert data["answers"]["length"] == 16.4 and data["answers"]["doors"] == 2
    assert {"key": "length", "text": "5 m = 16.4 ft"} in data["interpretations"]
    emulsion = next(m for m in data["materials"] if m["key"] == "emulsion")
    assert emulsion["steps"][1]["value"] == "2 × 21 + 1 × 12 = 54 sq ft"


def test_tiles_wire_and_metric_requirements(api_client, shop):
    data = _estimate(api_client, text="How many tiles do I need for 300 sq ft?").json()
    tiles = next(m for m in data["materials"] if m["key"] == "tiles")
    assert data["complete"] and tiles["need"]["amount"] == 83 and not tiles["found"]  # tiles aren't sold here
    assert data["not_sold"] and data["kit"]["not_found_count"] >= 1
    data = _estimate(api_client, text="Tiling a 10x12 room with 600x600 mm tiles").json()
    assert data["answers"]["tile_size"] == "2x2" and data["answers"]["length"] == 10
    data = _estimate(api_client, text="I need 100 feet of wire for lights").json()
    assert data["calculator"] == "wiring" and data["answers"] == {
        "metres": 30.48,
        "cross_section": "1.5",
        "runs": "total",
    }
    wire = _item(data, "wire")
    assert wire["variant"]["id"] == shop["w15"].pk and wire["quantity"] == 1  # 33.5 m → one 90 m coil
    assert {"key": "metres", "text": "100 ft = 30.5 m"} in data["interpretations"]
    power = _estimate(api_client, text="30 m wire for power sockets").json()
    assert _item(power, "wire")["variant"]["id"] == shop["w25"].pk


def test_size_words_in_the_requirement_choose_the_variant(api_client, shop):
    """ "25 kg cement for plastering": material cement, pack 25 kg, use plastering — from the listing's own
    understanding of the words, never an invented specification."""
    data = _estimate(api_client, text="25 kg cement for plastering 500 sq ft").json()
    cement = _item(data, "cement")
    assert cement["variant"]["id"] == shop["cement_25"].pk and cement["quantity"] == 4
    missing = _estimate(api_client, text="50 kg cement for plastering").json()
    assert missing["calculator"] == "plastering" and missing["missing"] == ["area"]


def test_products_must_be_named_by_the_need(api_client, shop):
    """Found live: "sand" matched "Sandpaper", "tiles" matched "Tile Adhesive"."""
    tools = create_category("Tools")
    create_product(name="Sandpaper Sheets (Pack of 10)", price="99.00", category=tools, stock=50, tags=["sandpaper"])
    create_product(
        name="Tile Adhesive 20 kg", price="529.00", category=tools, stock=50, tags=["tile", "tiles", "adhesive"]
    )
    data = _estimate(api_client, text="500 sq ft plastering").json()
    assert _item(data, "sand")["status"] == "not_found"
    data = _estimate(api_client, text="How many tiles do I need for 300 sq ft?").json()
    assert _item(data, "tiles")["status"] == "not_found" and _item(data, "adhesive")["status"] == "found"


def test_bulk_tier_and_the_next_tier(api_client, shop):
    """Need 50 bags: ₹395 each (50+), ₹19,750; 20 more unlock ₹389."""
    data = _estimate(api_client, text="500 sq ft plastering", overrides={"cement": {"quantity": 50}}).json()
    price = _item(data, "cement")["price"]
    assert price["unit_price"] == "395.00" and price["applied_tier"] == {"min_quantity": 50}
    assert price["line_total"] == "19750.00" and price["bulk_saving"] == "2750.00"
    assert price["next_tier"] == {"min_quantity": 70, "unit_price": "389.00", "units_more": 20, "reachable": True}
    assert data["kit"]["totals"]["bulk_savings"] == "2750.00"


def test_offers_and_coupons_come_from_the_shop_engine(api_client, auth_client, shop):
    now = timezone.now()
    offer = Offer.objects.create(
        name="Paint fest",
        discount_type="percent",
        value=D("10"),
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=1),
    )
    offer.categories.set([shop["paint_cat"]])
    create_coupon("PAINT50", discount_type="flat", value=D("50"))
    body = {"text": "paint for a 12x15 room, just repainting", "coupon": "paint50"}
    data = _estimate(api_client, **body).json()
    assert data["kit"]["offers"][0]["name"] == "Paint fest" and D(data["kit"]["totals"]["offer_discount"]) > 0
    assert data["kit"]["coupon"] == {"code": "PAINT50", "applied": False, "message": "Sign in to use a coupon."}
    data = _estimate(auth_client, **body).json()
    assert data["kit"]["coupon"]["applied"] and data["kit"]["totals"]["coupon_discount"] == "50.00"
    bad = _estimate(auth_client, **{**body, "coupon": "NOPE"}).json()
    assert not bad["kit"]["coupon"]["applied"] and bad["kit"]["coupon"]["message"]


def test_stock_status_and_short_stock(api_client, shop):
    data = _estimate(api_client, text="30 m wire for power sockets").json()  # 2.5 sq mm: 3 coils in stock
    assert _item(data, "wire")["stock_status"] == "available" and _item(data, "wire")["stock_available"] is None
    data = _estimate(api_client, text="300 m wire for power sockets").json()  # 330 m → 4 coils, 3 in stock
    wire = _item(data, "wire")
    assert wire["variant"]["id"] == shop["w25"].pk and wire["quantity"] == 4
    assert wire["stock_status"] == "limited" and wire["stock_available"] == 3 and wire["problem"] == "short_stock"
    assert not data["kit"]["can_add_to_cart"]


def test_very_large_quantities_hit_the_order_limit(api_client, shop):
    data = _estimate(api_client, text="5000 m wire for lights").json()  # 5500 m → 62 coils, at most 50 per order
    wire = _item(data, "wire")
    assert wire["quantity"] == 62 and wire["problem"] == "too_many" and not data["kit"]["can_add_to_cart"]
    assert any(i["code"] == "too_many" for i in data["kit"]["issues"])


def test_delivery_is_checked_with_the_delivery_engine(auth_client, user, shop):
    create_address(user)  # PIN 411001, inside the store's zone
    data = _estimate(auth_client, text="500 sq ft plastering").json()
    delivery = data["kit"]["delivery"]
    assert delivery["checked"] and delivery["available"] and isinstance(delivery["eta_minutes"], int)
    assert delivery["label"] and "60 minutes" not in delivery["message"]
    away = _estimate(auth_client, text="500 sq ft plastering", postal_code="110001").json()
    assert not away["kit"]["delivery"]["available"] and not away["kit"]["can_add_to_cart"]
    assert any(i["code"] == "not_deliverable" for i in away["kit"]["issues"])


def test_inactive_products_and_price_changes(api_client, shop):
    shop["e4"].price = D("899.00")
    shop["e4"].save()
    data = _estimate(api_client, text="paint for a 12x15 room, just repainting").json()
    assert _item(data, "emulsion")["price"]["unit_price"] == "899.00"  # always today's price
    shop["primer"].is_published = False
    shop["primer"].save()
    data = _estimate(api_client, text="paint for a 12x15 room, just repainting").json()
    primer = _item(data, "primer")
    assert primer["status"] == "not_found" and primer["variant"] is None  # never an unpublished product


def test_customer_changes_product_quantity_and_ticks(api_client, shop):
    text = "paint for a 12x15 room, just repainting"
    data = _estimate(api_client, text=text).json()
    assert {"primer", "primer~2"} <= {i["material_key"] for i in data["kit"]["items"]}  # 4 L + 1 L
    data = _estimate(api_client, text=text, overrides={"primer": {"variant_id": shop["p1"].pk}}).json()
    primer = _item(data, "primer")
    assert primer["variant"]["id"] == shop["p1"].pk and primer["quantity"] == 5 and primer["customer_set"]
    assert "primer~2" not in {i["material_key"] for i in data["kit"]["items"]}
    data = _estimate(
        api_client, text=text, overrides={"roller": {"included": False}, "emulsion": {"quantity": 3}}
    ).json()
    assert not _item(data, "roller")["included"] and _item(data, "emulsion")["quantity"] == 3
    response = _estimate(api_client, text=text, overrides={"primer": {"variant_id": 999_999}})
    assert response.status_code == 400 and response.json()["error"]["code"] == "product_unavailable"


def test_add_to_cart_all_or_nothing(api_client, auth_client, user, shop):
    lines = [{"variant_id": shop["cement_50"].pk, "quantity": 4}, {"variant_id": shop["w25"].pk, "quantity": 4}]
    assert api_client.post(CART, {"lines": lines}, format="json").status_code == 401
    response = auth_client.post(CART, {"lines": lines}, format="json")
    assert response.status_code == 400 and response.json()["error"]["code"] == "project_not_addable"
    assert not CartItem.objects.filter(cart__user=user).exists()
    lines[1]["quantity"] = 2
    assert auth_client.post(CART, {"lines": lines}, format="json").json() == {"added_lines": 2, "added_units": 6}
    assert {c.variant_id: c.quantity for c in CartItem.objects.filter(cart__user=user)} == {
        shop["cement_50"].pk: 4,
        shop["w25"].pk: 2,
    }
    assert auth_client.post(CART, {"lines": []}, format="json").status_code == 400


def test_save_as_a_project_and_edit_it_there(api_client, auth_client, user, shop):
    body = {"text": "500 sq ft plastering", "overrides": {"cement": {"variant_id": shop["cement_25"].pk}}}
    assert api_client.post(SAVE, body, format="json").status_code == 401
    response = auth_client.post(SAVE, body, format="json")
    assert response.status_code == 201
    project = Project.objects.get(pk=response.json()["project_id"], user=user)
    assert project.project_type == "plastering" and response.json()["path"] == f"/projects/{project.pk}"
    plan = auth_client.get(f"/api/ai/projects/{project.pk}/").json()
    assert plan["is_calculation"] and plan["complete"] and plan["verify"]
    cement = next(i for i in plan["kit"]["items"] if i["material_key"] == "cement")
    assert cement["variant"]["id"] == shop["cement_25"].pk and cement["customer_set"]
    assert any(p["id"] == project.pk for p in auth_client.get("/api/ai/projects/").json()["results"])


# --- Validation and edge cases ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answers, key",
    [
        ({"area": 0}, "area"),
        ({"area": -50}, "area"),
        ({"area": 999_999}, "area"),
        ({"area": "lots"}, "area"),
        ({"area": {"value": 50, "unit": "kg"}}, "area"),
        ({"area": 100, "ratio": "1:9"}, "ratio"),
    ],
)
def test_invalid_answers_are_refused(api_client, shop, answers, key):
    response = _estimate(api_client, calculator="plastering", answers=answers)
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_answers"
    assert key in response.json()["error"]["details"]


def test_impossible_dimensions_and_decimals(api_client, shop):
    tiny = {"length": 3, "width": 3, "height": 3, "doors": 10, "surface": "interior", "condition": "good"}
    response = _estimate(api_client, calculator="painting", answers=tiny)
    assert response.status_code == 400 and response.json()["error"]["details"]["doors"].startswith(
        "The doors and windows"
    )
    data = _estimate(api_client, calculator="plastering", answers={"area": {"value": 46.45, "unit": "sq m"}}).json()
    assert data["answers"]["area"] == pytest.approx(499.98, abs=0.05) and data["complete"]
    assert _estimate(api_client).status_code == 400  # nothing to calculate


def test_unknown_requirement_explains_instead_of_failing(api_client, shop):
    data = _estimate(api_client, text="hello there").json()
    assert data["calculator"] is None and not data["complete"] and data["message"].startswith("I couldn't tell")
    assert len(data["calculators"]) == len(T.CALCULATORS)
    assert data["ai"]["available"] is False and "isn't available" in data["ai"]["notice"]


def test_status_lists_the_calculators(api_client, db):
    data = api_client.get(URL, {"language": "hi"}).json()
    assert [c["key"] for c in data["calculators"]] == list(T.CALCULATORS)
    assert (
        data["label"] == "अनुमानित मात्रा" and data["pack_rule"] == "lowest_cost" and data["ai"] == {"available": False}
    )


# --- The AI helper and its fallback ----------------------------------------------------------------------


class FakeModel(LLMProvider):
    name = "fake"

    def __init__(self, reply: dict | None = None, error: Exception | None = None):
        self.reply, self.error, self.calls = reply, error, 0

    @property
    def available(self) -> bool:
        return True

    def chat(self, messages, options=None):
        self.calls += 1
        if self.error:
            raise self.error
        return LLMReply(json.dumps(self.reply))


def test_the_model_reads_what_the_rules_cannot_and_invented_numbers_are_dropped(shop, monkeypatch):
    model = FakeModel({"calculator": "plastering", "answers": {"area": 450, "thickness_mm": 15}})
    data = QuantityAIService(provider=model).estimate(text="cover my compound walls with cement, about 450 square foot")
    assert model.calls == 1 and data["calculator"] == "plastering" and data["understood_by"] == "ai"
    assert data["answers"]["area"] == 450 and "thickness_mm" not in data["from_ai"]  # 15 was never said
    assert "thickness_mm" not in data["answers"] and "thickness_mm" in [x["key"] for x in data["assumptions"]]
    assert data["ai"]["used"] and "check them" in data["ai"]["notice"]


def test_the_model_cannot_choose_options_the_customer_never_said(shop):
    model = FakeModel({"calculator": "tiling", "answers": {"tile_size": "2x4", "length": 20, "width": 15}})
    data = QuantityAIService(provider=model).estimate(text="cover my hall floor in squares, 20 feet by 15 feet")
    assert data["calculator"] == "tiling" and "tile_size" not in data["from_ai"]
    assert {"key": "tile_size", "value": "2x2"} in [{"key": a["key"], "value": a["value"]} for a in data["assumptions"]]


def test_recognised_requests_never_wait_for_the_model(shop):
    model = FakeModel({"calculator": "wiring", "answers": {}})
    data = QuantityAIService(provider=model).estimate(text="I need materials for 500 sq ft plastering")
    assert model.calls == 0 and data["understood_by"] == "rules"


def test_a_failing_model_falls_back_to_the_rules(shop):
    data = QuantityAIService(provider=FakeModel(error=LLMError("timeout"))).estimate(
        text="what should I buy, it is big"
    )
    assert data["calculator"] is None and "isn't available" in data["ai"]["notice"]
    data = QuantityAIService(provider=FakeModel(error=ValueError("bad"))).estimate(text="500 sq ft plastering")
    assert data["complete"]
    data = QuantityAIService(provider=FakeModel({"calculator": "rocket", "answers": {"area": "x"}})).estimate(
        text="something odd"
    )
    assert data["calculator"] is None


# --- Voice and the assistant use the same service ----------------------------------------------------------


def test_voice_quantity_request_goes_through_quantity_ai(shop):
    reply = VoiceShoppingService().command("I need materials for 500 sq ft plastering", language="en")
    assert reply.intent == "quantity" and reply.quantity["calculator"] == "plastering" and reply.quantity["complete"]
    assert reply.quantity["path"] == "/quantity?q=I%20need%20materials%20for%20500%20sq%20ft%20plastering"
    [cement] = reply.lines
    assert cement["status"] == "ready" and cement["variant_id"] == shop["cement_50"].pk and cement["quantity"] == 4
    assert reply.needs_confirmation and reply.reply.startswith("Plastering · 500 sq ft — estimated quantity:")
    assert "quantity calculator" in reply.reply  # sand isn't sold here: the full list is on the page


def test_voice_asks_for_missing_details_and_keeps_counted_orders(shop):
    reply = VoiceShoppingService().command("plastering ka saman kitna chahiye", language="hinglish")
    assert reply.intent == "quantity" and not reply.quantity["complete"] and reply.questions
    assert reply.reply.startswith("Plaster ka hisaab")
    counted = VoiceShoppingService().command("2 coils of 1.5 sq mm wire", language="en")
    assert counted.intent == "add_to_cart"


def test_assistant_paint_estimate_uses_the_quantity_formulas(shop):
    from apps.ai.services.assistant import HardwareAssistantService

    reply = HardwareAssistantService(LLMProvider()).answer("I need material to paint a 12x15 room.")
    assert reply.estimate["wall_area_sqft"] == round(F.wall_area(12, 15).amount)
    assert reply.estimate["calculator_path"].startswith("/quantity?q=")
