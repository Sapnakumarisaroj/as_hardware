"""Customer product discovery: categories, listing, search, filters, sorting, pagination,
facets, suggestions, recent searches, stock/delivery display, and wishlist/cart integration."""

from decimal import Decimal

import pytest

from apps.catalog.models import Brand, ProductVariant, RecentSearch
from apps.catalog.search import tokenize
from apps.core.testing import add_stock, create_category, create_product, create_store
from apps.delivery.models import DeliveryZone

pytestmark = pytest.mark.django_db


def _names(res):
    return [p["name"] for p in res.json()["results"]]


@pytest.fixture
def catalog():
    """Electrical › Wires & Plumbing › Taps, Tools › Drills with specs, brands and stock."""
    store = create_store()
    DeliveryZone.objects.create(store=store, name="5 km", radius_km=Decimal("5"))
    electrical = create_category("Electrical")
    wires = create_category("Wires", parent=electrical)
    plumbing = create_category("Plumbing")
    taps = create_category("Taps", parent=plumbing)
    tools = create_category("Tools")
    drills = create_category("Drills", parent=tools)
    volt = Brand.objects.create(name="VoltLine", slug="voltline")
    drillco = Brand.objects.create(name="DrillCo", slug="drillco")

    wire, wire_small = create_product(
        name="FR Copper Wire 90 m",
        price="1749.00",
        mrp="2150.00",
        category=electrical,
        subcategory=wires,
        stock=40,
        store=store,
        brand=volt,
        tags=["house wiring"],
    )
    wire_small.name = "1.0 sq mm"
    wire_small.save()
    wire_big = ProductVariant.objects.create(
        product=wire, sku="WIRE-1.5", name="1.5 sq mm", mrp=Decimal("2600.00"), price=Decimal("2100.00"), sort_order=1
    )
    add_stock(wire_big, 3, store=store)  # low stock
    wire.specifications.create(name="Conductor", value="Copper")

    tap, _ = create_product(
        name="Brass Pillar Tap",
        price="600.00",
        mrp="1000.00",
        category=plumbing,
        subcategory=taps,
        stock=10,
        store=store,
    )
    tap.specifications.create(name="Material", value="Brass")

    impact, _ = create_product(
        name="Impact Drill 650W",
        price="3200.00",
        mrp="4000.00",
        category=tools,
        subcategory=drills,
        stock=8,
        store=store,
        brand=drillco,
    )
    impact.specifications.create(name="Power", value="650", unit="W")
    impact.specifications.create(name="Chuck Size", value="13", unit="mm")
    cordless, _ = create_product(
        name="Cordless Drill Driver",
        price="2500.00",
        mrp="2600.00",
        category=tools,
        subcategory=drills,
        brand=drillco,
        short_description="Great for concrete and wood",
    )  # out of stock
    cordless.specifications.create(name="Power", value="12", unit="V")
    cordless.specifications.create(name="Chuck Size", value="10", unit="mm")
    return {
        "store": store,
        "electrical": electrical,
        "wires": wires,
        "tools": tools,
        "drills": drills,
        "wire": wire,
        "wire_big": wire_big,
        "tap": tap,
        "impact": impact,
        "cordless": cordless,
    }


# --- Categories -------------------------------------------------------------------------------


def test_category_tree_has_children_and_product_counts(api_client, catalog):
    create_product(name="Draft Wire", category=catalog["electrical"], subcategory=catalog["wires"], published=False)
    tree = {c["slug"]: c for c in api_client.get("/api/categories/").json()}
    tools = tree[catalog["tools"].slug]
    assert tools["product_count"] == 2
    assert [(c["slug"], c["product_count"]) for c in tools["children"]] == [(catalog["drills"].slug, 2)]
    assert tree[catalog["electrical"].slug]["product_count"] == 1  # the unpublished one is not counted


def test_subcategory_detail_by_slug_includes_parent(api_client, catalog):
    res = api_client.get(f"/api/categories/{catalog['drills'].slug}/")
    assert res.status_code == 200
    body = res.json()
    assert body["parent_detail"]["slug"] == catalog["tools"].slug
    assert body["product_count"] == 2
    assert api_client.get("/api/categories/no-such-category/").status_code == 404


# --- Listing & detail -------------------------------------------------------------------------


def test_listing_card_fields_are_server_computed(api_client, catalog):
    res = api_client.get("/api/products/", {"category": catalog["electrical"].slug})
    card = res.json()["results"][0]
    assert card["price"] == "1749.00" and card["mrp"] == "2150.00"  # cheapest variant
    assert card["discount_percent"] == "18.65" and card["discount_amount"] == "401.00"
    assert card["variant_count"] == 2
    assert card["default_variant_id"] == catalog["wire"].variants.get(sku__startswith="V-").id
    assert card["stock_status"] == "in_stock" and card["fast_delivery"] is True
    assert card["image"] is None and card["image_alt"] == "FR Copper Wire 90 m"
    assert "stock_total" not in card and "available_quantity" not in card


