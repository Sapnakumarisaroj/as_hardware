"""Smart shopping (Phase 22): recommendations (ranking, compatibility, required, alternatives, co-purchases, buy
again, honest home groups), the smart cart (warnings, needed accessories, bulk, free delivery, cheaper equivalents,
bundles, coupons, budget), budget plans (limits, swaps, drops, languages), bundles (pricing, stock, edits, add to
cart), admin management with audit, permissions and edge cases."""

import itertools
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.carts.models import CartItem
from apps.carts.services import add_item
from apps.catalog.services import set_accessories, set_price_tiers
from apps.catalog.tests.test_compatibility import hw  # noqa: F401 — the shared catalogue fixture
from apps.core.models import AuditLog
from apps.core.testing import create_coupon
from apps.offers.models import Offer
from apps.orders.models import Order, OrderItem
from apps.shopping.models import Bundle, BundleItem, RecommendationRule
from apps.shopping.services.budget import budget_from_text
from apps.shopping.services.recommendations import RecommendationService, co_purchased

D = Decimal
REC = "/api/shopping/recommendations/"
CART = "/api/shopping/cart/"
BUDGET = "/api/shopping/budget/"
BUNDLES = "/api/shopping/bundles/"
_numbers = itertools.count(1)


def order(user, *products, status="delivered", days_ago=1):
    money = {"subtotal": 0, "mrp_total": 0, "discount_total": 0, "delivery_fee": 0, "tax_total": 0, "grand_total": 0}
    o = Order.objects.create(
        order_number=f"T22-{next(_numbers)}",
        user=user,
        status=status,
        payment_method="cod",
        address_snapshot={},
        **money,
    )
    Order.objects.filter(pk=o.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    for product in products:
        variant = product.variants.first()
        OrderItem.objects.create(
            order=o,
            variant=variant,
            product=product,
            product_name=product.name,
            sku=variant.sku,
            unit_mrp=variant.mrp,
            unit_price=variant.price,
            gst_rate=D("18"),
            quantity=1,
            line_total=variant.price,
        )
    return o


def groups(data):
    return {name: [row["product_id"] for row in rows] for name, rows in data["groups"].items()}


def section(data, key):
    return next((s for s in data["sections"] if s["key"] == key), None)


# --- Recommendations ---------------------------------------------------------------------------------------


def test_product_recommendations_respect_links_compatibility_and_stock(hw, api_client):  # noqa: F811
    set_accessories(
        hw["impact"],
        [
            {"product": hw["plugs6"].pk, "kind": "required", "note": "To fix it"},
            {"product": hw["hss"].pk, "kind": "accessory"},
            {"product": hw["hammer"].pk, "kind": "accessory", "note": "Handy"},
            {"product": hw["big_bits"].pk, "kind": "incompatible"},
            {"product": hw["cordless"].pk, "kind": "alternative"},
        ],
    )
    data = api_client.get(REC, {"product": hw["impact"].pk}).json()
    g = groups(data)
    assert g["needed_with"] == [hw["plugs6"].pk]
    assert hw["masonry"].pk in g["works_with"] and hw["hss"].pk in g["works_with"]  # rules confirm the accessory link
    assert g["frequently_bought_together"] == [hw["hammer"].pk]  # a plain link the rules can't judge
    assert g["better_alternatives"][0] == hw["cordless"].pk
    everywhere = {pid for rows in g.values() for pid in rows}
    assert (
        hw["big_bits"].pk not in everywhere and hw["impact"].pk not in everywhere
    )  # never the incompatible one, never itself
    assert len(everywhere) == sum(len(rows) for rows in g.values())  # each product appears once
    card = data["groups"]["needed_with"][0]
    assert (
        card["product"]["name"] == "Nylon Wall Plugs 6 mm"
        and card["reason"] == "To fix it"
        and data["titles"]["needed_with"] == "Needed with this"
    )


def test_out_of_stock_and_unpublished_products_are_never_suggested(hw, api_client):  # noqa: F811
    from apps.inventory.models import Inventory

    set_accessories(
        hw["impact"],
        [{"product": hw["plugs6"].pk, "kind": "required"}, {"product": hw["hammer"].pk, "kind": "accessory"}],
    )
    Inventory.objects.filter(variant__product=hw["plugs6"]).update(available_quantity=0)
    hw["hammer"].is_published = False
    hw["hammer"].save()
    g = groups(api_client.get(REC, {"product": hw["impact"].pk}).json())
    everywhere = {pid for rows in g.values() for pid in rows}
    assert hw["plugs6"].pk not in everywhere and hw["hammer"].pk not in everywhere


def test_frequently_bought_together_comes_from_real_orders(hw, user, other_user):  # noqa: F811
    order(user, hw["impact"], hw["hammer"])
    order(other_user, hw["impact"], hw["hammer"], hw["bulb"])
    order(other_user, hw["impact"], hw["bulb"], status="cancelled")  # cancelled orders don't count
    # the bulb was bought with the drill once (support 1 < 2): not "frequently" bought together
    assert [(r.product_id, r.together) for r in co_purchased(hw["impact"].pk)] == [(hw["hammer"].pk, 2)]
    data = RecommendationService().for_product(hw["impact"].pk)
    rows = data["groups"]["frequently_bought_together"]
    assert (
        rows[0]["product_id"] == hw["hammer"].pk
        and rows[0]["reason"] == "Bought together in 2 orders (100% of orders with it)."
        and rows[0]["orders"] == 2
        and rows[0]["confidence"] == 1.0
    )


def test_alternatives_need_the_same_kind_and_say_to_compare(hw):  # noqa: F811
    from apps.catalog import selectors

    hw["cordless"].variants.update(price=D("500"))
    product = selectors.product_queryset().get(pk=hw["impact"].pk)
    [cheaper] = [s for s in RecommendationService().alternatives(product) if s.product_id == hw["cordless"].pk]
    assert cheaper.reason == "Also a drill, ₹400 less. Compare the specifications."
    cement = selectors.product_queryset().get(pk=hw["hammer"].pk)  # no recognised kind
    assert RecommendationService().alternatives(cement) == []


def test_complete_the_project_rules(hw, api_client):  # noqa: F811
    RecommendationRule.objects.create(
        source_category=hw["impact"].category, target_category=hw["bulb"].category, label="Light the room"
    )
    g = api_client.get(REC, {"product": hw["impact"].pk}).json()
    rows = g["groups"]["complete_the_project"]
    assert rows and {r["reason"] for r in rows} == {"Light the room"}


def test_home_groups_are_honest_for_new_and_returning_customers(hw, api_client, auth_client, user):  # noqa: F811
    new = api_client.get(REC).json()
    assert new["personal"] is False and "recommended_for_you" not in new["groups"] and "buy_again" not in new["groups"]
    assert "popular_now" in new["groups"] or "best_value" in new["groups"]
    fresh = auth_client.get(REC).json()
    assert fresh["personal"] is False and "buy_again" not in fresh["groups"]  # signed in, but no history yet
    order(user, hw["hammer"], hw["plugs6"])
    returning = auth_client.get(REC).json()
    assert returning["personal"] is True and set(groups(returning)["buy_again"]) == {hw["hammer"].pk, hw["plugs6"].pk}
    assert returning["groups"]["buy_again"][0]["reason"] == "You ordered this before."


def test_best_for_budget(hw, api_client):  # noqa: F811
    data = api_client.get(REC, {"product": hw["impact"].pk, "budget": "950"}).json()
    rows = data["groups"].get("best_for_budget", [])
    assert all(D(r["product"]["price"]) <= D("950") for r in rows)


# --- Smart cart --------------------------------------------------------------------------------------------


def test_smart_cart_sections_in_value_order(hw, user, auth_client):  # noqa: F811
    set_price_tiers(hw["cpvc_v"][0], [{"min_quantity": 5, "unit_price": "80.00"}])
    add_item(user, hw["cordless"].variants.first().pk, 1)
    add_item(user, hw["masonry"].variants.first().pk, 1)
    add_item(user, hw["plugs6"].variants.first().pk, 2)
    add_item(user, hw["cpvc_v"][0].pk, 3)
    data = auth_client.get(CART).json()
    keys = [s["key"] for s in data["sections"]]
    assert keys[0] == "warnings" and keys.index("needed_with") < keys.index("bulk")
    warning = section(data, "warnings")["items"][0]
    assert warning["type"] == "incompatible" and "may not work" in warning["message"] and warning["action"] == "replace"
    needed = section(data, "needed_with")["items"][0]
    assert needed["product_id"] == hw["screws"].pk and needed["action"] == "add" and "needs screws" in needed["message"]
    bulk = section(data, "bulk")["items"][0]
    assert bulk["quantity"] == 5 and bulk["action"] == "set_quantity"
    assert D(bulk["saving"]) == (hw["cpvc_v"][0].price - D("80.00")) * 5  # 5 at the normal price vs 5 at the tier
    assert data["top_actions"] and data["top_actions"][0]["priority"] >= data["top_actions"][-1]["priority"]
    assert not CartItem.objects.filter(cart__user=user, variant__product=hw["screws"]).exists()  # nothing changed


def test_smart_cart_needed_with_from_the_shops_required_links(hw, user, auth_client):  # noqa: F811
    # found by the query-count test: a required link crashed the smart cart (plain product row, no price annotations)
    set_accessories(hw["impact"], [{"product": hw["hammer"].id, "kind": "required", "note": "to set the plugs"}])
    add_item(user, hw["impact"].variants.first().pk, 1)
    response = auth_client.get(CART)
    assert response.status_code == 200
    needed = section(response.json(), "needed_with")
    [row] = [i for i in needed["items"] if i["product_id"] == hw["hammer"].id]
    assert row["action"] == "add" and row["variant_id"] == hw["hammer"].variants.first().pk
    assert "Needed with" in row["message"] and "to set the plugs" in row["message"]
    assert row["price"]["unit_price"]


def test_smart_cart_duplicates_quantity_mismatch_and_stock(hw, user, auth_client):  # noqa: F811
    from apps.catalog.models import ProductSpecification

    ProductSpecification.objects.create(
        product=hw["plugs6"], name="Pack Size", key="pack-size", value="100", unit="pcs"
    )
    add_item(user, hw["cpvc_v"][0].pk, 1)
    add_item(user, hw["cpvc_v"][1].pk, 1)
    add_item(user, hw["plugs6"].variants.first().pk, 1)  # 100 plugs
    add_item(user, hw["screw_v"][0].pk, 10)  # 10 screws (no pack size listed)
    warnings = section(auth_client.get(CART).json(), "warnings")["items"]
    types = {w["type"] for w in warnings}
    assert {"duplicate", "quantity_mismatch"} <= types
    mismatch = next(w for w in warnings if w["type"] == "quantity_mismatch")
    assert "100 wall plugs but only 10 screws" in mismatch["message"] and mismatch["quantity"] == 100


def test_free_delivery_opportunity_and_coupons(hw, user, auth_client, settings):  # noqa: F811
    settings.DELIVERY_FEE = D("40.00")
    settings.FREE_DELIVERY_MIN_ORDER = D("1500.00")
    create_coupon("SAVE10", show_in_checkout=True)
    add_item(user, hw["hammer"].variants.first().pk, 1)
    data = auth_client.get(CART).json()
    free = section(data, "free_delivery")["items"]
    assert free[0]["type"] == "free_delivery" and D(free[0]["gap"]) > 0 and free[0]["message"].startswith("Add ₹")
    assert all(item["action"] == "add" for item in free[1:])
    coupon = next(i for i in section(data, "offers")["items"] if i["type"] == "coupon")
    assert coupon["code"] == "SAVE10" and coupon["applicable"]


def test_cheaper_equivalent_must_fit_the_rest_of_the_cart(hw, user, auth_client):  # noqa: F811
    from apps.catalog.models import ProductSpecification
    from apps.core.testing import create_product
    from apps.shopping.services.smart_cart import SmartCartService

    hw["cordless"].variants.update(price=D("500"))  # cheaper, but a 10 mm chuck: differs from the 13 mm drill
    budget, _ = create_product(name="Budget Impact Drill", category=hw["tools"], price="700.00", stock=10)
    for name, value, unit in (("Chuck Size", "13", "mm"), ("Impact Function", "Yes", "")):
        ProductSpecification.objects.create(product=budget, name=name, value=value, unit=unit)
    add_item(user, hw["impact"].variants.first().pk, 1)
    add_item(user, hw["masonry"].variants.first().pk, 1)
    alternatives = section(auth_client.get(CART).json(), "alternatives")["items"]
    assert [a["product_id"] for a in alternatives] == [budget.pk]  # never the cordless one: another chuck size
    assert alternatives[0]["action"] == "replace" and "with the same Chuck Size 13 mm" in alternatives[0]["message"]
    assert "fits the rest of your cart" in alternatives[0]["reason"]
    # the fit check: the cordless drill doesn't take the 12 mm masonry bits in the cart as surely as the impact one
    items = list(CartItem.objects.filter(cart__user=user).select_related("variant__product").order_by("id"))
    service = SmartCartService()
    assert service._fits_others(hw["cordless"], items[0], {"items": items}) is False
    assert service._fits_others(budget, items[0], {"items": items}) is True


def test_smart_cart_budget_and_empty_cart(hw, user, auth_client, api_client):  # noqa: F811
    assert auth_client.get(CART).json() == {
        "empty": True,
        "sections": [],
        "top_actions": [],
        "titles": auth_client.get(CART).json()["titles"],
        "summary": None,
    }
    add_item(user, hw["impact"].variants.first().pk, 2)
    over = section(auth_client.get(CART, {"budget": "1000"}).json(), "budget")["items"][0]
    assert over["over"] and over["message"].startswith("₹") and "over your ₹1,000 budget" in over["message"]
    under = section(auth_client.get(CART, {"budget": "99999"}).json(), "budget")["items"][0]
    assert not under["over"] and "left of your" in under["message"]
    assert api_client.get(CART).status_code == 401


def test_bundle_opportunity_in_the_cart(hw, user, auth_client):  # noqa: F811
    bundle = Bundle.objects.create(name="Drilling kit", slug="drilling-kit", kind="drilling")
    BundleItem.objects.create(bundle=bundle, product=hw["impact"], quantity=1)
    BundleItem.objects.create(bundle=bundle, product=hw["hammer"], quantity=1, sort_order=1)
    BundleItem.objects.create(bundle=bundle, product=hw["bulb"], quantity=1, sort_order=2)
    add_item(user, hw["impact"].variants.first().pk, 1)
    bundles = section(auth_client.get(CART).json(), "bundles")
    # one item of the set in the cart is not "partially matching": no offer yet
    assert bundles is None or all(i["type"] != "bundle" for i in bundles["items"])
    add_item(user, hw["hammer"].variants.first().pk, 1)
    item = next(i for i in section(auth_client.get(CART).json(), "bundles")["items"] if i["type"] == "bundle")
    assert item["action"] == "apply_bundle" and item["bundle"]["missing"] == [hw["bulb"].pk]
    assert D(item["total"]) == hw["bulb"].variants.first().price and item["reason"] == "You have 2 of its 3 items."
    response = auth_client.post(f"{BUNDLES}drilling-kit/add-to-cart/", {"only_missing": True}, format="json")
    assert response.status_code == 200 and response.json()["added_lines"] == 1
    assert CartItem.objects.get(cart__user=user, variant__product=hw["impact"]).quantity == 1  # not doubled


# --- Budget ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, budget",
    [
        ("tiles for 300 sq ft under 1500", 1500),
        ("I need plumbing materials under ₹5,000", 5000),
        ("10x12 kamre ki putai 2000 ke andar", 2000),
        ("पुताई 3000 तक", 3000),
        ("budget of 750 for screws", 750),
        ("paint a 12x15 room", None),
    ],
)
def test_budget_is_read_from_the_words(text, budget):
    assert budget_from_text(text) == (D(budget) if budget else None)


