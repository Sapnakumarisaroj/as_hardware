"""Phase 15 catalogue: bulk price tiers, structured options, three-level categories, curated lists,
and the price quote that runs the shop's pricing engine for one line."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.collections import collection_products
from apps.catalog.models import Category, Collection, OptionType, Product, ProductVariant
from apps.catalog.services import (
    CatalogRuleError,
    resolve_variant,
    save_product,
    set_price_tiers,
    set_variant_options,
    validate_price_tiers,
)
from apps.core.testing import create_address, create_category, create_product, create_store
from apps.orders.pricing import line_from_variant, tier_for
from apps.orders.services import place_order, transition_order

pytestmark = pytest.mark.django_db
D = Decimal


def tiers(*pairs):
    return [{"min_quantity": m, "unit_price": p} for m, p in pairs]


@pytest.fixture
def cement():
    civil = create_category("Civil")
    cement_cat = create_category("Cement", parent=civil)
    grey = create_category("Grey Cement", parent=cement_cat)
    store = create_store()
    product, variant = create_product(
        name="OPC Cement", price="450.00", mrp="480.00", category=cement_cat, subcategory=grey, stock=200, store=store
    )
    set_price_tiers(variant, tiers((10, "415"), (30, "405"), (50, "395")))
    return {"civil": civil, "cement": cement_cat, "grey": grey, "product": product, "variant": variant, "store": store}


# --- Bulk price tiers -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quantity", "price", "tier"),
    [(1, "450.00", None), (9, "450.00", None), (10, "415.00", 10), (29, "415.00", 10), (30, "405.00", 30),
     (49, "405.00", 30), (50, "395.00", 50)],
)  # fmt: skip
def test_tier_selected_at_every_boundary(cement, quantity, price, tier):
    line = line_from_variant(cement["variant"], quantity)
    assert line.unit_price == D(price)
    assert line.tier_min_quantity == tier
    assert line.line_total == D(price) * quantity
    if tier:
        assert line.base_unit_price == D("450.00") and line.bulk_saving == (D("450") - D(price)) * quantity


def test_next_tier_is_reported_until_the_last_one(cement):
    assert line_from_variant(cement["variant"], 7).next_tier == (10, D("415.00"))
    assert line_from_variant(cement["variant"], 30).next_tier == (50, D("395.00"))
    assert line_from_variant(cement["variant"], 50).next_tier is None


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        (((1, "400"),), "invalid_tier"),  # tiers start at 2 units
        (((10, "0"),), "invalid_tier"),
        (((10, "-5"),), "invalid_tier"),
        (((10, "abc"),), "invalid_tier"),
        (((10, "415"), (10, "405")), "overlapping_tiers"),
        (((10, "490"),), "tier_above_mrp"),
        (((10, "450"),), "tier_not_cheaper"),  # same as the normal price
        (((10, "415"), (30, "420")), "tier_not_cheaper"),  # more units must never cost more
        (((60, "390"),), "tier_above_order_limit"),  # order limit is 50
    ],
)
def test_invalid_tiers_are_refused(cement, rows, code):
    with pytest.raises(CatalogRuleError) as exc:
        validate_price_tiers(cement["variant"], tiers(*rows))
    assert exc.value.error_code == code


def test_refused_tier_list_keeps_the_old_tiers(cement):
    with pytest.raises(CatalogRuleError):
        set_price_tiers(cement["variant"], tiers((10, "415"), (10, "400")))
    assert [t.min_quantity for t in cement["variant"].price_tiers.all()] == [10, 30, 50]


def test_lowering_the_normal_price_below_a_tier_is_refused(cement):
    product, variant = cement["product"], cement["variant"]
    with pytest.raises(CatalogRuleError) as exc:
        save_product(instance=product, data={"variants": [{"id": variant.id, "price": D("400.00")}]})
    assert exc.value.error_code == "tier_not_cheaper"
    variant.refresh_from_db()
    assert variant.price == D("450.00")


def test_engine_never_charges_more_for_more_units_even_with_bad_data(cement):
    # A tier written around the service (bad import) that is dearer than the normal price is ignored.
    variant = cement["variant"]
    variant.price_tiers.filter(min_quantity=30).update(unit_price=D("470.00"))
    assert tier_for(variant, 35).unit_price == D("415.00")


def test_product_cards_and_detail_show_bulk_prices(api_client, cement):
    card = next(p for p in api_client.get("/api/products/").json()["results"] if p["id"] == cement["product"].id)
    assert card["bulk_pricing"] == {"from_quantity": 10, "lowest_unit_price": "395.00"}
    detail = api_client.get(f"/api/products/{cement['product'].slug}/").json()
    rows = detail["variants"][0]["price_tiers"]
    assert [(r["min_quantity"], r["max_quantity"], r["unit_price"]) for r in rows] == [
        (1, 9, "450.00"), (10, 29, "415.00"), (30, 49, "405.00"), (50, None, "395.00")
    ]  # fmt: skip
    assert rows[0]["is_base"] and rows[3]["saving_percent"] == "12.22"
    bulk_only = api_client.get("/api/products/", {"bulk_pricing": "true"}).json()
    assert [p["id"] for p in bulk_only["results"]] == [cement["product"].id]


def test_quote_runs_the_pricing_engine(api_client, cement):
    url = f"/api/products/{cement['product'].slug}/quote/"
    quote = api_client.get(url, {"quantity": 10}).json()
    assert quote["unit_price"] == "415.00" and quote["line_total"] == "4150.00"
    assert quote["applied_tier"] == {"min_quantity": 10} and quote["bulk_saving"] == "350.00"
    assert quote["next_tier"] == {"min_quantity": 30, "unit_price": "405.00", "units_more": 20, "reachable": True}
    assert api_client.get(url, {"quantity": 3}).json()["unit_price"] == "450.00"
    assert api_client.get(url, {"quantity": 0}).status_code == 400
    assert api_client.get(url, {"quantity": 51}).json()["error"]["code"] == "max_quantity_exceeded"
    assert api_client.get(url, {"variant": 999999}).status_code == 400


def test_cart_charges_the_tier_and_follows_quantity_changes(auth_client, cement):
    variant = cement["variant"]
    cart = auth_client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": 9}, format="json").json()
    line = cart["items"][0]
    assert (line["unit_price"], line["line_total"]) == ("450.00", "4050.00")
    assert line["bulk"]["next_tier"] == {"min_quantity": 10, "unit_price": "415.00", "units_more": 1, "reachable": True}
    cart = auth_client.patch(f"/api/cart/items/{line['id']}/", {"quantity": 30}, format="json").json()
    line = cart["items"][0]
    assert (line["unit_price"], line["base_unit_price"], line["line_total"]) == ("405.00", "450.00", "12150.00")
    assert line["bulk"]["applied_min_quantity"] == 30 and line["bulk"]["saving"] == "1350.00"
    assert cart["totals"]["subtotal"] == "12150.00" and cart["totals"]["bulk_savings"] == "1350.00"
    cart = auth_client.patch(f"/api/cart/items/{line['id']}/", {"quantity": 2}, format="json").json()
    assert cart["items"][0]["unit_price"] == "450.00" and cart["items"][0]["bulk"]["applied_min_quantity"] is None


def test_order_snapshots_the_tier_and_returns_refund_what_was_paid(user, admin_user, cement):
    from apps.carts.services import add_item
    from apps.orders.returns import approve_return, receive_return, request_return

    add_item(user, cement["variant"].id, 12)
    order, _ = place_order(user=user, address_id=create_address(user).id, payment_method="cod")
    item = order.items.get()
    assert (item.unit_price, item.base_unit_price, item.price_tier_min_quantity) == (D("415.00"), D("450.00"), 10)
    assert item.line_total == D("4980.00")
    # Later price changes don't touch the order.
    set_price_tiers(cement["variant"], [])
    item.refresh_from_db()
    assert item.unit_price == D("415.00")

    for status in ("processing", "packed", "assigned", "picked_up", "out_for_delivery", "delivered"):
        order = transition_order(order, status, actor=admin_user)
    request = request_return(order, user=user, items=[{"order_item_id": item.id, "quantity": 2}], reason="damaged")
    assert request.refund_amount == D("830.00")  # 2 × ₹415 (the tier price paid), not 2 × ₹450
    approve_return(request, actor=admin_user)
    received = receive_return(request, actor=admin_user, restock=True)
    assert received.refund.amount == D("830.00")


def test_stale_tier_between_preview_and_order_is_refused(auth_client, user, cement):
    variant = cement["variant"]
    auth_client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": 10}, format="json")
    address = create_address(user)
    preview = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    shown = preview["totals"]["grand_total"]
    assert shown == "4150.00"
    set_price_tiers(variant, tiers((10, "430"), (30, "405")))  # the 10+ price went up meanwhile
    res = auth_client.post(
        "/api/orders/", {"address_id": address.id, "payment_method": "cod", "expected_total": shown}, format="json"
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "totals_changed"
    assert res.json()["error"]["details"]["grand_total"] == "4300.00"
    assert not user.orders.exists()


# --- Structured options --------------------------------------------------------------------------


@pytest.fixture
def options(cement):
    grade = OptionType.objects.create(name="Grade", sort_order=1)
    bag = OptionType.objects.create(name="Bag size", unit="kg", sort_order=2)
    grade.categories.set([cement["cement"]])
    bag.categories.set([cement["civil"]])  # a department covers everything below it
    product, first = cement["product"], cement["variant"]
    second = ProductVariant.objects.create(product=product, sku="CEM-43-50", mrp=D("470"), price=D("430"))
    third = ProductVariant.objects.create(product=product, sku="CEM-53-25", mrp=D("250"), price=D("235"))
    set_variant_options(
        first, [{"option_type": grade.id, "value": "53 Grade"}, {"option_type": bag.id, "value": "50 kg"}]
    )
    set_variant_options(
        second, [{"option_type": grade.id, "value": "43 Grade"}, {"option_type": bag.id, "value": "50 kg"}]
    )
    set_variant_options(
        third, [{"option_type": grade.id, "value": "53 Grade"}, {"option_type": bag.id, "value": "25 kg"}]
    )
    return {"grade": grade, "bag": bag, "first": first, "second": second, "third": third}


def test_options_are_stored_as_rows_and_mirrored_in_attributes(options):
    first = options["first"]
    assert {o.option_type.name: o.value.value for o in first.option_values.all()} == {
        "Grade": "53 Grade",
        "Bag size": "50 kg",
    }
    first.refresh_from_db()
    assert first.attributes == {"Grade": "53 Grade", "Bag size": "50 kg"}
    assert options["grade"].values.count() == 2  # "53 Grade" reused, not duplicated


def test_variant_is_chosen_by_options_and_invalid_options_are_refused(cement, options):
    product = cement["product"]
    assert resolve_variant(product, {"grade": "43-grade", "bag-size": "50-kg"}) == options["second"]
    with pytest.raises(CatalogRuleError):
        resolve_variant(product, {"grade": "43-grade", "bag-size": "25-kg"})  # combination not sold
    with pytest.raises(CatalogRuleError):
        resolve_variant(product, {"colour": "red"})
    with pytest.raises(CatalogRuleError):
        resolve_variant(product, {"grade": "53-grade"})  # incomplete


def test_option_rules(cement, options):
    tools = create_category("Tools")
    _, drill = create_product(name="Drill", category=tools)
    with pytest.raises(CatalogRuleError):  # Grade is a cement option, not a tools one
        set_variant_options(drill, [{"option_type": options["grade"].id, "value": "53 Grade"}])
    with pytest.raises(CatalogRuleError):
        set_variant_options(options["first"], [{"option_type": options["grade"].id, "value": " "}])
    with pytest.raises(CatalogRuleError):
        set_variant_options(
            options["first"],
            [{"option_type": options["grade"].id, "value": "53"}, {"option_type": options["grade"].id, "value": "43"}],
        )
    with pytest.raises(CatalogRuleError) as exc:  # two variants with the same options
        save_product(
            instance=cement["product"],
            data={"variants": [{"id": options["second"].id, "options": [
                {"option_type": options["grade"].id, "value": "53 Grade"},
                {"option_type": options["bag"].id, "value": "50 kg"},
            ]}]},
        )  # fmt: skip
    assert exc.value.error_code == "duplicate_variant_options"


def test_product_detail_options_quote_by_option_and_filters(api_client, cement, options):
    slug = cement["product"].slug
    detail = api_client.get(f"/api/products/{slug}/").json()
    assert [(o["name"], [v["value"] for v in o["values"]]) for o in detail["options"]] == [
        ("Grade", ["53 Grade", "43 Grade"]),
        ("Bag size", ["50 kg", "25 kg"]),
    ]
    assert {v["sku"]: v["options"] for v in detail["variants"]}["CEM-43-50"] == {
        "grade": "43-grade",
        "bag-size": "50-kg",
    }
    quote = api_client.get(f"/api/products/{slug}/quote/", {"opt_grade": "53-grade", "opt_bag-size": "25-kg"}).json()
    assert quote["sku"] == "CEM-53-25" and quote["unit_price"] == "235.00"
    bad = api_client.get(f"/api/products/{slug}/quote/", {"opt_grade": "43-grade", "opt_bag-size": "25-kg"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_option"

    assert api_client.get("/api/products/", {"opt_grade": "43-grade"}).json()["count"] == 1
    assert api_client.get("/api/products/", {"opt_grade": "33-grade"}).json()["count"] == 0
    facets = api_client.get("/api/products/facets/", {"category": cement["cement"].slug}).json()
    grade = next(f for f in facets["options"] if f["slug"] == "grade")
    assert [(v["value"], v["count"]) for v in grade["values"]] == [("53 Grade", 1), ("43 Grade", 1)]
    types = api_client.get("/api/options/").json()
    assert [t["name"] for t in types] == ["Grade", "Bag size"]


def test_inactive_variant_cannot_be_bought_or_quoted(auth_client, api_client, cement, options):
    ProductVariant.objects.filter(pk=options["second"].pk).update(is_active=False)
    res = auth_client.post("/api/cart/items/", {"variant_id": options["second"].id, "quantity": 1}, format="json")
    assert res.status_code == 400 and res.json()["error"]["code"] == "product_unavailable"
    quote = api_client.get(f"/api/products/{cement['product'].slug}/quote/", {"variant": options["second"].id})
    assert quote.status_code == 400


# --- Three-level categories ----------------------------------------------------------------------


def test_three_levels_loops_and_product_placement(cement):
    civil, cement_cat, grey = cement["civil"], cement["cement"], cement["grey"]
    assert (civil.level, cement_cat.level, grey.level) == (1, 2, 3)
    civil.parent = grey  # a department under its own grandchild
    with pytest.raises(ValidationError):
        civil.clean()
    civil.refresh_from_db()
    cement_cat.parent = cement_cat
    with pytest.raises(ValidationError):
        cement_cat.clean()
    cement_cat.refresh_from_db()
    other = create_category("Other")
    moved = Category.objects.get(pk=cement_cat.pk)
    moved.parent = create_category("Deep", parent=other)  # would make Grey Cement a 4th level
    with pytest.raises(ValidationError):
        moved.clean()
    with pytest.raises(ValidationError):  # a third-level category can't be a product's main category
        Product(name="X", sku="X-9", slug="x-9", category=grey).clean()
    Product(name="Y", sku="Y-9", slug="y-9", category=civil, subcategory=cement_cat).clean()


def test_department_filter_includes_all_levels_and_api_returns_the_tree(api_client, cement):
    tools = create_category("Tools")
    create_product(name="Hammer", category=tools)
    by_department = api_client.get("/api/products/", {"category": cement["civil"].slug}).json()
    assert [p["id"] for p in by_department["results"]] == [cement["product"].id]
    assert api_client.get("/api/products/", {"category": cement["grey"].slug}).json()["count"] == 1
    tree = api_client.get("/api/categories/").json()
    civil = next(c for c in tree if c["slug"] == cement["civil"].slug)
    assert civil["product_count"] == 1 and civil["level"] == 1
    assert civil["children"][0]["name"] == "Cement" and civil["children"][0]["product_count"] == 1
    assert civil["children"][0]["children"][0]["name"] == "Grey Cement"
    detail = api_client.get(f"/api/categories/{cement['grey'].slug}/").json()
    assert [c["name"] for c in detail["breadcrumb"]] == ["Civil", "Cement", "Grey Cement"] and detail["level"] == 3
    facets = api_client.get("/api/products/facets/", {"category": cement["civil"].slug}).json()
    assert facets["categories"] == [{"slug": cement["cement"].slug, "name": "Cement", "count": 1}]
    product = api_client.get(f"/api/products/{cement['product'].slug}/").json()
    assert [c["name"] for c in product["breadcrumb"]] == ["Civil", "Cement", "Grey Cement"]


def test_inactive_category_is_hidden_from_customers(api_client, cement):
    Category.objects.filter(pk=cement["grey"].pk).update(is_active=False)
    tree = api_client.get("/api/categories/").json()
    civil = next(c for c in tree if c["slug"] == cement["civil"].slug)
    assert civil["children"][0]["children"] == []


# --- Curated lists -------------------------------------------------------------------------------


def test_manual_list_keeps_order_and_skips_unpublished(api_client, cement):
    _, drill = create_product(name="Drill")
    hidden, _ = create_product(name="Hidden", published=False)
    deals = Collection.objects.create(name="Deals of the week", ends_at=timezone.now() + timedelta(days=7))
    for position, product in enumerate([drill.product, hidden, cement["product"]]):
        deals.items.create(product=product, sort_order=position)
    assert [p.name for p in collection_products(deals)] == ["Drill", "OPC Cement"]
    data = api_client.get("/api/collections/").json()
    assert [c["name"] for c in data] == ["Deals of the week"]
    assert [p["name"] for p in data[0]["products"]] == ["Drill", "OPC Cement"]
    assert api_client.get(f"/api/collections/{deals.slug}/").status_code == 200


def test_lists_outside_their_dates_inactive_or_empty_are_not_shown(api_client, cement):
    past = Collection.objects.create(name="Old deals", ends_at=timezone.now() - timedelta(minutes=1))
    past.items.create(product=cement["product"])
    future = Collection.objects.create(name="Next week", starts_at=timezone.now() + timedelta(days=1))
    future.items.create(product=cement["product"])
    off = Collection.objects.create(name="Off", is_active=False)
    off.items.create(product=cement["product"])
    Collection.objects.create(name="Empty")
    Collection.objects.create(name="Best sellers", rule=Collection.Rule.BEST_SELLERS)  # nothing sold yet
    assert api_client.get("/api/collections/").json() == []
    assert api_client.get(f"/api/collections/{past.slug}/").status_code == 404


def test_automatic_lists_use_real_data(user, cement):
    from apps.carts.services import add_item

    tools = create_category("Tools")
    _, drill = create_product(name="Drill", category=tools, stock=10, store=cement["store"])
    Product.objects.filter(pk=cement["product"].pk).update(created_at=timezone.now() - timedelta(days=90))
    Product.objects.filter(pk=drill.product_id).update(
        launch_date=timezone.localdate() - timedelta(days=2), created_at=timezone.now() - timedelta(days=90)
    )
    newest = Collection.objects.create(name="New", rule=Collection.Rule.NEW_LAUNCHES, window_days=30)
    bulk = Collection.objects.create(name="Bulk", rule=Collection.Rule.BULK_PRICING)
    best = Collection.objects.create(name="Best", rule=Collection.Rule.BEST_SELLERS, window_days=30)
    best_tools = Collection.objects.create(name="Best tools", rule=Collection.Rule.BEST_SELLERS)
    best_tools.categories.set([tools])

    assert [p.name for p in collection_products(newest)] == ["Drill"]
    assert [p.name for p in collection_products(bulk)] == ["OPC Cement"]
    assert collection_products(best) == []
    add_item(user, cement["variant"].id, 5)
    add_item(user, drill.id, 1)
    place_order(user=user, address_id=create_address(user).id, payment_method="cod")
    assert [p.name for p in collection_products(best)] == ["OPC Cement", "Drill"]  # 5 units before 1
    assert [p.name for p in collection_products(best_tools)] == ["Drill"]