def test_detail_by_slug_with_variants_and_hidden_exact_stock(api_client, catalog):
    res = api_client.get(f"/api/products/{catalog['wire'].slug}/")
    assert res.status_code == 200
    variants = {v["name"]: v for v in res.json()["variants"]}
    small, big = variants["1.0 sq mm"], variants["1.5 sq mm"]
    assert (big["sku"], big["price"], big["mrp"]) == ("WIRE-1.5", "2100.00", "2600.00")
    assert big["discount_amount"] == "500.00" and big["discount_percent"] == "19.23"
    assert small["stock_status"] == "in_stock" and small["available_quantity"] is None
    assert big["stock_status"] == "low_stock" and big["available_quantity"] == 3
    assert small["fast_delivery"] is True
    assert res.json()["specifications"][0]["value"] == "Copper"


def test_unpublished_product_detail_is_hidden_from_customers(api_client, auth_client):
    product, _ = create_product(published=False)
    assert api_client.get(f"/api/products/{product.slug}/").status_code == 404
    assert auth_client.get(f"/api/products/{product.slug}/").status_code == 404


def test_out_of_stock_and_no_fast_delivery_without_zone(api_client, catalog):
    card = next(p for p in api_client.get("/api/products/").json()["results"] if p["name"] == "Cordless Drill Driver")
    assert card["stock_status"] == "out_of_stock" and card["fast_delivery"] is False
    other_store = create_store(zone=False)  # no delivery zone → stock there is not "fast"
    product, _ = create_product(name="Hammer", stock=5, store=other_store)
    card = next(p for p in api_client.get("/api/products/").json()["results"] if p["name"] == "Hammer")
    assert card["stock_status"] == "low_stock" and card["fast_delivery"] is False


# --- Search -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("drill", ["Impact Drill 650W", "Cordless Drill Driver"]),
        ("drills", ["Impact Drill 650W", "Cordless Drill Driver"]),  # plural → singular
        ("drillco", ["Cordless Drill Driver", "Impact Drill 650W"]),  # brand
        ("concrete drill", ["Cordless Drill Driver"]),  # description + name
        ("1.5 sq mm wire", ["FR Copper Wire 90 m"]),  # variant name
        ("brass", ["Brass Pillar Tap"]),
        ("taps", ["Brass Pillar Tap"]),  # category name
        ("wire-1.5", ["FR Copper Wire 90 m"]),  # variant SKU
        ("house wiring", ["FR Copper Wire 90 m"]),  # tags
    ],
)
def test_search_matches_expected_products(api_client, catalog, query, expected):
    res = api_client.get("/api/products/", {"q": query})
    assert res.status_code == 200
    assert sorted(_names(res)) == sorted(expected)
    assert res.json()["search"] == {"query": query, "matched": "all_terms"}


def test_search_ranks_name_matches_first_and_falls_back_to_any_term(api_client, catalog):
    ranked = _names(api_client.get("/api/products/", {"q": "impact drill"}))
    assert ranked[0] == "Impact Drill 650W"
    res = api_client.get("/api/products/", {"q": "water tap"})  # "water" matches nothing
    assert _names(res) == ["Brass Pillar Tap"]
    assert res.json()["search"]["matched"] == "some_terms"
    assert api_client.get("/api/products/", {"q": "zzzz"}).json()["count"] == 0


def test_tokenizer_keeps_sizes_and_drops_stopwords():
    assert tokenize("Wire for 1.5 sq mm, 3/4 inch") == ("wire", "1.5", "sq", "mm", "3/4", "inch")


def test_suggestions_return_products_categories_and_brands(api_client, catalog):
    body = api_client.get("/api/search/suggest/", {"q": "dril"}).json()
    assert {p["name"] for p in body["products"]} == {"Impact Drill 650W", "Cordless Drill Driver"}
    assert [c["name"] for c in body["categories"]] == ["Drills"]
    assert body["categories"][0]["parent_name"] == "Tools"
    assert [b["name"] for b in body["brands"]] == ["DrillCo"]
    assert api_client.get("/api/search/suggest/", {"q": "d"}).json()["products"] == []


def test_recent_searches_are_private_deduplicated_and_clearable(api_client, auth_client, user):
    assert api_client.get("/api/search/recent/").status_code == 401
    for term in ["Drill", "wire", "drill "]:
        assert auth_client.post("/api/search/recent/", {"query": term}, format="json").status_code == 201
    assert [r["query"] for r in auth_client.get("/api/search/recent/").json()] == ["drill", "wire"]
    for n in range(RecentSearch.MAX_PER_USER + 3):
        auth_client.post("/api/search/recent/", {"query": f"term {n}"}, format="json")
    assert RecentSearch.objects.filter(user=user).count() == RecentSearch.MAX_PER_USER
    assert auth_client.delete("/api/search/recent/").status_code == 204
    assert auth_client.get("/api/search/recent/").json() == []