def test_budget_plan_never_exceeds_the_budget(hw, api_client):  # noqa: F811
    text = "lay a new water line of 12 m with 2 elbows for hot water"
    full = api_client.post(BUDGET, {"text": text, "budget": "99999"}, format="json").json()
    assert full["complete"] and full["within_budget"] and not full["dropped"]
    full_total = D(full["total"])
    tight = api_client.post(BUDGET, {"text": text, "budget": str(full_total - 1)}, format="json").json()
    assert D(tight["total"]) <= full_total - 1 and (tight["dropped"] or tight["swapped"])
    assert tight["full_kit_total"] == f"{full_total:.2f}"
    assert tight["message"].startswith("The full kit costs")
    impossible = api_client.post(BUDGET, {"text": text, "budget": "5"}, format="json").json()
    assert impossible["within_budget"] is False and D(impossible["total"]) == 0 and impossible["full_kit_over_budget"]
    assert all(not i["included"] for i in impossible["kit"]["items"])


def test_budget_plan_swaps_for_a_cheaper_product_of_the_same_kind(hw, api_client):  # noqa: F811
    from apps.core.testing import create_product

    # a cheaper CPVC pipe of the same kind in the same category
    cheap, variant = create_product(
        name="CPVC Pipe Economy 3 m", category=hw["cpvc"].category, price="20.00", mrp="30.00", stock=200
    )
    from apps.catalog.models import ProductSpecification

    ProductSpecification.objects.create(product=cheap, name="Material", key="material", value="CPVC")
    variant.name = "1/2 inch"
    variant.save()
    text = "lay a new water line of 12 m with 2 elbows for hot water"
    full = api_client.post(BUDGET, {"text": text, "budget": "99999"}, format="json").json()
    budget = D(full["total"]) - 1
    plan = api_client.post(BUDGET, {"text": text, "budget": str(budget)}, format="json").json()
    assert D(plan["total"]) <= budget
    assert plan["swapped"] and plan["swapped"][0]["to"] == "CPVC Pipe Economy 3 m"


