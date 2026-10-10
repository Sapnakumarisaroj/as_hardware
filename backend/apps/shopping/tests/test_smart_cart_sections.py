"""Smart cart and frequently bought together, extended: co-purchase ranking (window, support, lift, demo/real never
mixed), "customers also bought", cheaper alternatives that never cross a defining specification, pack-size savings
from the pricing engine, relevant free-delivery add-ons that close the gap, department "needed with" rules, complete
the set (admin bundles and project kits, only with two items already in the cart), de-duplication across sections
and empty sections hidden."""

from decimal import Decimal

from apps.carts.models import CartItem
from apps.carts.services import add_item
from apps.catalog.models import ProductSpecification
from apps.catalog.services import set_accessories
from apps.catalog.tests.test_compatibility import hw  # noqa: F401 — the shared catalogue fixture
from apps.core.testing import add_stock, create_category, create_product
from apps.inventory.models import Inventory
from apps.orders.pricing import line_from_variant
from apps.shopping.services.recommendations import RecommendationService, co_purchased

from .test_shopping import CART, order, section

D = Decimal


def spec(product, name, value, unit=""):
    ProductSpecification.objects.create(product=product, name=name, value=value, unit=unit)


def sections(data) -> dict:
    return {s["key"]: s for s in data["sections"]}


def suggested_products(data) -> list[int]:
    """Products put in front of the customer by the suggestion sections (not the cart's own lines)."""
    out = []
    for s in data["sections"]:
        if s["key"] in ("warnings", "offers", "budget"):
            continue
        for item in s["items"]:
            if item.get("lines"):
                out += [line["product_id"] for line in item["lines"]]
            elif item.get("bundle"):
                out += item["bundle"]["missing"]
            elif item.get("action") in ("add", "replace") and item.get("type") != "pack_size":
                out.append(item["product_id"])
    return out


# --- Frequently bought together ----------------------------------------------------------------------------


def test_co_purchases_rank_by_lift_with_minimum_support_and_a_window(hw, user, other_user):  # noqa: F811
    order(user, hw["impact"], hw["hammer"], hw["bulb"], hw["wire"])
    order(other_user, hw["impact"], hw["hammer"], hw["bulb"])
    order(user, hw["impact"], hw["hammer"])
    for _ in range(4):
        order(other_user, hw["hammer"])  # the hammer sells in every order: popular, but not *with* the drill
    order(user, hw["impact"], hw["mcb"], days_ago=400)  # outside the 180-day window
    order(other_user, hw["impact"], hw["mcb"], days_ago=400)
    order(user, hw["impact"], hw["mcb"], status="cancelled")
    rows = co_purchased(hw["impact"].pk)
    # bulb: 2 of the drill's 3 orders, in 2 of 7 orders overall → lift 2.33; hammer: 3 of 3 but in all 7 → lift 1
    assert [r.product_id for r in rows] == [hw["bulb"].pk, hw["hammer"].pk]
    assert rows[0].together == 2 and rows[0].lift > rows[1].lift and rows[1].confidence == 1.0
    assert hw["wire"].pk not in [r.product_id for r in rows]  # once together: below the support of 2
    assert hw["mcb"].pk not in [r.product_id for r in rows]  # old and cancelled orders don't count
    assert hw["impact"].pk not in [r.product_id for r in rows]  # never itself


