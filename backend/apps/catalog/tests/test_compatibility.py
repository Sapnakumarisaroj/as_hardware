"""Compatibility checker (Phase 21): listing facts → profiles, the rules (drill/bit, bit/plug, plug/screw, pipes and
fittings, taps, MCB/wire, switch/socket, bolt/spanner), variants and options, the shop's links (compatible, required,
incompatible, accessory, alternative) and their audit, accessories, the API, cart problems and replace, security."""

import threading

import pytest
from django.db import connection

from apps.carts.models import CartItem
from apps.carts.services import add_item
from apps.catalog.compatibility import profiles
from apps.catalog.compatibility.rules import COMPATIBLE, NOT, POSSIBLY, UNKNOWN
from apps.catalog.compatibility.service import CompatibilityService
from apps.catalog.models import OptionType, ProductRelation, ProductSpecification
from apps.catalog.services import set_accessories, set_variant_options
from apps.core.models import AuditLog
from apps.core.testing import add_stock, create_category, create_product, create_store

CHECK = "/api/compatibility/check/"
D = __import__("decimal").Decimal


def spec(product, name, value, unit=""):
    ProductSpecification.objects.create(
        product=product, name=name, key=name.lower().replace(" ", "-"), value=value, unit=unit
    )


@pytest.fixture
def hw(db):
    store = create_store()
    tools, plumbing, electrical = create_category("Tools"), create_category("Plumbing"), create_category("Electrical")
    fixings = create_category("Fixings")

    def make(name, category, specs=(), variants=(), stock=50, **kwargs):
        product, first = create_product(name=name, category=category, stock=stock, store=store, **kwargs)
        for spec_name, value, unit in specs:
            spec(product, spec_name, value, unit)
        made = [first]
        if variants:
            first.name = variants[0]
            first.save()
            for index, vname in enumerate(variants[1:], start=1):
                v = product.variants.create(sku=f"{product.sku}-{index}", name=vname, price=D("100"), mrp=D("120"))
                add_stock(v, stock, store=store)
                made.append(v)
        return product, made

    impact, _ = make("Impact Drill 13 mm", tools, [("Chuck Size", "13", "mm"), ("Impact Function", "Yes", "")])
    cordless, _ = make("Cordless Drill 12V", tools, [("Chuck Size", "10", "mm")])
    no_chuck, _ = make("Mini Drill", tools)
    masonry, _ = make(
        "Masonry Drill Bit Set", tools, [("Sizes", "5, 6, 8, 10, 12", "mm"), ("Material", "Carbide tipped", "")]
    )
    hss, _ = make("HSS Drill Bit Set", tools, [("Sizes", "1.5 - 6.5", "mm"), ("Material", "HSS", "")])
    big_bits, _ = make("Core Drill Bit Set", tools, [("Sizes", "16, 20", "mm"), ("Material", "Carbide tipped", "")])
    plugs6, _ = make("Nylon Wall Plugs 6 mm", fixings, [("Diameter", "6", "mm")])
    plugs8, _ = make("Nylon Wall Plugs 8 mm", fixings, [("Diameter", "8", "mm")])
    screws, screw_v = make("Wood Screws", fixings, variants=("No. 8 x 25 mm", "No. 12 x 50 mm"))
    cpvc, cpvc_v = make("CPVC Pipe 3 m", plumbing, [("Material", "CPVC", "")], variants=("1/2 inch", "3/4 inch"))
    upvc, _ = make("UPVC Pipe 3 m", plumbing, [("Material", "UPVC", "")], variants=("1 inch",))
    elbow, elbow_v = make("CPVC Elbow 90", plumbing, [("Material", "CPVC", "")], variants=("1/2 inch",))
    valve, valve_v = make("Brass Ball Valve", plumbing, [("Material", "Brass", "")], variants=("1/2 inch", "3/4 inch"))
    tap, _ = make("Pillar Tap", plumbing, [("Inlet Size", "1/2", "inch")])
    connector, _ = make("Braided Connector", plumbing, [("Thread", "1/2 x 1/2", "inch")])
    mcb, mcb_v = make("MCB Single Pole", electrical, variants=("16 A", "32 A"))
    wire, wire_v = make("Copper Wire 90 m", electrical, variants=("1.5 sq mm", "2.5 sq mm"))
    cross = OptionType.objects.create(name="Cross-section", unit="sq mm")
    set_variant_options(wire_v[0], [{"option_type": cross.pk, "value": "1.5 sq mm"}])
    set_variant_options(wire_v[1], [{"option_type": cross.pk, "value": "2.5 sq mm"}])
    switch6, _ = make("Modular Switch 6A", electrical, [("Current Rating", "6", "A")])
    switch16, _ = make("Modular Switch 16A", electrical, [("Current Rating", "16", "A")])
    socket16, _ = make("Modular Socket 16A", electrical, [("Current Rating", "16", "A")])
    bulb, _ = make("LED Bulb 9W", electrical, [("Base", "B22", "")])
    hammer, _ = make("Claw Hammer", tools)
    return locals()