def test_budget_questions_languages_and_refusals(hw, api_client):  # noqa: F811
    asking = api_client.post(BUDGET, {"text": "paint my room under 3000"}, format="json").json()
    assert asking["complete"] is False and "length" in asking["missing"] and "best_for_budget" in asking
    hinglish = api_client.post(BUDGET, {"text": "plumbing ka saman"}, format="json").json()
    assert hinglish["language"] == "hinglish" and hinglish["message"].startswith("Apna budget bataiye")
    unknown = api_client.post(BUDGET, {"text": "hello under 500"}, format="json").json()
    assert unknown["complete"] is False and unknown["message"].startswith("I couldn't tell")
    assert api_client.post(BUDGET, {}, format="json").status_code == 400
    bad = api_client.post(BUDGET, {"text": "paint my room under 3000", "answers": {"length": -1}}, format="json")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_answers"


# --- Bundles -----------------------------------------------------------------------------------------------


@pytest.fixture
def kit_bundle(hw):  # noqa: F811
    bundle = Bundle.objects.create(name="Wall kit", slug="wall-kit", kind="drilling", promo_label="Starter")
    BundleItem.objects.create(bundle=bundle, product=hw["impact"], quantity=1)
    BundleItem.objects.create(bundle=bundle, product=hw["masonry"], quantity=1, sort_order=1)
    BundleItem.objects.create(bundle=bundle, product=hw["plugs6"], quantity=2, sort_order=2)
    BundleItem.objects.create(bundle=bundle, product=hw["hammer"], quantity=1, is_optional=True, sort_order=3)
    return bundle


