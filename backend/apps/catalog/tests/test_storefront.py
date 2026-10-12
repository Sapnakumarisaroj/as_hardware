"""Phase 16 storefront APIs: PIN-aware delivery flags on listings and product pages, search words
understood as filters, free-delivery badges, brand pages, product-page content and accessories,
payment options in the quote, recently viewed (`slugs`), the sitemap, and that customers still can't
change catalogue data."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog.models import Brand, OptionType, Product
from apps.catalog.services import set_variant_options
from apps.core.testing import create_category, create_product
from apps.delivery.models import DeliveryZone, FreeDeliveryRule, PinCode
from apps.delivery.tests.helpers import store_at, zone_for
from apps.payments.models import PaymentSettings
from apps.stores.models import Store

pytestmark = pytest.mark.django_db

NEAR_PIN = "411038"  # the fast store's own PIN (PIN centre = the store)
FAR_PIN = "411014"  # served by nobody


@pytest.fixture
def shop():
    """A fast store at PIN 411038 and a far store (20 km north) that doesn't reach it."""
    near = store_at(0, name="Near Store", postal_code=NEAR_PIN)
    near_zone = zone_for(near)
    far = store_at(20, name="Far Store", postal_code="411099")
    zone_for(far)
    PinCode.objects.create(postal_code=NEAR_PIN, area="Kothrud", latitude=near.latitude, longitude=near.longitude)
    tools = create_category("Tools")
    drill, drill_variant = create_product(name="Drill", price="900.00", stock=5, store=near, category=tools)
    saw, saw_variant = create_product(name="Saw", price="500.00", stock=5, store=far, category=tools)
    return {
        "near": near,
        "near_zone": near_zone,
        "far": far,
        "tools": tools,
        "drill": drill,
        "drill_variant": drill_variant,
        "saw": saw,
        "saw_variant": saw_variant,
    }


def by_slug(data):
    return {p["slug"]: p for p in data["results"]}


# --- PIN-aware delivery --------------------------------------------------------------------------


def test_listing_without_a_pin_promises_no_pin_delivery(api_client, shop):
    data = api_client.get("/api/products/").json()
    assert "delivery_context" not in data
    assert all(p["delivery"] is None for p in data["results"])


def test_listing_marks_fast_delivery_only_for_the_chosen_pin(api_client, shop):
    data = api_client.get("/api/products/", {"postal_code": NEAR_PIN}).json()
    context = data["delivery_context"]
    assert context["serviceable"] is True and context["fast_delivery_available"] is True
    assert context["label"].startswith("Delivery in ") and "60" not in context["label"].split()[2:3]
    products = by_slug(data)
    assert products[shop["drill"].slug]["delivery"] == {"postal_code": NEAR_PIN, "deliverable": True, "fast": True}
    # The saw is only at a store that doesn't reach this PIN: not deliverable, no fast badge.
    assert products[shop["saw"].slug]["delivery"] == {"postal_code": NEAR_PIN, "deliverable": False, "fast": False}
    # The Phase 4 flag (stocked at *some* fast store) is unchanged for older clients.
    assert products[shop["saw"].slug]["fast_delivery"] is True


def test_fast_filter_and_facets_follow_the_pin(api_client, shop):
    fast = api_client.get("/api/products/", {"postal_code": NEAR_PIN, "fast_delivery": "true"}).json()
    assert [p["slug"] for p in fast["results"]] == [shop["drill"].slug]
    deliverable = api_client.get("/api/products/", {"postal_code": NEAR_PIN, "deliverable": "true"}).json()
    assert deliverable["count"] == 1
    facets = api_client.get("/api/products/facets/", {"postal_code": NEAR_PIN}).json()
    assert facets["availability"]["fast_delivery"] == 1
    assert api_client.get("/api/products/facets/").json()["availability"]["fast_delivery"] == 2


def test_no_fast_badge_when_the_store_cannot_deliver_fast_now(api_client, shop):
    Store.objects.filter(pk=shop["near"].pk).update(own_riders=0)  # no rider → standard only
    data = api_client.get("/api/products/", {"postal_code": NEAR_PIN}).json()
    assert data["delivery_context"]["fast_delivery_available"] is False
    assert data["delivery_context"]["fast_unavailable_reason"]
    drill = by_slug(data)[shop["drill"].slug]["delivery"]
    assert drill["deliverable"] is True and drill["fast"] is False


