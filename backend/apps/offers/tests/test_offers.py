"""Phase 6: automatic offers engine, stacking with coupons, and the cart/checkout/order/catalog surfaces."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.testing import create_address, create_category, create_coupon, create_product, create_store
from apps.offers.engine import apply_offers, load_active_offers
from apps.offers.models import CouponRedemption, Offer
from apps.orders.models import Order
from apps.orders.pricing import line_from_variant, price_lines

pytestmark = pytest.mark.django_db
D = Decimal


def create_offer(name="Offer", *, categories=(), products=(), **kwargs):
    defaults = {
        "discount_type": "percent",
        "value": D("10"),
        "starts_at": timezone.now() - timedelta(days=1),
        "ends_at": timezone.now() + timedelta(days=1),
    }
    defaults.update(kwargs)
    offer = Offer.objects.create(name=name, **defaults)
    offer.categories.set(categories)
    offer.products.set(products)
    return offer


@pytest.fixture
def cat():
    tools = create_category("Tools")
    drills = create_category("Drills", parent=tools)
    plumbing = create_category("Plumbing")
    store = create_store()
    _, drill = create_product(
        name="Drill", price="1180.00", mrp="1400.00", category=tools, subcategory=drills, stock=20, store=store
    )
    _, hammer = create_product(name="Hammer", price="300.00", mrp="300.00", category=tools, stock=20, store=store)
    _, tap = create_product(name="Tap", price="500.00", mrp="600.00", category=plumbing, stock=20, store=store)
    return {"tools": tools, "drills": drills, "plumbing": plumbing, "drill": drill, "hammer": hammer, "tap": tap}


def lines_for(*pairs):
    return [line_from_variant(variant, qty) for variant, qty in pairs]


# --- Engine rules ------------------------------------------------------------------------------


def test_no_offers_changes_nothing(cat):
    result = apply_offers(lines_for((cat["drill"], 1)))
    assert result.applied == [] and result.line_discounts == {} and result.total == D("0.00")


def test_category_offer_matches_subcategories_and_is_capped(cat):
    create_offer("Tools", categories=[cat["tools"]], value=D("20"), max_discount_amount=D("250"))
    result = apply_offers(lines_for((cat["drill"], 1), (cat["hammer"], 1), (cat["tap"], 1)))
    (applied,) = result.applied
    assert applied.eligible_amount == D("1480.00")  # drill (subcategory) + hammer; tap is plumbing
    assert applied.discount == D("250.00")  # 20% = 296 → capped at 250
    assert sum(result.line_discounts.values()) == D("250.00")
    assert cat["tap"].id not in result.line_discounts


def test_fixed_offer_never_exceeds_eligible_amount(cat):
    create_offer("Big", products=[cat["hammer"].product], discount_type="fixed", value=D("1000"))
    result = apply_offers(lines_for((cat["hammer"], 1)))
    assert result.total == D("300.00")


def test_whole_cart_offer_when_no_targets(cat):
    create_offer("Everything", value=D("5"))
    assert apply_offers(lines_for((cat["drill"], 1), (cat["tap"], 1))).total == D("84.00")  # 5% of 1680


def test_minimum_spend_counts_only_the_offer_lines_and_reports_shortfall(cat):
    create_offer("Tools 2k", categories=[cat["tools"]], min_order_value=D("2000"))
    result = apply_offers(lines_for((cat["drill"], 1), (cat["tap"], 2)))  # cart 2180, but tools only 1180
    assert result.applied == []
    (missed,) = result.missed
    assert missed.shortfall == D("820.00") and missed.offer.name == "Tools 2k"
    result = apply_offers(lines_for((cat["drill"], 1), (cat["hammer"], 3)))  # tools 2080
    assert result.total == D("208.00") and result.missed == []


def test_lower_priority_number_wins_overlaps_one_offer_per_line(cat):
    create_offer("General", categories=[cat["tools"]], value=D("5"), priority=50)
    create_offer("Drill special", products=[cat["drill"].product], value=D("20"), priority=10)
    result = apply_offers(lines_for((cat["drill"], 1), (cat["hammer"], 1)))
    by_name = {a.offer.name: a for a in result.applied}
    assert by_name["Drill special"].discount == D("236.00")  # 20% of drill only
    assert by_name["General"].discount == D("15.00")  # 5% of hammer only — the drill line is taken
    assert by_name["General"].variant_ids == (cat["hammer"].id,)


def test_offer_missing_its_minimum_releases_lines_to_the_next_offer(cat):
    create_offer("Premium", categories=[cat["tools"]], value=D("20"), min_order_value=D("5000"), priority=1)
    create_offer("Basic", categories=[cat["tools"]], value=D("5"), priority=2)
    result = apply_offers(lines_for((cat["drill"], 1)))
    assert [a.offer.name for a in result.applied] == ["Basic"]
    assert result.total == D("59.00")
    assert [m.offer.name for m in result.missed] == ["Premium"]


def test_inactive_expired_and_future_offers_are_ignored(cat):
    now = timezone.now()
    create_offer("Off", is_active=False)
    create_offer("Old", ends_at=now - timedelta(minutes=1))
    create_offer("Soon", starts_at=now + timedelta(hours=1), ends_at=None)
    create_offer("Open-ended", ends_at=None, value=D("1"))
    assert [r.name for r in load_active_offers()] == ["Open-ended"]


def test_discount_spread_is_exact_and_badges_read_well(cat):
    offer = create_offer("Thirds", categories=[cat["tools"]], discount_type="fixed", value=D("100"))
    result = apply_offers(lines_for((cat["drill"], 1), (cat["hammer"], 1)))
    assert sum(result.line_discounts.values()) == D("100.00")
    assert all(v >= 0 for v in result.line_discounts.values())
    rule = next(r for r in load_active_offers() if r.id == offer.id)
    assert rule.badge == "₹100 off"
    create_offer("Pct", value=D("12.50"), max_discount_amount=D("300.00"))
    assert next(r for r in load_active_offers() if r.name == "Pct").badge == "12.5% off (up to ₹300)"


# --- Pricing: offers + coupon + tax ----------------------------------------------------------------


def test_coupon_applies_after_offers_and_tax_uses_net_line_amounts(cat, settings):
    settings.FREE_DELIVERY_MIN_ORDER = D("499.00")
    create_offer("Tools", categories=[cat["tools"]], value=D("10"))
    coupon = create_coupon("EXTRA", value=D("10"))
    pricing = price_lines(lines_for((cat["drill"], 1)), coupon=coupon)
    t = pricing.totals
    assert (t.subtotal, t.offer_discount, t.coupon_discount) == (D("1180.00"), D("118.00"), D("106.20"))
    assert t.discount_total == D("224.20") and t.grand_total == D("955.80")
    assert t.tax_total == D("145.80")  # 955.80 × 18/118
    assert t.savings_vs_mrp == D("444.20")  # (1400-1180) MRP saving + 224.20 discounts


def test_coupon_minimum_is_checked_after_offers(cat):
    create_offer("Tools", categories=[cat["tools"]], value=D("20"))
    coupon = create_coupon("MIN1000", min_order_value=D("1000"))
    from apps.offers.services import CouponError

    with pytest.raises(CouponError) as exc:
        price_lines(lines_for((cat["drill"], 1)), coupon=coupon)  # 1180 - 236 = 944 < 1000
    assert exc.value.error_code == "coupon_min_order"


# --- API surfaces --------------------------------------------------------------------------------------


def test_cart_shows_applied_offers_and_unlock_hints(auth_client, cat):
    create_offer("Tools", categories=[cat["tools"]], value=D("10"), description="10% off tools")
    create_offer(
        "Plumbing 1k", categories=[cat["plumbing"]], discount_type="fixed", value=D("50"), min_order_value=D("1000")
    )
    auth_client.post("/api/cart/items/", {"variant_id": cat["drill"].id, "quantity": 1}, format="json")
    cart = auth_client.post("/api/cart/items/", {"variant_id": cat["tap"].id, "quantity": 1}, format="json").json()
    assert cart["totals"]["offer_discount"] == "118.00" and cart["totals"]["coupon_discount"] == "0.00"
    assert cart["totals"]["grand_total"] == "1562.00"  # 1680 - 118
    (applied,) = cart["offers"]["applied"]
    assert applied["name"] == "Tools" and applied["badge"] == "10% off" and applied["variant_ids"] == [cat["drill"].id]
    (missed,) = cart["offers"]["missed"]
    assert missed["name"] == "Plumbing 1k" and missed["shortfall"] == "500.00"


def test_order_records_offer_and_coupon_breakdown(auth_client, user, cat):
    create_offer("Tools", categories=[cat["tools"]], value=D("10"))
    create_coupon("EXTRA", value=D("10"))
    auth_client.post("/api/cart/items/", {"variant_id": cat["drill"].id, "quantity": 1}, format="json")
    address = create_address(user)
    preview = auth_client.post(
        "/api/checkout/preview/", {"address_id": address.id, "coupon_code": "EXTRA"}, format="json"
    ).json()
    assert preview["offers"]["applied"][0]["discount"] == "118.00"
    assert preview["coupon"]["discount"] == "106.20" and preview["totals"]["grand_total"] == "955.80"

    res = auth_client.post(
        "/api/orders/",
        {"address_id": address.id, "payment_method": "cod", "coupon_code": "EXTRA", "expected_total": "955.80"},
        format="json",
    )
    assert res.status_code == 201, res.json()
    data = res.json()
    assert (data["offer_discount"], data["coupon_discount"], data["discount_total"]) == ("118.00", "106.20", "224.20")
    assert data["applied_offers"] == [
        {
            "id": data["applied_offers"][0]["id"],
            "name": "Tools",
            "badge": "10% off",
            "discount": "118.00",
            "skus": [cat["drill"].sku],
        }
    ]
    assert data["items"][0]["offer_discount"] == "118.00"
    assert CouponRedemption.objects.get().discount_amount == D("106.20")  # coupon portion only


def test_offer_ending_between_preview_and_order_is_caught(auth_client, user, cat):
    offer = create_offer("Tools", categories=[cat["tools"]], value=D("10"))
    auth_client.post("/api/cart/items/", {"variant_id": cat["drill"].id, "quantity": 1}, format="json")
    address = create_address(user)
    shown = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    Offer.objects.filter(pk=offer.pk).update(is_active=False)
    res = auth_client.post(
        "/api/orders/",
        {"address_id": address.id, "payment_method": "cod", "expected_total": shown["totals"]["grand_total"]},
        format="json",
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "totals_changed"
    assert Order.objects.count() == 0


def test_products_show_their_offer_badge(api_client, cat):
    create_offer("Tools week", categories=[cat["tools"]], value=D("10"))
    listing = api_client.get("/api/products/").json()["results"]
    badges = {p["name"]: p["offer"] for p in listing}
    assert badges["Drill"]["badge"] == "10% off" and badges["Drill"]["name"] == "Tools week"
    assert badges["Tap"] is None
    detail = api_client.get(f"/api/products/{cat['hammer'].product.slug}/").json()
    assert detail["offer"]["name"] == "Tools week"


def test_public_offer_list(api_client, cat):
    create_offer("Tools week", categories=[cat["tools"]], value=D("10"), description="On all tools")
    create_offer("Hidden", is_active=False)
    data = api_client.get("/api/offers/").json()
    assert [o["name"] for o in data] == ["Tools week"]
    assert data[0]["categories"] == [{"name": "Tools", "slug": cat["tools"].slug}]
    assert data[0]["applies_to_everything"] is False


def test_available_coupons_are_opt_in_personal_and_explain_eligibility(auth_client, api_client, user, cat):
    create_coupon("PUBLIC10", value=D("10"), show_in_checkout=True, description="10% off")
    create_coupon("BIG500", discount_type="fixed", value=D("500"), min_order_value=D("5000"), show_in_checkout=True)
    create_coupon("SECRET", value=D("50"))  # not advertised
    used = create_coupon("ONCEONLY", value=D("5"), show_in_checkout=True, per_customer_limit=1)
    order = Order.objects.create(
        order_number="ODUSED1", user=user, address_snapshot={}, payment_method="cod",
        subtotal=0, mrp_total=0, discount_total=0, delivery_fee=0, tax_total=0, grand_total=0,
    )  # fmt: skip
    CouponRedemption.objects.create(coupon=used, user=user, order=order, discount_amount=D("1"))

    assert api_client.get("/api/coupons/available/").status_code == 401
    empty = auth_client.get("/api/coupons/available/").json()
    assert {c["code"] for c in empty} == {"PUBLIC10", "BIG500"}
    assert all(not c["applicable"] and "Add items" in c["message"] for c in empty)

    auth_client.post("/api/cart/items/", {"variant_id": cat["drill"].id, "quantity": 1}, format="json")
    rows = auth_client.get("/api/coupons/available/").json()
    assert [c["code"] for c in rows] == ["PUBLIC10", "BIG500"]  # applicable first
    assert rows[0]["applicable"] is True and rows[0]["discount"] == "118.00"
    assert rows[1]["applicable"] is False and "minimum order" in rows[1]["message"]


def test_customers_cannot_manage_offers(auth_client):
    assert auth_client.post("/api/offers/", {"name": "Mine"}, format="json").status_code == 405