def test_bundles_are_priced_by_the_engine(hw, api_client, kit_bundle):  # noqa: F811
    from apps.ai.projects import kit
    from apps.shopping.services import bundles

    listing = api_client.get(BUNDLES).json()["results"]
    [row] = [b for b in listing if b["slug"] == "wall-kit"]
    rows = [r for r in bundles.rows(kit_bundle) if r.included]
    assert (
        row["total"] == kit.price_rows(rows, user=None)["totals"]["grand_total"]
        and row["item_count"] == 3
        and row["valid"]
    )
    data = api_client.post(f"{BUNDLES}wall-kit/price/", {}, format="json").json()
    items = {i["product_id"]: i for i in data["kit"]["items"]}
    assert not items[hw["hammer"].pk]["included"] and items[hw["plugs6"].pk]["quantity"] == 2
    assert data["promo_label"] == "Starter" and set(data["savings"]) == {"vs_mrp", "bulk", "offers"}
    assert api_client.get(BUNDLES, {"product": hw["masonry"].pk}).json()["results"][0]["slug"] == "wall-kit"


def test_bundle_edits_offers_and_tiers(hw, api_client, kit_bundle):  # noqa: F811
    set_price_tiers(hw["plugs6"].variants.first(), [{"min_quantity": 5, "unit_price": "800.00"}])
    offer = Offer.objects.create(
        name="Tools week",
        discount_type="percent",
        value=D("10"),
        starts_at=timezone.now() - timedelta(days=1),
        ends_at=timezone.now() + timedelta(days=1),
    )
    offer.categories.set([hw["impact"].category])
    plug_item = kit_bundle.items.get(product=hw["plugs6"])
    hammer_item = kit_bundle.items.get(product=hw["hammer"])
    data = api_client.post(
        f"{BUNDLES}wall-kit/price/",
        {"overrides": {str(plug_item.pk): {"quantity": 5}, str(hammer_item.pk): {"included": True}}},
        format="json",
    ).json()
    items = {i["product_id"]: i for i in data["kit"]["items"]}
    assert items[hw["plugs6"].pk]["price"]["applied_tier"] == {"min_quantity": 5} and items[hw["hammer"].pk]["included"]
    assert data["kit"]["offers"][0]["name"] == "Tools week" and D(data["savings"]["bulk"]) > 0
    wrong = api_client.post(
        f"{BUNDLES}wall-kit/price/",
        {"overrides": {str(plug_item.pk): {"variant_id": hw["cpvc_v"][0].pk}}},
        format="json",
    )
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "invalid_variant"