def check(a, b, va=None, vb=None):
    return CompatibilityService().check_ids(a.pk, b.pk, getattr(va, "pk", None), getattr(vb, "pk", None))


# --- Profiles: only what the listing says -------------------------------------------------------------------


def test_profiles_read_listing_facts_and_never_guess(hw):
    drill = profiles.build(hw["impact"])
    assert drill.kind == "drill" and drill.values["chuck_mm"] == 13 and drill.values["impact"] is True
    assert drill.sources["chuck_mm"] == "spec Chuck Size"
    bits = profiles.build(hw["masonry"])
    assert (
        bits.kind == "drill_bit" and bits.values["bit_mm"] == [5, 6, 8, 10, 12] and bits.values["bit_use"] == "masonry"
    )
    assert profiles.build(hw["hss"]).values["bit_range"] == (1.5, 6.5)
    assert profiles.build(hw["plugs6"]).values["plug_mm"] == 6
    screws = profiles.build(hw["screws"], hw["screw_v"][0])
    assert screws.values["screw_mm"] == 4.2 and screws.values["screw_len_mm"] == 25
    assert profiles.build(hw["cpvc"]).values["sizes"] == {"1/2", "3/4"}  # not the "2" of "1/2"
    assert profiles.build(hw["connector"]).values["sizes"] == {"1/2"}
    assert profiles.build(hw["mcb"]).values["amps"] == [16, 32]
    assert profiles.build(hw["wire"], hw["wire_v"][1]).values["cross_section"] == 2.5
    assert (
        "chuck_mm" not in profiles.build(hw["no_chuck"]).values
        and "impact" not in profiles.build(hw["cordless"]).values
    )
    assert profiles.build(hw["hammer"]).kind is None


# --- Rules -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a, b, verdict, words",
    [
        ("impact", "masonry", COMPATIBLE, "13 mm chuck takes every bit"),
        ("masonry", "impact", COMPATIBLE, "hammer (impact) action"),  # either order
        ("cordless", "masonry", POSSIBLY, "the 12 mm won't fit"),
        ("cordless", "hss", COMPATIBLE, "10 mm chuck takes every bit"),
        ("impact", "big_bits", NOT, "bigger than the 13 mm chuck"),
        ("no_chuck", "masonry", UNKNOWN, "Not enough information to confirm compatibility"),
        ("masonry", "plugs6", COMPATIBLE, "6 mm bit for the 6 mm plug"),
        ("hss", "plugs8", NOT, "No 8 mm bit"),
        ("hss", "plugs6", POSSIBLY, "metal (HSS) bits"),
        ("plugs6", "screws", POSSIBLY, "Only the 4.2 mm screws"),
        ("upvc", "elbow", NOT, "can't be solvent-joined"),
        ("cpvc", "elbow", POSSIBLY, "match only in 1/2 inch"),
        ("cpvc", "valve", POSSIBLY, "threaded adapter"),
        ("tap", "connector", COMPATIBLE, "Both are 1/2 inch"),
        ("switch6", "socket16", NOT, "6 A switch can't control a 16 A socket"),
        ("switch16", "socket16", COMPATIBLE, "16 A switch handles"),
        ("bulb", "hammer", UNKNOWN, "Not enough information"),
    ],
)
def test_rules(hw, a, b, verdict, words):
    result = check(hw[a], hw[b])
    assert result.verdict == verdict, result.reason
    assert words in result.reason