def test_unserved_pin_and_invalid_pin(api_client, shop):
    data = api_client.get("/api/products/", {"postal_code": FAR_PIN}).json()
    assert data["delivery_context"]["serviceable"] is False
    assert data["delivery_context"]["message"] == f"We don't deliver to PIN {FAR_PIN} yet."
    assert all(p["delivery"]["deliverable"] is False for p in data["results"])
    for junk in ("12", "abcdef", "012345", "4110388"):
        response = api_client.get("/api/products/", {"postal_code": junk})
        assert response.status_code == 200 and "delivery_context" not in response.json()


def test_product_detail_with_a_pin(api_client, shop):
    url = f"/api/products/{shop['drill'].slug}/"
    assert api_client.get(url).json()["delivery"] is None
    data = api_client.get(url, {"postal_code": NEAR_PIN}).json()
    assert data["delivery"] == {"postal_code": NEAR_PIN, "deliverable": True, "fast": True}
    assert data["variants"][0]["fast_delivery"] is True
    saw = api_client.get(f"/api/products/{shop['saw'].slug}/", {"postal_code": NEAR_PIN}).json()
    assert saw["delivery"]["deliverable"] is False and saw["variants"][0]["fast_delivery"] is False


# --- Search words → filters ----------------------------------------------------------------------


@pytest.fixture
def cement_shop(shop):
    civil = create_category("Civil")
    cement = create_category("Cement", parent=civil)
    opc, opc_variant = create_product(name="OPC Cement", price="410.00", category=cement, stock=50, store=shop["near"])
    ppc, ppc_variant = create_product(name="PPC Cement", price="380.00", category=cement, stock=50, store=shop["near"])
    grade = OptionType.objects.create(name="Grade")
    bag = OptionType.objects.create(name="Bag size", unit="kg")
    grade.values.create(value="43 Grade")  # exists as a value, but no product has it
    set_variant_options(
        opc_variant, [{"option_type": grade.pk, "value": "53 Grade"}, {"option_type": bag.pk, "value": "50 kg"}]
    )
    set_variant_options(
        ppc_variant, [{"option_type": grade.pk, "value": "PPC"}, {"option_type": bag.pk, "value": "25 kg"}]
    )
    return {"opc": opc, "ppc": ppc, "cement": cement}


def test_grade_and_category_are_understood(api_client, cement_shop):
    data = api_client.get("/api/products/", {"q": "53 grade cement"}).json()
    assert [p["slug"] for p in data["results"]] == [cement_shop["opc"].slug]
    assert data["search"]["interpreted"] == [
        {"param": "opt_grade", "value": "53-grade", "label": "Grade: 53 Grade"},
        {"param": "category", "value": cement_shop["cement"].slug, "label": "Cement"},
    ]


def test_pack_size_written_without_a_space(api_client, cement_shop):
    data = api_client.get("/api/products/", {"q": "50kg cement"}).json()
    assert {"param": "opt_bag-size", "value": "50-kg", "label": "Bag size: 50 kg"} in data["search"]["interpreted"]
    assert [p["slug"] for p in data["results"]] == [cement_shop["opc"].slug]


def test_use_words_keep_the_category_filter(api_client, cement_shop):
    data = api_client.get("/api/products/", {"q": "cement for plastering"}).json()
    assert data["search"]["interpreted"] == [
        {"param": "category", "value": cement_shop["cement"].slug, "label": "Cement"}
    ]
    assert {p["slug"] for p in data["results"]} <= {cement_shop["opc"].slug, cement_shop["ppc"].slug}


def test_nothing_is_invented_or_forced(api_client, cement_shop):
    # "33 grade" is not a value the shop has: not understood.
    unknown = api_client.get("/api/products/", {"q": "33 grade cement"}).json()
    assert all(item["param"] != "opt_grade" for item in unknown["search"].get("interpreted", []))
    # "43 Grade" exists but no product has it: the filter would leave nothing, so it isn't applied.
    empty = api_client.get("/api/products/", {"q": "43 grade cement"}).json()
    assert "interpreted" not in empty["search"] and empty["count"] >= 1
    # The shopper removed the understood filters.
    off = api_client.get("/api/products/", {"q": "53 grade cement", "interpret": "0"}).json()
    assert "interpreted" not in off["search"]
    # A filter the shopper chose wins over the words.
    chosen = api_client.get("/api/products/", {"q": "53 grade cement", "opt_grade": "ppc"}).json()
    assert all(item["param"] != "opt_grade" for item in chosen["search"].get("interpreted", []))