def test_bundle_stock_failure_and_add_to_cart(hw, user, auth_client, api_client, kit_bundle):  # noqa: F811
    from apps.inventory.models import Inventory

    assert api_client.post(f"{BUNDLES}wall-kit/add-to-cart/", {}, format="json").status_code == 401
    Inventory.objects.filter(variant__product=hw["masonry"]).update(available_quantity=0)
    data = api_client.post(f"{BUNDLES}wall-kit/price/", {}, format="json").json()
    assert not data["valid"] and any(i["code"] == "short_stock" for i in data["kit"]["issues"])
    refused = auth_client.post(f"{BUNDLES}wall-kit/add-to-cart/", {}, format="json")
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "project_not_addable"
    assert not CartItem.objects.filter(cart__user=user).exists()  # all or nothing
    masonry_item = kit_bundle.items.get(product=hw["masonry"])
    added = auth_client.post(
        f"{BUNDLES}wall-kit/add-to-cart/", {"overrides": {str(masonry_item.pk): {"included": False}}}, format="json"
    )
    assert added.status_code == 200 and added.json() == {"added_lines": 2, "added_units": 3}


def test_inactive_and_unpublished_bundles(hw, api_client, kit_bundle):  # noqa: F811
    hw["impact"].is_published = False
    hw["impact"].save()
    data = api_client.post(f"{BUNDLES}wall-kit/price/", {}, format="json").json()
    assert not data["valid"] and any(i["code"] == "unavailable" for i in data["kit"]["issues"])
    kit_bundle.ends_at = timezone.now() - timedelta(minutes=1)
    kit_bundle.save()
    assert api_client.post(f"{BUNDLES}wall-kit/price/", {}, format="json").status_code == 404
    assert all(b["slug"] != "wall-kit" for b in api_client.get(BUNDLES).json()["results"])