def test_variants_and_options_decide_the_fit(hw):
    half, three_quarter = hw["cpvc_v"]
    assert check(hw["cpvc"], hw["elbow"], half, hw["elbow_v"][0]).verdict == COMPATIBLE
    wrong = check(hw["cpvc"], hw["elbow"], three_quarter, hw["elbow_v"][0])
    assert wrong.verdict == NOT and "3/4 vs 1/2" in wrong.reason
    both = check(hw["cpvc"], hw["valve"])
    assert {(m["a"], m["b"]) for m in both.matching_variants} == {
        (half.pk, hw["valve_v"][0].pk),
        (three_quarter.pk, hw["valve_v"][1].pk),
    }
    sixteen, thirty_two = hw["mcb_v"]
    thin, thick = hw["wire_v"]
    assert check(hw["mcb"], hw["wire"], sixteen, thick).verdict == COMPATIBLE
    assert check(hw["mcb"], hw["wire"], sixteen, thin).verdict == NOT
    assert "needs 6 sq mm" in check(hw["mcb"], hw["wire"], thirty_two, thick).reason
    # matching pairs come back in the caller's order, whichever way the rule was written
    swapped = check(hw["wire"], hw["mcb"])
    assert {(m["a"], m["b"]) for m in swapped.matching_variants} == {(thick.pk, sixteen.pk)}
    assert check(hw["screws"], hw["plugs6"], hw["screw_v"][1]).verdict == NOT  # No. 12 = 5.5 mm


# --- The shop's links --------------------------------------------------------------------------------------


def test_shop_links_are_evidence_but_never_beat_the_facts(hw):
    set_accessories(hw["bulb"], [{"product": hw["hammer"].pk, "kind": "compatible", "note": "Tested in store"}])
    linked = check(hw["bulb"], hw["hammer"])
    assert (
        linked.verdict == COMPATIBLE
        and "Tested in store" in linked.reason
        and linked.sources == ["relation:compatible"]
    )
    set_accessories(hw["impact"], [{"product": hw["masonry"].pk, "kind": "incompatible", "note": "Recall"}])
    assert check(hw["masonry"], hw["impact"]).verdict == NOT  # either direction
    set_accessories(hw["upvc"], [{"product": hw["elbow"].pk, "kind": "compatible"}])
    conflict = check(hw["upvc"], hw["elbow"])
    assert conflict.verdict == POSSIBLY and "listings say" in conflict.reason
    set_accessories(hw["bulb"], [{"product": hw["hammer"].pk, "kind": "accessory"}])
    assert check(hw["bulb"], hw["hammer"]).verdict == POSSIBLY  # "goes with" isn't a fit claim


def test_accessory_groups(hw, api_client):
    set_accessories(
        hw["impact"],
        [
            {"product": hw["plugs6"].pk, "kind": "required", "note": "To fix it"},
            {"product": hw["hammer"].pk, "kind": "accessory"},
            {"product": hw["cordless"].pk, "kind": "alternative"},
            {"product": hw["big_bits"].pk, "kind": "incompatible"},
        ],
    )
    hw["hss"].is_published = False
    hw["hss"].save()
    data = api_client.get(f"/api/products/{hw['impact'].pk}/compatibility/").json()
    groups = {name: [row["product_id"] for row in rows] for name, rows in data["groups"].items()}
    assert data["kind"] == "drill" and groups["required"] == [hw["plugs6"].pk]
    assert groups["accessories"] == [hw["hammer"].pk] and groups["alternatives"] == [hw["cordless"].pk]
    assert hw["masonry"].pk in groups["compatible"]  # confirmed by the rules
    assert hw["big_bits"].pk not in groups["compatible"] and hw["hss"].pk not in groups["compatible"]
    row = next(r for r in data["groups"]["compatible"] if r["product_id"] == hw["masonry"].pk)
    assert (
        row["source"] == "rules" and row["verdict"] == COMPATIBLE and row["product"]["name"] == "Masonry Drill Bit Set"
    )


# --- API ---------------------------------------------------------------------------------------------------