# --- Filters, sorting, pagination -------------------------------------------------------------


def test_filters_brand_price_discount_availability_spec_exclude(api_client, catalog):
    tools = catalog["tools"].slug
    assert set(_names(api_client.get("/api/products/", {"brand": "drillco"}))) == {
        "Impact Drill 650W",
        "Cordless Drill Driver",
    }
    assert _names(api_client.get("/api/products/", {"min_price": "1000", "max_price": "2000"})) == [
        "FR Copper Wire 90 m"
    ]
    assert _names(api_client.get("/api/products/", {"discount": "30"})) == ["Brass Pillar Tap"]
    assert _names(api_client.get("/api/products/", {"category": tools, "availability": "in_stock"})) == [
        "Impact Drill 650W"
    ]
    assert _names(api_client.get("/api/products/", {"category": tools, "fast_delivery": "true"})) == [
        "Impact Drill 650W"
    ]
    assert _names(api_client.get("/api/products/", {"spec_power": "12"})) == ["Cordless Drill Driver"]
    assert set(_names(api_client.get("/api/products/", {"spec_chuck-size": "13,10"}))) == {
        "Impact Drill 650W",
        "Cordless Drill Driver",
    }
    assert _names(api_client.get("/api/products/", {"category": tools, "exclude": catalog["impact"].slug})) == [
        "Cordless Drill Driver"
    ]
    # Invalid numbers are ignored rather than erroring.
    assert api_client.get("/api/products/", {"min_price": "abc", "discount": "NaN"}).json()["count"] == 4


def test_rating_filter_and_bestseller_filter(api_client, catalog):
    tap = catalog["tap"]
    tap.rating_avg, tap.rating_count = Decimal("4.50"), 2
    tap.save()
    assert _names(api_client.get("/api/products/", {"rating": "4"})) == ["Brass Pillar Tap"]
    assert api_client.get("/api/products/", {"bestseller": "true"}).json()["count"] == 0


@pytest.mark.parametrize(
    ("ordering", "first"),
    [
        ("price", "Brass Pillar Tap"),
        ("-price", "Impact Drill 650W"),
        ("discount", "Brass Pillar Tap"),
        ("newest", "Cordless Drill Driver"),
        ("name", "Brass Pillar Tap"),
    ],
)
def test_sorting(api_client, catalog, ordering, first):
    assert _names(api_client.get("/api/products/", {"ordering": ordering}))[0] == first


def test_rating_sort_and_unknown_ordering_falls_back(api_client, catalog):
    impact = catalog["impact"]
    impact.rating_avg, impact.rating_count = Decimal("4.90"), 7
    impact.save()
    assert _names(api_client.get("/api/products/", {"ordering": "rating"}))[0] == "Impact Drill 650W"
    assert api_client.get("/api/products/", {"ordering": "drop table"}).status_code == 200


def test_pagination(api_client, catalog):
    first = api_client.get("/api/products/", {"page_size": 3, "ordering": "name"}).json()
    assert first["count"] == 4 and len(first["results"]) == 3 and first["next"]
    second = api_client.get("/api/products/", {"page_size": 3, "ordering": "name", "page": 2}).json()
    assert len(second["results"]) == 1 and second["next"] is None
    assert api_client.get("/api/products/", {"page": 99}).status_code == 404


# --- Facets -------------------------------------------------------------------------------------


def test_facets_offer_relevant_spec_filters_per_category(api_client, catalog):
    drills = api_client.get("/api/products/facets/", {"category": catalog["tools"].slug}).json()
    assert drills["total"] == 2
    assert [c["slug"] for c in drills["categories"]] == [catalog["drills"].slug]
    assert drills["brands"] == [{"slug": "drillco", "name": "DrillCo", "count": 2}]
    assert drills["price"] == {"min": "2500.00", "max": "3200.00"}
    assert drills["availability"] == {"in_stock": 1, "fast_delivery": 1}
    spec_keys = {f["key"] for f in drills["specifications"]}
    assert spec_keys == {"power", "chuck-size"}
    power = next(f for f in drills["specifications"] if f["key"] == "power")
    assert [v["value"] for v in power["values"]] == ["12", "650"]

    # Plumbing-only facets never show drill specifications.
    taps = api_client.get("/api/products/facets/", {"q": "tap"}).json()
    assert taps["specifications"] == []


def test_facet_counts_ignore_their_own_filter(api_client, catalog):
    body = api_client.get("/api/products/facets/", {"brand": "drillco"}).json()
    assert body["total"] == 2
    # Other brands stay selectable (the tap uses the helper's default "Test Brand").
    assert {b["slug"] for b in body["brands"]} == {"drillco", "voltline", "test-brand"}