def test_facets_use_the_understood_filters(api_client, cement_shop):
    facets = api_client.get("/api/products/facets/", {"q": "53 grade cement"}).json()
    assert facets["total"] == 1


# --- Free-delivery badge, brands, recently viewed -------------------------------------------------


def test_free_delivery_badge_follows_live_rules(api_client, shop):
    now = timezone.now()
    rule = FreeDeliveryRule.objects.create(name="Tools from ₹2,000", threshold=Decimal("2000"), starts_at=now)
    rule.categories.set([shop["tools"]])
    other, _ = create_product(name="Glove", stock=1, store=shop["near"], category=create_category("Safety"))
    products = by_slug(api_client.get("/api/products/").json())
    assert products[shop["drill"].slug]["free_delivery"] == {"name": "Tools from ₹2,000", "threshold": "2000.00"}
    assert products[other.slug]["free_delivery"] is None

    zoned = FreeDeliveryRule.objects.create(name="Glove zone", threshold=Decimal("100"), starts_at=now)
    zoned.products.set([other])
    zoned.zones.set([shop["near_zone"]])
    assert by_slug(api_client.get("/api/products/").json())[other.slug]["free_delivery"] is None  # no PIN
    with_pin = by_slug(api_client.get("/api/products/", {"postal_code": NEAR_PIN}).json())
    assert with_pin[other.slug]["free_delivery"]["name"] == "Glove zone"

    FreeDeliveryRule.objects.filter(pk=rule.pk).update(ends_at=now - timedelta(minutes=1))
    assert by_slug(api_client.get("/api/products/").json())[shop["drill"].slug]["free_delivery"] is None


def test_brand_pages_count_only_visible_products(api_client, shop):
    brand = Brand.objects.create(name="Acme", slug="acme", description="Hand tools")
    create_product(name="Acme Hammer", brand=brand, stock=1, store=shop["near"])
    create_product(name="Acme Draft", brand=brand, published=False)
    Brand.objects.create(name="Hidden", slug="hidden", is_active=False)
    brands = {b["slug"]: b for b in api_client.get("/api/brands/").json()}
    assert brands["acme"]["product_count"] == 1 and "hidden" not in brands
    detail = api_client.get("/api/brands/acme/").json()
    assert detail["description"] == "Hand tools" and detail["product_count"] == 1
    assert api_client.get("/api/brands/hidden/").status_code == 404
    facets = api_client.get("/api/products/facets/", {"brand": "acme"}).json()
    assert facets["total"] == 1 and facets["categories"]


def test_recently_viewed_by_slugs(api_client, shop):
    hidden, _ = create_product(name="Draft", published=False)
    data = api_client.get("/api/products/", {"slugs": f"{shop['saw'].slug},{hidden.slug},nope"}).json()
    assert [p["slug"] for p in data["results"]] == [shop["saw"].slug]


# --- Product page content, accessories, payment options ------------------------------------------


def test_product_page_content_and_accessories(admin_client, api_client, shop):
    bits, _ = create_product(name="Drill Bits", stock=3, store=shop["near"])
    draft, _ = create_product(name="Draft Plugs", published=False)
    url = f"/api/admin/products/{shop['drill'].pk}/"
    saved = admin_client.patch(
        url,
        {
            "quick_answer": "Drills brick and wood.",
            "uses": "Brick walls\n- Wood\n\n",
            "installation_steps": "Mark the spot\nDrill straight",
            "faqs": [{"question": "Concrete?", "answer": "Yes, with a masonry bit."}],
            "accessories": [{"product": bits.pk, "note": "For brick"}, {"product": draft.pk}],
        },
        format="json",
    )
    assert saved.status_code == 200, saved.data
    assert [a["slug"] for a in saved.data["accessories"]] == [bits.slug, draft.slug]

    data = api_client.get(f"/api/products/{shop['drill'].slug}/").json()
    assert data["quick_answer"] == "Drills brick and wood."
    assert data["uses"] == ["Brick walls", "Wood"]
    assert data["installation_steps"] == ["Mark the spot", "Drill straight"]
    assert data["faqs"] == [{"question": "Concrete?", "answer": "Yes, with a masonry bit."}]
    # Customers see only published accessories, with the shop's note.
    assert [(a["slug"], a["relation_note"]) for a in data["accessories"]] == [(bits.slug, "For brick")]
    assert data["return_policy"]["returnable"] is True and data["return_policy"]["window_days"] >= 1