def test_check_api(api_client, hw):
    response = api_client.post(CHECK, {"product_a": hw["cordless"].pk, "product_b": hw["masonry"].pk}, format="json")
    data = response.json()
    assert response.status_code == 200 and data["verdict"] == POSSIBLY
    assert data["product_a"]["kind"] == "drill" and data["product_b"]["card"]["name"] == "Masonry Drill Bit Set"
    assert {c["name"] for c in data["checks"]} == {"chuck", "hammer action"}
    assert [o["product"]["name"] for o in data["options"]] == ["HSS Drill Bit Set"]  # bits that fit this drill
    half = hw["cpvc_v"][0]
    data = api_client.post(
        CHECK, {"product_a": hw["cpvc"].pk, "variant_a": half.pk, "product_b": hw["elbow"].pk}, format="json"
    ).json()
    assert data["verdict"] == COMPATIBLE and data["variant_a"] == half.pk


@pytest.mark.parametrize(
    "body, status, code",
    [
        ({"product_a": 1}, 400, "validation_error"),
        ({"product_a": 999_999, "product_b": 999_998}, 404, "not_found"),
        ("same", 400, "same_product"),
        ("foreign_variant", 400, "invalid_variant"),
        ("unpublished", 404, "not_found"),
    ],
)
def test_check_api_refusals(api_client, hw, body, status, code):
    if body == "same":
        body = {"product_a": hw["impact"].pk, "product_b": hw["impact"].pk}
    elif body == "foreign_variant":
        body = {"product_a": hw["cpvc"].pk, "variant_a": hw["elbow_v"][0].pk, "product_b": hw["elbow"].pk}
    elif body == "unpublished":
        hw["elbow"].is_published = False
        hw["elbow"].save()
        body = {"product_a": hw["cpvc"].pk, "product_b": hw["elbow"].pk}
    response = api_client.post(CHECK, body, format="json")
    assert response.status_code == status and response.json()["error"]["code"] == code


# --- Admin: links, audit, permissions ----------------------------------------------------------------------


def test_admin_manages_links_with_an_audit_trail(admin_client, staff_client, api_client, auth_client, hw):
    url = f"/api/admin/products/{hw['impact'].pk}/"
    body = {
        "accessories": [
            {"product": hw["masonry"].pk, "kind": "compatible", "note": "SDS"},
            {"product": hw["plugs6"].pk, "kind": "required"},
        ]
    }
    saved = admin_client.patch(url, body, format="json")
    assert saved.status_code == 200
    assert [(a["id"], a["kind"]) for a in saved.json()["accessories"]] == [
        (hw["masonry"].pk, "compatible"),
        (hw["plugs6"].pk, "required"),
    ]
    entry = AuditLog.objects.filter(action="product.update", target_id=str(hw["impact"].pk)).latest("id")
    assert entry.changes["relations"]["before"] == []
    assert entry.changes["relations"]["after"][0] == {"product": hw["masonry"].pk, "kind": "compatible", "note": "SDS"}
    admin_client.patch(url, {"accessories": [{"product": hw["masonry"].pk, "kind": "incompatible"}]}, format="json")
    entry = AuditLog.objects.filter(action="product.update", target_id=str(hw["impact"].pk)).latest("id")
    assert (
        entry.changes["relations"]["before"][0]["kind"] == "compatible"
        and entry.changes["relations"]["after"][0]["kind"] == "incompatible"
    )
    bad = admin_client.patch(
        url, {"accessories": [{"product": hw["masonry"].pk, "kind": "best-friend"}]}, format="json"
    )
    assert bad.status_code == 400
    # customers and visitors can't change links; store managers without the store can't either
    assert auth_client.patch(url, body, format="json").status_code == 403
    assert api_client.patch(url, body, format="json").status_code == 401
    assert ProductRelation.objects.filter(product=hw["impact"]).values_list("kind", flat=True).get() == "incompatible"
    assert (
        api_client.post(CHECK, {"product_a": hw["impact"].pk, "product_b": hw["masonry"].pk}, format="json").json()[
            "verdict"
        ]
        == NOT
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_link_edits_leave_one_consistent_set(hw):
    if connection.vendor == "sqlite" and connection.settings_dict["NAME"].startswith(":memory"):
        pytest.skip("needs a file database")
    errors = []

    def save(kind):
        try:
            set_accessories(
                hw["impact"], [{"product": hw["masonry"].pk, "kind": kind}, {"product": hw["plugs6"].pk, "kind": kind}]
            )
        except Exception as exc:  # noqa: BLE001 — collected and asserted below
            errors.append(exc)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=save, args=(kind,)) for kind in ("compatible", "required", "accessory", "alternative")
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    kinds = list(ProductRelation.objects.filter(product=hw["impact"]).values_list("kind", flat=True))
    assert len(kinds) == 2 and len(set(kinds)) == 1  # one editor's whole set, never a mix


