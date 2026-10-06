"""Project builder (Phase 19): the guided flow (type, answers from the description, questions, assumptions),
the material rules, catalogue-only kits with pack sizes and variants, kit pricing through the shop's
pricing engine (tiers, offers, delivery), customer changes, all-or-nothing add to cart, and isolation."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.ai.models import Project
from apps.ai.projects import flow, kit
from apps.ai.projects.templates import PAINTING, TEMPLATES, WALL_DRILLING
from apps.carts.models import CartItem
from apps.carts.services import add_item
from apps.catalog.models import OptionType
from apps.catalog.services import set_price_tiers, set_variant_options
from apps.core.testing import add_stock, create_address, create_category, create_product, create_store
from apps.offers.models import Offer
from apps.orders.pricing import line_from_variant, price_lines

URL = "/api/ai/projects/"
TYPES = "/api/ai/project-types/"
D = Decimal


# --- Flow (no database) --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("paint my 12x15 bedroom", "painting"),
        ("mujhe kamre ki putai karni hai", "painting"),
        ("मेरे कमरे की पुताई करनी है", "painting"),
        ("install 2 shelves on a concrete wall", "wall_drilling"),
        ("terrace waterproofing, seepage in ceiling", "waterproofing"),
        ("tiling my bathroom floor", "tiling"),
        ("bathroom tap is dripping", "bathroom_repair"),
        ("new wiring for 6 points", "electrical"),
        ("plaster 200 sq ft wall", "construction"),
        ("assemble a new wardrobe", "furniture_repair"),
        ("hello there", None),
    ],
)
def test_project_type_from_the_description(text, expected):
    assert flow.detect_type(text) == expected


def test_answers_read_from_the_description():
    found = flow.extract_answers(PAINTING, "Paint my 12x15 bedroom, the walls have cracks")
    assert found == {"length": 12, "width": 15, "surface": "interior", "condition": "minor"}
    # Devanagari digits and words
    found = flow.extract_answers(PAINTING, "मेरे १० x १२ कमरे की पुताई, दीवार में दरार है")
    assert found["length"] == 10 and found["width"] == 12 and found["condition"] == "minor"
    drilling = flow.extract_answers(WALL_DRILLING, "install 2 shelves on a brick wall, I don't have a drill")
    assert drilling == {"shelves": 2, "wall_type": "brick", "have_drill": "no"}


def test_only_missing_questions_are_asked_and_defaults_are_assumptions():
    state = flow.resolve(PAINTING, {"length": 12, "width": 15})
    assert [q.key for q in state.missing] == ["surface", "condition"]
    assert state.assumptions == [{"key": "height", "value": 10}]
    state = flow.resolve(PAINTING, {"length": 12, "width": 15, "surface": "interior", "condition": "good"})
    assert state.complete and state.answers["height"] == 10


def test_conditional_questions_follow_earlier_answers():
    plumbing = TEMPLATES["plumbing"]
    assert [q.key for q in flow.resolve(plumbing, {"job": "fix_leak"}).missing] == []
    assert [q.key for q in flow.resolve(plumbing, {"job": "new_line"}).missing] == ["pipe_kind", "length_m", "fittings"]


def test_answers_are_validated():
    accepted, errors = flow.clean_answers(PAINTING, {"length": "12.5", "width": "0", "surface": "garden", "x": 1})
    assert accepted == {"length": 12.5}
    assert set(errors) == {"width", "surface"}


def test_painting_quantities_follow_the_labelled_rules():
    needs = {
        n.key: n
        for n in PAINTING.materials(
            {"length": 12, "width": 15, "height": 10, "surface": "interior", "condition": "minor"}
        )
    }
    area = 2 * (12 + 15) * 10 * 0.9  # 486 sq ft of wall
    assert needs["emulsion"].amount == pytest.approx(area * 2 / 130)
    assert needs["primer"].amount == pytest.approx(area / 110)
    assert needs["putty"].amount == pytest.approx(area / 50)
    assert not needs["sandpaper"].optional
    good = {
        n.key
        for n in PAINTING.materials(
            {"length": 12, "width": 15, "height": 10, "surface": "interior", "condition": "good"}
        )
    }
    assert "putty" not in good


# --- Fixtures ------------------------------------------------------------------------------------------


@pytest.fixture
def paints(db):
    store = create_store()
    paint_cat = create_category("Paints")
    tools = create_category("Painting Tools")
    volume = OptionType.objects.create(name="Volume", unit="L")

    def sized(name, sizes, category=paint_cat, **kwargs):
        """sizes: [(variant name, price, stock)]; the first is the default variant."""
        first_name, first_price, first_stock = sizes[0]
        product, variant = create_product(name=name, price=first_price, mrp=str(D(first_price) * 2), category=category,
                                          stock=first_stock, store=store, **kwargs)  # fmt: skip
        variant.name = first_name
        variant.save()
        variants = [variant]
        for index, (vname, price, stock) in enumerate(sizes[1:], start=1):
            v = product.variants.create(sku=f"{product.sku}-{index}", name=vname, price=D(price), mrp=D(price) * 2)
            add_stock(v, stock, store=store)
            variants.append(v)
        if all(v.name.endswith(" L") for v in variants):
            for v in variants:
                set_variant_options(v, [{"option_type": volume.pk, "value": v.name}])
        return product, variants

    emulsion, emulsion_v = sized(
        "Interior Emulsion Paint", [("4 L", "999.00", 40), ("1 L", "279.00", 50), ("10 L", "2349.00", 20)]
    )
    set_price_tiers(emulsion_v[0], [{"min_quantity": 3, "unit_price": "969.00"}])
    primer, primer_v = sized("Wall Primer", [("4 L", "649.00", 50), ("1 L", "179.00", 50)])
    putty, putty_v = sized("Wall Putty", [("20 kg", "799.00", 30), ("5 kg", "229.00", 30)], unit="bag")
    roller, roller_v = sized("Paint Roller 9 inch", [("", "349.00", 20)], category=tools)
    brush, brush_v = sized("Paint Brush Set (3 pcs)", [("", "219.00", 20)], category=tools)
    tape, tape_v = sized("Masking Tape 1 inch, 20 m", [("", "65.00", 40)], category=tools)
    sand, sand_v = sized("Sandpaper Sheets (Pack of 10)", [("", "99.00", 40)], category=tools)
    return {
        "store": store,
        "paint_cat": paint_cat,
        "emulsion": emulsion,
        "emulsion_v": emulsion_v,
        "primer_v": primer_v,
        "putty_v": putty_v,
        "roller_v": roller_v,
        "brush_v": brush_v,
        "tape_v": tape_v,
        "sand_v": sand_v,
    }


@pytest.fixture
def home(user):
    return create_address(user)  # PIN 411001, inside the test store's zone


def _start(client, **body):
    return client.post(URL, body, format="json")


def _item(data, key):
    return next(i for i in data["kit"]["items"] if i["material_key"] == key)


ROOM = "Paint my 12x15 bedroom, the walls have a few cracks"


# --- Kits from the catalogue ---------------------------------------------------------------------------


def test_pack_sizes_are_read_from_the_listing(paints):
    emulsion_4l = paints["emulsion_v"][0]
    assert kit.pack_amount(emulsion_4l.product, emulsion_4l, "l") == 4
    assert kit.pack_amount(paints["putty_v"][1].product, paints["putty_v"][1], "kg") == 5
    assert kit.pack_amount(paints["tape_v"][0].product, paints["tape_v"][0], "m") == 20
    assert kit.pack_amount(paints["sand_v"][0].product, paints["sand_v"][0], "pcs") == 10
    assert kit.pack_amount(paints["brush_v"][0].product, paints["brush_v"][0], "pcs") == 3
    assert kit.pack_amount(paints["roller_v"][0].product, paints["roller_v"][0], "l") is None
    assert kit.packs_for(7.48, 4) == 2 and kit.packs_for(8.0, 4) == 2 and kit.packs_for(0.2, 10) == 1


def test_a_described_job_becomes_a_priced_kit_of_real_products(auth_client, user, paints, home):
    response = _start(auth_client, description=ROOM)
    assert response.status_code == 201
    data = response.json()
    assert data["project_type"] == "painting" and data["complete"] and data["status"] == "ready"
    assert data["missing"] == [] and data["from_description"] == ["condition", "length", "surface", "width"]
    assert [a["key"] for a in data["assumptions"]] == ["height"]
    assert data["title"] == "Painting · 12 × 15 ft room"
    emulsion = _item(data, "emulsion")
    # 7.5 L needed: two 4 L tins (₹1,998) beat eight 1 L (₹2,232) and one 10 L (₹2,349)
    assert emulsion["variant"]["id"] == paints["emulsion_v"][0].pk and emulsion["quantity"] == 2
    assert emulsion["is_estimate"] and emulsion["included"] and emulsion["product"]["name"] == "Interior Emulsion Paint"
    assert _item(data, "primer")["variant"]["id"] == paints["primer_v"][1].pk and _item(data, "primer")["quantity"] == 5
    putty = _item(data, "putty")  # 9.7 kg: two 5 kg bags (₹458) beat one 20 kg (₹799)
    assert putty["variant"]["id"] == paints["putty_v"][1].pk and putty["quantity"] == 2
    assert "cracks" in putty["rationale"]
    assert _item(data, "masking_tape")["quantity"] == 2  # 33 m of edges, 20 m rolls
    assert _item(data, "brush")["quantity"] == 1  # a set of 3 covers 2 brushes

    # the totals are the pricing engine's for exactly the ticked lines
    lines = [
        line_from_variant(item.variant, int(item.quantity))
        for item in Project.objects.get(pk=data["id"]).items.filter(included=True).select_related("variant__product")
    ]
    totals = price_lines(lines, user=user).totals
    assert data["kit"]["totals"]["subtotal"] == f"{totals.subtotal:.2f}"
    assert data["kit"]["delivery"]["checked"] and data["kit"]["delivery"]["available"]
    assert data["kit"]["postal_code"] == "411001"
    assert data["kit"]["can_add_to_cart"] and data["kit"]["issues"] == []
    assert any("ventilated" in line for line in data["safety"])


def test_missing_answers_are_asked_then_the_kit_is_built(auth_client, paints):
    data = _start(auth_client, description="I want to paint my room").json()
    assert not data["complete"] and data["status"] == "draft" and data["kit"] is None
    assert data["missing"] == ["length", "width", "condition"]  # "room" already says inside walls
    asked = {q["key"]: q for q in data["questions"]}
    assert asked["condition"]["kind"] == "choice" and len(asked["condition"]["choices"]) == 3
    data = auth_client.patch(
        f"{URL}{data['id']}/", {"answers": {"length": 10, "width": 12, "condition": "good"}}, format="json"
    ).json()
    assert data["complete"] and data["kit"]["items"]
    assert "putty" not in {i["material_key"] for i in data["kit"]["items"]}


def test_a_project_can_start_from_a_type_with_answers(auth_client, paints):
    answers = {"length": 10, "width": 10, "surface": "interior", "condition": "good"}
    data = _start(auth_client, project_type="painting", answers=answers).json()
    assert data["complete"] and data["description"] == ""


def test_invalid_input_is_refused(auth_client, paints):
    response = _start(auth_client, description="hello there")
    assert response.status_code == 400 and response.json()["error"]["code"] == "project_type_unknown"
    response = _start(auth_client, project_type="painting", answers={"length": -3})
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_answers"
    assert _start(auth_client).status_code == 400
    assert _start(auth_client, project_type="gardening").status_code == 400
    project = _start(auth_client, description=ROOM).json()
    response = auth_client.patch(f"{URL}{project['id']}/", {"answers": {"surface": "moon"}}, format="json")
    assert response.status_code == 400 and response.json()["error"]["details"] == {
        "surface": "Choose one of the options."
    }


def test_materials_the_shop_does_not_sell_are_never_invented(auth_client, paints):
    data = _start(auth_client, description="install 2 shelves on a concrete wall, I don't have a drill").json()
    assert data["complete"]
    for item in data["kit"]["items"]:
        assert item["status"] == "not_found" and item["variant"] is None and not item["included"]
    assert data["kit"]["not_found_count"] == len(data["kit"]["items"])
    assert data["kit"]["totals"]["subtotal"] == "0.00" and not data["kit"]["can_add_to_cart"]


def test_bulk_tier_and_offers_apply_to_the_whole_kit(auth_client, paints, home):
    offer = Offer.objects.create(
        name="Paint week",
        discount_type="percent",
        value=D("10"),
        starts_at=timezone.now() - timedelta(days=1),
        ends_at=timezone.now() + timedelta(days=1),
    )
    offer.categories.set([paints["paint_cat"]])
    data = _start(auth_client, description=ROOM).json()
    emulsion = _item(data, "emulsion")
    assert emulsion["price"]["next_tier"] == {"min_quantity": 3, "unit_price": "969.00", "units_more": 1}
    assert data["kit"]["offers"][0]["name"] == "Paint week" and D(emulsion["price"]["offer_discount"]) > 0
    data = auth_client.patch(f"{URL}{data['id']}/items/{emulsion['id']}/", {"quantity": 3}, format="json").json()
    emulsion = _item(data, "emulsion")
    assert emulsion["price"]["unit_price"] == "969.00" and emulsion["price"]["applied_tier"] == {"min_quantity": 3}
    assert emulsion["price"]["bulk_saving"] == "90.00" and emulsion["customer_set"]


def test_customer_changes_survive_new_answers(auth_client, paints):
    data = _start(auth_client, description=ROOM).json()
    emulsion, roller = _item(data, "emulsion"), _item(data, "roller")
    one_litre = paints["emulsion_v"][1]
    base = f"{URL}{data['id']}/items/"
    data = auth_client.patch(f"{base}{emulsion['id']}/", {"variant_id": one_litre.pk}, format="json").json()
    assert (
        _item(data, "emulsion")["variant"]["id"] == one_litre.pk and _item(data, "emulsion")["quantity"] == 8
    )  # same need
    auth_client.patch(f"{base}{roller['id']}/", {"included": False}, format="json")
    data = auth_client.patch(f"{URL}{data['id']}/", {"answers": {"length": 20}}, format="json").json()
    changed = _item(data, "emulsion")
    assert changed["variant"]["id"] == one_litre.pk and changed["quantity"] == 8 and changed["customer_set"]
    # the new suggestion is shown next to it: 9.7 L → one 10 L tin (₹2,349) beats three 4 L (₹2,907 at the tier)
    assert changed["need"]["amount"] > 9
    assert changed["suggested"] == {"variant_id": paints["emulsion_v"][2].pk, "quantity": 1}
    assert not _item(data, "roller")["included"]
    data = auth_client.post(f"{URL}{data['id']}/reset/").json()
    assert _item(data, "emulsion")["variant"]["id"] == paints["emulsion_v"][2].pk
    assert not _item(data, "emulsion")["customer_set"]
    assert _item(data, "roller")["included"]


def test_customer_can_add_and_remove_their_own_products(auth_client, paints):
    project = _start(auth_client, description=ROOM).json()
    extra_variant = paints["putty_v"][0]
    response = auth_client.post(
        f"{URL}{project['id']}/items/", {"variant_id": extra_variant.pk, "quantity": 2}, format="json"
    )
    assert response.status_code == 201
    extra = next(i for i in response.json()["kit"]["items"] if i["added_by_customer"])
    assert extra["quantity"] == 2 and extra["included"]
    suggested = _item(response.json(), "primer")
    response = auth_client.delete(f"{URL}{project['id']}/items/{suggested['id']}/")
    assert response.status_code == 400 and response.json()["error"]["code"] == "suggested_item"
    data = auth_client.delete(f"{URL}{project['id']}/items/{extra['id']}/").json()
    assert not any(i["added_by_customer"] for i in data["kit"]["items"])
    assert auth_client.post(f"{URL}{project['id']}/items/", {"variant_id": 999999}, format="json").status_code == 400


def test_add_to_cart_is_all_or_nothing(auth_client, user, paints):
    data = _start(auth_client, description=ROOM).json()
    emulsion = _item(data, "emulsion")
    url = f"{URL}{data['id']}/"
    # more than in stock: shown before adding, and nothing is added
    data = auth_client.patch(f"{url}items/{emulsion['id']}/", {"quantity": 45}, format="json").json()
    assert _item(data, "emulsion")["problem"] == "short_stock" and not data["kit"]["can_add_to_cart"]
    response = auth_client.post(f"{url}add-to-cart/")
    assert response.status_code == 400 and response.json()["error"]["code"] == "project_not_addable"
    assert not CartItem.objects.filter(cart__user=user).exists()

    auth_client.patch(f"{url}items/{emulsion['id']}/", {"quantity": 2}, format="json")
    add_item(user, paints["roller_v"][0].pk, 1)
    response = auth_client.post(f"{url}add-to-cart/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ordered" and body["added"]["added_lines"] == body["kit"]["included_count"]
    cart = {c.variant_id: c.quantity for c in CartItem.objects.filter(cart__user=user)}
    assert cart[paints["emulsion_v"][0].pk] == 2
    assert cart[paints["roller_v"][0].pk] == 2  # already had one: quantities add up


def test_delivery_is_checked_for_the_pin(auth_client, paints):
    data = _start(auth_client, description=ROOM).json()
    data = auth_client.get(f"{URL}{data['id']}/", {"postal_code": "110001"}).json()
    assert data["kit"]["postal_code"] == "110001" and not data["kit"]["delivery"]["available"]
    assert [i["code"] for i in data["kit"]["issues"]] == ["not_deliverable"] and not data["kit"]["can_add_to_cart"]
    unchecked = auth_client.get(f"{URL}{data['id']}/").json()  # no PIN, no saved address
    assert not unchecked["kit"]["delivery"]["checked"]


def test_unavailable_products_are_flagged_live(auth_client, paints):
    data = _start(auth_client, description=ROOM).json()
    product = paints["emulsion"]
    product.is_published = False
    product.save()
    data = auth_client.get(f"{URL}{data['id']}/").json()
    assert _item(data, "emulsion")["problem"] == "unavailable"
    assert {"item_id": _item(data, "emulsion")["id"], "code": "unavailable"}.items() <= data["kit"]["issues"][0].items()


def test_hindi_description_gives_a_hindi_plan(auth_client, paints):
    data = _start(auth_client, description="मेरे 10x12 कमरे की पुताई करनी है, दीवारें अच्छी हैं").json()
    assert data["language"] == "hi" and data["type_name"] == "पुताई / पेंटिंग"
    assert data["missing"] == ["condition"]  # "अच्छी" alone isn't a condition the template knows
    data = auth_client.patch(f"{URL}{data['id']}/", {"answers": {"condition": "good"}}, format="json").json()
    assert _item(data, "primer")["label"] == "वॉल प्राइमर"


def test_projects_are_private(auth_client, other_user, api_client, paints):
    project = _start(auth_client, description=ROOM).json()
    api_client.force_authenticate(other_user)
    assert api_client.get(f"{URL}{project['id']}/").status_code == 404
    assert api_client.post(f"{URL}{project['id']}/add-to-cart/").status_code == 404
    assert api_client.get(URL).json()["count"] == 0
    api_client.force_authenticate(None)
    assert api_client.get(URL).status_code == 401
    assert api_client.post(URL, {"description": ROOM}, format="json").status_code == 401
    listing = auth_client.get(URL).json()
    assert listing["count"] == 1 and listing["results"][0]["item_count"] > 0
    assert auth_client.delete(f"{URL}{project['id']}/").status_code == 204


def test_project_types_are_public(api_client, db):
    data = api_client.get(TYPES, {"language": "hinglish"}).json()
    keys = [row["key"] for row in data["results"]]
    assert keys == list(TEMPLATES) and data["results"][0]["first_question"]["text"]


def test_professional_advice_for_risky_jobs(auth_client, db):
    data = _start(auth_client, description="new wiring 6 points 40 m").json()
    assert data["complete"] and data["professional"] and any("electrician" in s for s in data["safety"])