def test_bundle_compatibility_is_checked(hw, api_client):  # noqa: F811
    bundle = Bundle.objects.create(name="Bad kit", slug="bad-kit")
    BundleItem.objects.create(bundle=bundle, product=hw["cordless"], quantity=1)
    BundleItem.objects.create(bundle=bundle, product=hw["big_bits"], quantity=1, sort_order=1)
    data = api_client.post(f"{BUNDLES}bad-kit/price/", {}, format="json").json()
    assert not data["valid"] and data["kit"]["compatibility"][0]["verdict"] == "NOT_COMPATIBLE"


# --- Admin -------------------------------------------------------------------------------------------------


def test_admin_manages_bundles_with_audit(hw, admin_client, staff_client, auth_client):  # noqa: F811
    body = {
        "name": "Starter drill kit",
        "kind": "drilling",
        "item_rows": [
            {"product": hw["impact"].pk, "quantity": 1},
            {"product": hw["masonry"].pk, "quantity": 1, "note": "For walls"},
        ],
    }
    created = admin_client.post("/api/admin/bundles/", body, format="json")
    assert created.status_code == 201
    data = created.json()
    assert (
        data["slug"] == "starter-drill-kit"
        and [i["product"] for i in data["items"]] == [hw["impact"].pk, hw["masonry"].pk]
        and data["state"] == "live"
    )
    entry = AuditLog.objects.filter(action="bundle.create").latest("id")
    assert entry.changes["items"][1] == {"product": hw["masonry"].pk, "variant": None, "quantity": 1, "optional": False}
    url = f"/api/admin/bundles/{data['id']}/"
    admin_client.patch(
        url, {"item_rows": [{"product": hw["impact"].pk, "quantity": 2}], "is_active": False}, format="json"
    )
    entry = AuditLog.objects.filter(action="bundle.update").latest("id")
    assert entry.changes["items"]["before"][0]["quantity"] == 1 and entry.changes["items"]["after"] == [
        {"product": hw["impact"].pk, "variant": None, "quantity": 2, "optional": False}
    ]
    preview = admin_client.get(f"{url}preview/").json()
    assert preview["is_live"] is False and preview["kit"]["items"][0]["quantity"] == 2
    dup = admin_client.post(
        "/api/admin/bundles/",
        {"name": "X", "item_rows": [{"product": hw["impact"].pk}, {"product": hw["impact"].pk}]},
        format="json",
    )
    assert dup.status_code == 400
    foreign = admin_client.post(
        "/api/admin/bundles/",
        {"name": "X", "item_rows": [{"product": hw["impact"].pk, "variant": hw["cpvc_v"][0].pk}]},
        format="json",
    )
    assert foreign.status_code == 400
    assert staff_client.post("/api/admin/bundles/", body, format="json").status_code == 403
    assert auth_client.get("/api/admin/bundles/").status_code == 403
    admin_client.delete(url)
    assert AuditLog.objects.filter(action="bundle.delete").exists()