def test_co_purchases_skip_unsellable_and_never_mix_demo_and_real(hw, user, other_user):  # noqa: F811
    demo_torch, _ = create_product(name="Demo Torch", category=hw["tools"], stock=10, is_demo=True)
    demo_drill, _ = create_product(name="Demo Drill Kit", category=hw["tools"], stock=10, is_demo=True)
    for buyer in (user, other_user):
        order(buyer, hw["impact"], hw["hammer"], hw["bulb"], demo_torch)
        order(buyer, demo_drill, demo_torch, hw["hammer"])
    real = [r.product_id for r in co_purchased(hw["impact"].pk)]
    assert demo_torch.pk not in real and hw["hammer"].pk in real
    assert [r.product_id for r in co_purchased(demo_drill.pk)] == [demo_torch.pk]  # a demo anchor: demo only
    Inventory.objects.filter(variant__product=hw["bulb"]).update(available_quantity=0)
    hw["hammer"].is_published = False
    hw["hammer"].save()
    assert co_purchased(hw["impact"].pk) == []  # out of stock / unpublished: not suggested
    # the product page falls back to the shop's "goes with" links
    set_accessories(hw["impact"], [{"product": hw["wire"].pk, "kind": "accessory", "note": "Often taken"}])
    rows = RecommendationService().for_product(hw["impact"].pk)["groups"]["frequently_bought_together"]
    assert [r["product_id"] for r in rows] == [hw["wire"].pk] and rows[0]["reason"] == "Often taken"


def test_customers_also_bought_in_the_cart(hw, user, other_user, auth_client):  # noqa: F811
    for buyer in (user, other_user):
        order(buyer, hw["bulb"], hw["wire"])
    add_item(user, hw["bulb"].variants.first().pk, 1)
    data = auth_client.get(CART).json()
    [row] = section(data, "also_bought")["items"]
    assert row["product_id"] == hw["wire"].pk and row["action"] == "add" and row["orders"] == 2
    assert row["reason"].startswith("Bought together in 2 orders") and "LED Bulb 9W" in row["message"]
    add_item(user, hw["wire"].variants.first().pk, 1)
    assert section(auth_client.get(CART).json(), "also_bought") is None  # already in the cart: hidden


# --- Cheaper alternatives by specification -----------------------------------------------------------------


def test_cheaper_alternative_never_crosses_a_defining_specification(hw, user, auth_client):  # noqa: F811
    boards = create_category("Boards")
    ply, ply_v = create_product(name="BWP Plywood 18 mm", category=boards, price="2000.00", mrp="2400.00", stock=20)
    same, same_v = create_product(name="Economy Plywood 18", category=boards, price="1600.00", mrp="2000.00", stock=20)
    thinner, _ = create_product(name="Thin Plywood", category=boards, price="900.00", mrp="1000.00", stock=20)
    other_grade, _ = create_product(name="MR Plywood 18", category=boards, price="1000.00", mrp="1200.00", stock=20)
    unstated, _ = create_product(name="Plywood Sheet", category=boards, price="800.00", mrp="1000.00", stock=20)
    for product, thickness, grade in (
        (ply, "18", "BWP"),
        (same, "18", "BWP"),
        (thinner, "12", "BWP"),
        (other_grade, "18", "MR"),
    ):
        spec(product, "Thickness", thickness, "mm")
        spec(product, "Grade", grade)
        spec(product, "Warranty", "1 year" if product is ply else "5 years")  # descriptive: may differ
    spec(unstated, "Thickness", "18", "mm")  # no grade stated: can't be judged the same
    add_item(user, ply_v.pk, 2)
    [alt] = section(auth_client.get(CART).json(), "alternatives")["items"]
    assert alt["product_id"] == same.pk and alt["action"] == "replace" and alt["quantity"] == 2
    expected = line_from_variant(ply_v, 2).line_total - line_from_variant(same_v, 2).line_total
    assert D(alt["saving"]) == expected == D("800.00")
    assert "Thickness 18 mm, Grade BWP" in alt["message"] and "the same thickness, grade" in alt["reason"]


def test_no_alternative_without_defining_specifications_or_stock(hw, user, auth_client):  # noqa: F811
    boards = create_category("Boards")
    ply, ply_v = create_product(name="Acrylic Sheet A", category=boards, price="2000.00", mrp="2400.00", stock=20)
    cheap, _ = create_product(name="Acrylic Sheet B", category=boards, price="1000.00", mrp="1200.00", stock=1)
    add_item(user, ply_v.pk, 2)
    assert section(auth_client.get(CART).json(), "alternatives") is None  # nothing states what the product is
    spec(ply, "Thickness", "18", "mm")
    spec(cheap, "Thickness", "18", "mm")
    assert section(auth_client.get(CART).json(), "alternatives") is None  # 1 in stock, 2 needed