@pytest.mark.parametrize(
    "payload",
    [
        {"faqs": [{"question": "Only a question"}]},
        {"faqs": [{"question": "Q", "answer": ""}]},
        {"faqs": "not a list"},
    ],
)
def test_bad_faqs_are_refused(admin_client, shop, payload):
    response = admin_client.patch(f"/api/admin/products/{shop['drill'].pk}/", payload, format="json")
    assert response.status_code == 400


def test_a_product_cannot_be_its_own_accessory(admin_client, shop):
    response = admin_client.patch(
        f"/api/admin/products/{shop['drill'].pk}/", {"accessories": [{"product": shop["drill"].pk}]}, format="json"
    )
    assert response.status_code == 400
    unknown = admin_client.patch(
        f"/api/admin/products/{shop['drill'].pk}/", {"accessories": [{"product": 999999}]}, format="json"
    )
    assert unknown.status_code == 400


def test_quote_reports_cod_with_the_same_rules_as_checkout(api_client, shop):
    url = f"/api/products/{shop['drill'].slug}/quote/"
    ok = api_client.get(url, {"quantity": 2}).json()["payment_options"]
    assert ok["online"] is True and ok["cod"]["available"] is True and ok["cod"]["max_order_value"] == "10000.00"
    settings = PaymentSettings.load()
    settings.cod_max_order_value = Decimal("1000")
    settings.save()
    over = api_client.get(url, {"quantity": 2}).json()["payment_options"]["cod"]
    assert over["available"] is False and over["reason_code"] == "cod_limit"
    settings.cod_max_order_value = None
    settings.save()
    DeliveryZone.objects.filter(pk=shop["near_zone"].pk).update(cod_enabled=False)
    zone_off = api_client.get(url, {"quantity": 1, "postal_code": NEAR_PIN}).json()["payment_options"]["cod"]
    assert zone_off["available"] is False and zone_off["reason_code"] == "cod_zone"
    assert api_client.get(url, {"quantity": 1}).json()["payment_options"]["cod"]["available"] is True


def test_quote_reports_the_free_delivery_threshold(api_client, shop, settings):
    url = f"/api/products/{shop['drill'].slug}/quote/"
    settings.FREE_DELIVERY_MIN_ORDER = Decimal("2500.00")
    assert api_client.get(url, {"quantity": 1}).json()["payment_options"]["free_delivery_from"] == "2500.00"
    DeliveryZone.objects.filter(pk=shop["near_zone"].pk).update(free_delivery_min_order=Decimal("999"))
    zoned = api_client.get(url, {"quantity": 1, "postal_code": NEAR_PIN}).json()["payment_options"]
    assert zoned["free_delivery_from"] == "999.00"


# --- Sitemap and security --------------------------------------------------------------------------


def test_sitemap_lists_only_public_pages(client, shop, settings):
    settings.FRONTEND_URL = "https://shop.example"
    draft, _ = create_product(name="Draft", published=False)
    body = client.get("/api/seo/sitemap.xml").content.decode()
    assert body.startswith("<?xml") and "<urlset" in body
    assert f"<loc>https://shop.example/p/{shop['drill'].slug}</loc>" in body
    assert f"/c/{shop['tools'].slug}</loc>" in body and "https://shop.example/brands</loc>" in body
    assert draft.slug not in body


def test_customers_cannot_change_catalogue_data(api_client, auth_client, shop):
    url = f"/api/products/{shop['drill'].slug}/"
    for client, expected in ((api_client, 401), (auth_client, 403)):
        assert client.patch(url, {"name": "Cheap"}, format="json").status_code == expected
        assert client.post("/api/products/", {"name": "New"}, format="json").status_code == expected
        assert client.delete(url).status_code == expected
        assert client.post("/api/brands/", {"name": "Mine"}, format="json").status_code == expected
        assert (
            client.patch(f"/api/admin/products/{shop['drill'].pk}/", {"faqs": []}, format="json").status_code
            == expected
        )
        assert client.get("/api/admin/products/").status_code == expected
        assert client.post("/api/inventory/adjust/", {}, format="json").status_code in (expected, 404, 405)
    # Prices sent by a client are never used: the quote ignores a price parameter.
    quote = api_client.get(f"{url}quote/", {"quantity": 1, "price": "1", "unit_price": "1"}).json()
    assert quote["unit_price"] == "900.00"
    product = Product.objects.get(pk=shop["drill"].pk)
    assert product.name == "Drill" and shop["drill_variant"].price == Decimal("900.00")