# --- Wishlist & cart integration ----------------------------------------------------------------


def test_wishlist_add_list_remove_requires_login(api_client, auth_client, catalog):
    product = catalog["impact"]
    assert api_client.post("/api/wishlist/", {"product_id": product.id}, format="json").status_code == 401
    assert auth_client.post("/api/wishlist/", {"product_id": product.id}, format="json").status_code == 201
    assert (
        auth_client.post("/api/wishlist/", {"product_id": product.id}, format="json").status_code == 201
    )  # idempotent
    items = auth_client.get("/api/wishlist/").json()
    assert [i["product"]["slug"] for i in items] == [product.slug]
    assert items[0]["product"]["price"] == "3200.00"
    assert auth_client.delete(f"/api/wishlist/{product.id}/").status_code == 204
    assert auth_client.get("/api/wishlist/").json() == []


def test_cart_uses_selected_variant_server_price_and_stock(auth_client, catalog):
    big = catalog["wire_big"]
    res = auth_client.post("/api/cart/items/", {"variant_id": big.id, "quantity": 2, "price": "1.00"}, format="json")
    assert res.status_code == 201
    line = res.json()["items"][0]
    assert (line["sku"], line["unit_price"], line["quantity"]) == ("WIRE-1.5", "2100.00", 2)

    too_many = auth_client.post("/api/cart/items/", {"variant_id": big.id, "quantity": 5}, format="json")
    assert too_many.status_code == 409
    assert too_many.json()["error"]["message"] == "Only 3 unit(s) available."

    cordless = catalog["cordless"].variants.get()
    out = auth_client.post("/api/cart/items/", {"variant_id": cordless.id}, format="json")
    assert out.status_code == 409 and out.json()["error"]["message"] == "This item is out of stock."

    item_id = line["id"]
    assert (
        auth_client.patch(f"/api/cart/items/{item_id}/", {"quantity": 3}, format="json").json()["items"][0]["quantity"]
        == 3
    )
    assert auth_client.delete(f"/api/cart/items/{item_id}/").json()["items"] == []


# --- Unauthorized catalog modifications -------------------------------------------------------


def test_customers_cannot_modify_catalog_prices_inventory_or_fake_reviews(auth_client, api_client, catalog):
    impact = catalog["impact"]
    variant = impact.variants.get()
    url = f"/api/products/{impact.slug}/"
    price_change = {"variants": [{"id": variant.id, "sku": variant.sku, "mrp": "1.00", "price": "1.00"}]}
    assert auth_client.patch(url, price_change, format="json").status_code == 403
    assert api_client.patch(url, price_change, format="json").status_code == 401
    assert auth_client.delete(url).status_code == 403
    assert auth_client.post("/api/categories/", {"name": "Hacked"}, format="json").status_code == 403
    assert (
        auth_client.patch(f"/api/categories/{catalog['tools'].slug}/", {"name": "X"}, format="json").status_code == 403
    )
    assert auth_client.post("/api/brands/", {"name": "Fake"}, format="json").status_code == 403
    assert auth_client.get("/api/inventory/").status_code == 403
    assert auth_client.get(url, {"include_unpublished": "true"}).status_code == 200  # flag ignored for customers
    variant.refresh_from_db()
    assert variant.price == Decimal("3200.00")

    review = auth_client.post(f"{url}reviews/", {"rating": 5, "title": "Great"}, format="json")
    assert review.status_code == 400 and review.json()["error"]["code"] == "not_purchased"


def test_customers_never_see_unpublished_products_via_listing_flags(auth_client):
    create_product(name="Secret Drill", published=False, stock=3)
    res = auth_client.get("/api/products/", {"include_unpublished": "true", "q": "secret"})
    assert res.json()["count"] == 0


def test_discount_sort_and_filter_use_exact_percentages(api_client):
    """Whole-number prices must not be ranked by integer division (SQLite stores them as INTEGER)."""
    category = create_category("Fixings")
    create_product(name="Screws", price="129.00", mrp="180.00", category=category)  # 28.33 %
    create_product(name="Masks", price="249.00", mrp="350.00", category=category)  # 28.86 %
    create_product(name="Pliers", price="300.00", mrp="400.00", category=category)  # exactly 25 %
    create_product(name="Glue", price="301.00", mrp="400.00", category=category)  # 24.75 %
    res = api_client.get("/api/products/", {"ordering": "discount"})
    assert _names(res) == ["Masks", "Screws", "Pliers", "Glue"]
    assert _names(api_client.get("/api/products/", {"discount": "25", "ordering": "discount"})) == [
        "Masks",
        "Screws",
        "Pliers",
    ]
    assert _names(api_client.get("/api/products/", {"discount": "28.5"})) == ["Masks"]