# --- Pack sizes ----------------------------------------------------------------------------------------------


def test_pack_size_saving_is_the_engines_difference(hw, user, auth_client):  # noqa: F811
    nails, single = create_product(name="Steel Nails", category=hw["fixings"], price="3.00", mrp="4.00", stock=500)
    single.name = "Single"
    single.save()
    box = nails.variants.create(sku=f"{nails.sku}-B50", name="Box of 50", price=D("90.00"), mrp=D("120.00"))
    other = nails.variants.create(sku=f"{nails.sku}-B100", name="Box of 100 (3 inch)", price=D("50.00"), mrp=D("60.00"))
    add_stock(box, 20)
    add_stock(other, 20)
    add_item(user, single.pk, 40)
    [row] = section(auth_client.get(CART).json(), "packs")["items"]
    assert (
        row["type"] == "pack_size"
        and row["action"] == "replace"
        and row["variant_id"] == box.pk
        and row["quantity"] == 1
    )
    assert (
        D(row["saving"]) == line_from_variant(single, 40).line_total - line_from_variant(box, 1).line_total == D("30")
    )
    # never the cheaper 3 inch box: another item, not another pack of this one
    assert "1 × 50 pcs costs ₹90 instead of ₹120 for 40 × Single" in row["message"]


def test_no_pack_suggestion_when_the_cart_line_is_already_cheapest(hw, user, auth_client):  # noqa: F811
    glue, one = create_product(
        name="Wood Glue", category=hw["fixings"], price="300.00", mrp="350.00", stock=50, unit="kg"
    )
    one.name = "1 kg"
    one.save()
    five = glue.variants.create(sku=f"{glue.sku}-5", name="5 kg", price=D("1200.00"), mrp=D("1500.00"))
    add_stock(five, 10)
    add_item(user, one.pk, 3)  # 3 × 1 kg = ₹900 < 1 × 5 kg = ₹1,200
    assert section(auth_client.get(CART).json(), "packs") is None
    item = glue.variants.get(pk=one.pk)
    CartItem.objects.filter(cart__user=user, variant=item).update(quantity=5)  # 5 × 1 kg = ₹1,500
    [row] = section(auth_client.get(CART).json(), "packs")["items"]
    assert row["variant_id"] == five.pk and D(row["saving"]) == D("300.00")


# --- Free delivery ---------------------------------------------------------------------------------------------


def test_free_delivery_add_ons_are_relevant_and_close_the_gap(hw, user, auth_client, settings):  # noqa: F811
    settings.DELIVERY_FEE = D("40.00")
    settings.FREE_DELIVERY_MIN_ORDER = D("1500.00")
    add_item(user, hw["hammer"].variants.first().pk, 1)  # a tool: ₹900, ₹600 short
    free = section(auth_client.get(CART).json(), "free_delivery")["items"]
    gap = D(free[0]["gap"])
    assert free[0]["type"] == "free_delivery" and gap > 0 and len(free) >= 2
    tools = set(hw["tools"].products.values_list("pk", flat=True))
    for item in free[1:]:
        assert item["product_id"] in tools  # same department, never the unrelated electrical or plumbing products
        assert D(item["price"]["line_total"]) >= gap and item["closes_gap"] and item["reason"]


def test_free_delivery_hidden_when_nothing_relevant_closes_the_gap(hw, user, auth_client, settings):  # noqa: F811
    settings.DELIVERY_FEE = D("40.00")
    settings.FREE_DELIVERY_MIN_ORDER = D("50000.00")  # no sensible add-on reaches it
    add_item(user, hw["hammer"].variants.first().pk, 1)
    assert section(auth_client.get(CART).json(), "free_delivery") is None


# --- Needed with it ---------------------------------------------------------------------------------------------