def test_admin_manages_recommendation_rules_with_audit(hw, admin_client, auth_client):  # noqa: F811
    body = {
        "source_category": hw["impact"].category_id,
        "target_category": hw["bulb"].category_id,
        "label": "Light it",
        "priority": 5,
    }
    created = admin_client.post("/api/admin/recommendation-rules/", body, format="json")
    assert created.status_code == 201 and created.json()["source_name"] == hw["impact"].category.name
    assert admin_client.post("/api/admin/recommendation-rules/", body, format="json").status_code == 400  # duplicate
    same = admin_client.post(
        "/api/admin/recommendation-rules/", {**body, "target_category": hw["impact"].category_id}, format="json"
    )
    assert same.status_code == 400
    assert AuditLog.objects.filter(action="recommendation_rule.create").exists()
    assert auth_client.post("/api/admin/recommendation-rules/", body, format="json").status_code == 403


def test_price_changes_show_at_once(hw, api_client, kit_bundle):  # noqa: F811
    before = api_client.post(f"{BUNDLES}wall-kit/price/", {}, format="json").json()["kit"]["totals"]["subtotal"]
    hw["impact"].variants.update(price=D("700.00"))
    after = api_client.post(f"{BUNDLES}wall-kit/price/", {}, format="json").json()["kit"]["totals"]["subtotal"]
    assert D(before) - D(after) == D("200.00")  # nothing cached from the old price


# --- Performance -------------------------------------------------------------------------------------------


def _queries(client, method, url):
    from django.core.cache import cache
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    cache.clear()
    with CaptureQueriesContext(connection) as captured:
        assert getattr(client, method)(url, format="json").status_code == 200
    return len(captured)


def test_queries_do_not_grow_with_links_bundle_items_or_cart_lines(hw, api_client, auth_client, user, kit_bundle):  # noqa: F811
    url = f"{REC}?product={hw['impact'].id}"
    set_accessories(hw["impact"], [{"product": hw["masonry"].id, "kind": "accessory"}])
    few = _queries(api_client, "get", url)
    links = [("masonry", "accessory"), ("hss", "accessory"), ("plugs6", "required"), ("screws", "accessory"),
             ("hammer", "accessory"), ("wire", "accessory"), ("bulb", "alternative")]  # fmt: skip
    set_accessories(hw["impact"], [{"product": hw[key].id, "kind": kind} for key, kind in links])
    assert _queries(api_client, "get", url) <= few + 8  # a group that now has rows may add its one query; not per link

    BundleItem.objects.create(bundle=kit_bundle, product=hw["wire"], quantity=1, sort_order=8)  # has option values
    kit_queries = _queries(api_client, "post", f"{BUNDLES}wall-kit/price/")
    for key in ("bulb", "connector"):  # no rule with the other items: no new problems (and replacement lookups)
        BundleItem.objects.create(bundle=kit_bundle, product=hw[key], quantity=1, sort_order=9)
    assert _queries(api_client, "post", f"{BUNDLES}wall-kit/price/") <= kit_queries + 2

    # the smart cart works per line (accessories on the first 5 lines, cheaper equivalents on the first 10 of a known
    # kind); the catalogue, offers, links and candidate products are loaded once, so each extra line costs a few queries
    for key in ("impact", "masonry", "hammer", "wire", "bulb", "connector", "mcb", "valve"):
        add_item(user, hw[key].variants.first().pk, 1)
    eight_lines = _queries(auth_client, "get", CART)
    for key in ("cpvc", "upvc", "elbow", "hss"):
        add_item(user, hw[key].variants.first().pk, 1)
    assert _queries(auth_client, "get", CART) <= eight_lines + 4 * 10