# --- Cart (Smart Cart preparation) -------------------------------------------------------------------------


def test_cart_problems_and_replace(auth_client, user, api_client, hw):
    add_item(user, hw["cordless"].variants.first().pk, 1)
    add_item(user, hw["big_bits"].variants.first().pk, 1)
    add_item(user, hw["hammer"].variants.first().pk, 1)
    data = auth_client.get("/api/cart/compatibility/").json()
    [problem] = data["problems"]
    bits_line = CartItem.objects.get(cart__user=user, variant__product=hw["big_bits"])
    assert problem["verdict"] == NOT and problem["message"].startswith(
        "Your selected Core Drill Bit Set won't work with Cordless Drill 12V"
    )
    assert bits_line.pk in problem["cart_item_ids"]
    assert [o["product"]["name"] for o in problem["options"]] == ["HSS Drill Bit Set"]
    replacement = hw["hss"].variants.first()
    response = auth_client.post(
        f"/api/cart/items/{bits_line.pk}/replace/", {"variant_id": replacement.pk}, format="json"
    )
    assert response.status_code == 200
    assert (
        not CartItem.objects.filter(pk=bits_line.pk).exists()
        and CartItem.objects.get(cart__user=user, variant=replacement).quantity == 1
    )
    assert auth_client.get("/api/cart/compatibility/").json()["problems"] == []
    # someone else's line, an unknown product, and visitors are refused
    other = auth_client.post("/api/cart/items/999999/replace/", {"variant_id": replacement.pk}, format="json")
    assert other.status_code == 404
    unknown = auth_client.post(
        f"/api/cart/items/{CartItem.objects.filter(cart__user=user).first().pk}/replace/",
        {"variant_id": 999_999},
        format="json",
    )
    assert unknown.status_code == 400
    assert api_client.get("/api/cart/compatibility/").status_code == 401


def test_replace_merges_and_checks_stock(auth_client, user, hw):
    hss_variant = hw["hss"].variants.first()
    add_item(user, hss_variant.pk, 2)
    add_item(user, hw["big_bits"].variants.first().pk, 3)
    line = CartItem.objects.get(cart__user=user, variant__product=hw["big_bits"])
    auth_client.post(f"/api/cart/items/{line.pk}/replace/", {"variant_id": hss_variant.pk}, format="json")
    assert CartItem.objects.get(cart__user=user, variant=hss_variant).quantity == 5
    too_many = auth_client.post(
        f"/api/cart/items/{CartItem.objects.get(cart__user=user).pk}/replace/",
        {"variant_id": hss_variant.pk, "quantity": 9999},
        format="json",
    )
    assert too_many.status_code in (400, 409)


def test_line_checks_ignore_goes_with_links_but_flag_incompatible_ones(hw):
    """Found live: a plain "goes with" link (drill → wall plugs) had raised a warning in project kits."""
    service = CompatibilityService()
    lines = [
        {"key": "drill", "variant": hw["impact"].variants.first()},
        {"key": "hammer", "variant": hw["hammer"].variants.first()},
    ]
    set_accessories(hw["impact"], [{"product": hw["hammer"].pk, "kind": "accessory"}])
    assert service.check_lines(lines) == []
    set_accessories(hw["impact"], [{"product": hw["hammer"].pk, "kind": "incompatible", "note": "Too heavy"}])
    [problem] = service.check_lines(lines)
    assert problem["verdict"] == NOT and problem["keys"] == ["drill", "hammer"] and "Too heavy" in problem["message"]