def test_department_rules_suggest_what_a_line_needs(hw, user, auth_client):  # noqa: F811
    furniture = create_category("Furniture Fittings")
    hinge, hinge_v = create_product(name="Soft Close Hinge", category=furniture, price="120.00", mrp="150.00", stock=40)
    create_product(name="Hinge Screws 16 mm", category=hw["fixings"], price="40.00", mrp="50.00", stock=40)
    add_item(user, hinge_v.pk, 4)
    needed = section(auth_client.get(CART).json(), "needed_with")["items"]
    assert [i["product_id"] for i in needed][:1] and "Hinges are fixed with screws." in needed[0]["message"]
    picked = needed[0]["product_id"]
    assert picked != hinge.pk
    # the cart already has screws: the rule is satisfied, nothing to add
    add_item(user, hw["screw_v"][0].pk, 10)
    needed = section(auth_client.get(CART).json(), "needed_with")
    assert needed is None or all("Hinges are fixed" not in i["message"] for i in needed["items"])


def test_shop_links_win_over_the_rules_and_unrelated_lines_get_nothing(hw, user, auth_client):  # noqa: F811
    furniture = create_category("Furniture Fittings")
    hinge, hinge_v = create_product(name="Soft Close Hinge", category=furniture, price="120.00", mrp="150.00", stock=40)
    create_product(name="Hinge Screws 16 mm", category=hw["fixings"], price="40.00", mrp="50.00", stock=40)
    set_accessories(hinge, [{"product": hw["hammer"].pk, "kind": "required", "note": "to tap it in"}])
    add_item(user, hinge_v.pk, 1)
    needed = section(auth_client.get(CART).json(), "needed_with")["items"]
    assert [i["product_id"] for i in needed] == [hw["hammer"].pk]  # the shop said what it needs
    assert needed[0]["reason"] == "The shop lists it as needed with this product."
    CartItem.objects.filter(cart__user=user).delete()
    add_item(user, hw["bulb"].variants.first().pk, 1)  # no rule for a bulb
    assert section(auth_client.get(CART).json(), "needed_with") is None


# --- Complete the set -----------------------------------------------------------------------------------------


def test_project_kit_completion_needs_two_materials_in_the_cart(hw, user, auth_client):  # noqa: F811
    add_item(user, hw["plugs6"].variants.first().pk, 1)
    data = auth_client.get(CART).json()
    assert section(data, "bundles") is None  # one material of the wall-drilling kit: not a partial match yet
    add_item(user, hw["screw_v"][0].pk, 1)
    kits = [i for i in section(auth_client.get(CART).json(), "bundles")["items"] if i["type"] == "complete_kit"]
    [drilling] = [k for k in kits if k["kit"]["key"] == "wall_drilling"]
    [line] = drilling["lines"]
    assert line["product_id"] == hw["masonry"].pk and line["quantity"] == 1 and drilling["action"] == "add_lines"
    masonry = hw["masonry"].variants.first()
    assert D(drilling["total"]) == line_from_variant(masonry, 1).line_total == D(line["line_total"])
    assert drilling["reason"].startswith("You have 2 of the 3 materials")


# --- Every section ---------------------------------------------------------------------------------------------


def test_a_product_appears_in_one_section_at_most(hw, user, other_user, auth_client, settings):  # noqa: F811
    settings.DELIVERY_FEE = D("40.00")
    settings.FREE_DELIVERY_MIN_ORDER = D("4000.00")
    for buyer in (user, other_user):
        order(buyer, hw["impact"], hw["masonry"], hw["hss"], hw["hammer"])
    set_accessories(hw["impact"], [{"product": hw["hss"].pk, "kind": "accessory"}])
    add_item(user, hw["impact"].variants.first().pk, 1)
    data = auth_client.get(CART).json()
    shown = suggested_products(data)
    assert shown and len(shown) == len(set(shown))
    assert hw["impact"].pk not in shown  # never what the cart already has
    for s in data["sections"]:
        assert s["items"]  # no empty section
        assert len(s["items"]) <= (10 if s["key"] == "warnings" else 4)
        for item in s["items"]:
            assert item.get("reason") or s["key"] == "budget"
