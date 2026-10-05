"""Phase 15 checkout rules: advanced offers (quantity, first order, festival, free delivery, usage
limits), free-delivery rules and cash-on-delivery eligibility — all through the one pricing engine."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.carts.services import add_item, clear_cart
from apps.catalog.services import set_price_tiers
from apps.core.exceptions import ServiceError
from apps.core.testing import create_address, create_category, create_product, create_store
from apps.delivery.models import DeliveryZone, FreeDeliveryRule
from apps.offers.models import Offer, OfferRedemption
from apps.orders.pricing import line_from_variant, price_lines
from apps.orders.services import TotalsChanged, cancel_order_by_customer, place_order
from apps.payments.cod_rules import format_inr
from apps.payments.models import PaymentSettings

pytestmark = pytest.mark.django_db
D = Decimal


def make_offer(name="Offer", *, categories=(), products=(), **kwargs):
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
def shop(settings):
    settings.DELIVERY_FEE = D("40.00")
    settings.FREE_DELIVERY_MIN_ORDER = D("5000.00")
    civil = create_category("Civil")
    cement_cat = create_category("Cement", parent=civil)
    tools = create_category("Tools")
    store = create_store()
    _, cement = create_product(name="Cement", price="400.00", mrp="450.00", category=cement_cat, stock=500, store=store)
    _, gloves = create_product(name="Gloves", price="100.00", mrp="120.00", category=tools, stock=500, store=store)
    return {
        "civil": civil,
        "cement_cat": cement_cat,
        "tools": tools,
        "store": store,
        "cement": cement,
        "gloves": gloves,
    }


def order(user, *pairs, method="cod", **kwargs):
    clear_cart(user)
    for variant, quantity in pairs:
        add_item(user, variant.id, quantity)
    return place_order(user=user, address_id=create_address(user).id, payment_method=method, **kwargs)[0]


# --- Advanced offers -----------------------------------------------------------------------------


def test_quantity_offer_counts_only_lines_with_enough_units(user, shop):
    make_offer("Gloves 10+", categories=[shop["tools"]], value=D("5"), min_quantity=10)
    few = price_lines([line_from_variant(shop["gloves"], 9)], user=user)
    assert few.totals.offer_discount == D("0.00")
    assert few.offers.missed[0].units_short == 1  # "add 1 more"
    many = price_lines([line_from_variant(shop["gloves"], 10)], user=user)
    assert many.totals.offer_discount == D("50.00")


def test_quantity_offer_and_bulk_tier_stack_on_the_tier_price(user, shop):
    set_price_tiers(shop["cement"], [{"min_quantity": 10, "unit_price": "380"}])
    make_offer("Cement 10+", categories=[shop["civil"]], value=D("5"), min_quantity=10)  # department covers Cement
    totals = price_lines([line_from_variant(shop["cement"], 10)], user=user).totals
    assert totals.subtotal == D("3800.00") and totals.offer_discount == D("190.00")
    assert totals.grand_total == D("3650.00")  # 3610 + ₹40 delivery (below the ₹5,000 threshold)
    assert totals.grand_total > 0


def test_first_order_offer_applies_only_before_the_first_order(user, shop):
    make_offer("Welcome", value=D("10"), max_prior_orders=0)
    lines = [line_from_variant(shop["gloves"], 2)]
    assert price_lines(lines, user=None).totals.offer_discount == D("0.00")  # visitors don't get it
    assert price_lines(lines, user=user).totals.offer_discount == D("20.00")
    first = order(user, (shop["gloves"], 2))
    assert first.offer_discount == D("20.00")
    assert price_lines(lines, user=user).totals.offer_discount == D("0.00")
    cancel_order_by_customer(first, user=user, reason="Changed my mind")  # a cancelled order doesn't count
    assert price_lines(lines, user=user).totals.offer_discount == D("20.00")


def test_festival_offer_runs_only_in_its_dates_and_says_so(api_client, user, shop):
    festival = make_offer(
        "Diwali tools",
        categories=[shop["tools"]],
        value=D("8"),
        campaign="Diwali",
        starts_at=timezone.now() + timedelta(days=2),
        ends_at=timezone.now() + timedelta(days=5),
    )
    assert price_lines([line_from_variant(shop["gloves"], 1)], user=user).totals.offer_discount == D("0.00")
    Offer.objects.filter(pk=festival.pk).update(starts_at=timezone.now() - timedelta(minutes=1))
    assert price_lines([line_from_variant(shop["gloves"], 1)], user=user).totals.offer_discount == D("8.00")
    live = api_client.get("/api/offers/").json()
    assert live[0]["campaign"] == "Diwali" and live[0]["benefit"] == "discount"


def test_free_delivery_offer(user, shop):
    make_offer("Cement ships free", benefit="free_delivery", value=D("0"), categories=[shop["cement_cat"]],
               min_order_value=D("1000"))  # fmt: skip
    small = price_lines([line_from_variant(shop["cement"], 2)], user=user)
    assert small.totals.delivery_fee == D("40.00") and small.offers.missed[0].shortfall == D("200.00")
    big = price_lines([line_from_variant(shop["cement"], 3)], user=user)
    assert big.totals.delivery_fee == D("0.00") and big.totals.free_delivery_reason == "Cement ships free"
    assert big.totals.offer_discount == D("0.00")
    placed = order(user, (shop["cement"], 3))
    assert placed.delivery_fee == D("0.00") and placed.free_delivery_reason == "Cement ships free"
    assert placed.applied_offers[0]["benefit"] == "free_delivery"


def test_usage_limit_and_per_customer_limit(user, other_user, shop):
    capped = make_offer("Two orders only", value=D("10"), usage_limit=2)
    once = make_offer(
        "Once each", products=[shop["cement"].product], value=D("5"), per_customer_limit=1, priority=10
    )  # wins the cement line over "Two orders only" while it has uses left
    first = order(user, (shop["gloves"], 1), (shop["cement"], 1))
    assert {a["name"] for a in first.applied_offers} == {"Two orders only", "Once each"}
    second = order(user, (shop["gloves"], 1), (shop["cement"], 1))
    assert [a["name"] for a in second.applied_offers] == ["Two orders only"]  # "Once each" used up for this customer
    third = order(other_user, (shop["gloves"], 1))
    assert third.applied_offers == []  # the global limit of 2 is reached
    capped.refresh_from_db()
    assert capped.used_count == 2
    # Cancelling gives the use back.
    cancel_order_by_customer(first, user=user, reason="No longer needed")
    capped.refresh_from_db()
    assert capped.used_count == 1 and not OfferRedemption.objects.filter(order=first).exists()
    assert price_lines([line_from_variant(shop["gloves"], 1)], user=other_user).totals.offer_discount == D("10.00")
    once.refresh_from_db()
    assert once.used_count == 0


def test_offer_running_out_during_checkout_is_refused(user, shop):
    offer = make_offer("Last one", value=D("10"), usage_limit=1)
    add_item(user, shop["gloves"].id, 1)
    address = create_address(user)
    # Someone else takes the last use between pricing and the lock.
    original = Offer.objects.select_for_update

    def exhausted(*args, **kwargs):
        Offer.objects.filter(pk=offer.pk).update(used_count=1)
        return original(*args, **kwargs)

    Offer.objects.select_for_update = exhausted
    try:
        with pytest.raises(TotalsChanged):
            place_order(user=user, address_id=address.id, payment_method="cod")
    finally:
        Offer.objects.select_for_update = original
    assert not user.orders.exists()


def test_offers_never_make_a_line_negative(user, shop):
    make_offer("Big fixed", discount_type="fixed", value=D("5000"))
    totals = price_lines([line_from_variant(shop["gloves"], 1)], user=user).totals
    assert totals.offer_discount == D("100.00") and totals.grand_total == D("0.00")


def test_dashboard_offer_fields(admin_client, shop):
    payload = {
        "name": "First order delivery",
        "benefit": "free_delivery",
        "max_prior_orders": 0,
        "starts_at": timezone.now().isoformat(),
    }
    created = admin_client.post("/api/admin/offers/", payload, format="json")
    assert created.status_code == 201, created.data
    assert created.data["conditions"] == ["First order only"] and created.data["summary"].startswith("Free delivery")
    bad = admin_client.post(
        "/api/admin/offers/",
        {"name": "No value", "discount_type": "percent", "value": "0", "starts_at": timezone.now().isoformat()},
        format="json",
    )
    assert bad.status_code == 400
    quantity = admin_client.post(
        "/api/admin/offers/",
        {"name": "Bags", "discount_type": "percent", "value": "5", "min_quantity": 10, "campaign": "Monsoon",
         "usage_limit": 100, "per_customer_limit": 2, "starts_at": timezone.now().isoformat()},
        format="json",
    )  # fmt: skip
    assert quantity.status_code == 201 and quantity.data["remaining_uses"] == 100
    assert quantity.data["summary"].startswith("Monsoon: 5% off")


# --- Free-delivery rules -------------------------------------------------------------------------


def make_rule(name="Rule", threshold="1000", *, zones=(), categories=(), products=(), **kwargs):
    defaults = {"starts_at": timezone.now() - timedelta(days=1)}
    defaults.update(kwargs)
    rule = FreeDeliveryRule.objects.create(name=name, threshold=D(threshold), **defaults)
    rule.zones.set(zones)
    rule.categories.set(categories)
    rule.products.set(products)
    return rule


def test_zone_threshold_still_works_and_shows_add_more(auth_client, user, shop):
    add_item(user, shop["gloves"].id, 10)  # ₹1,000
    preview = auth_client.post("/api/checkout/preview/", {"address_id": create_address(user).id}, format="json").json()
    assert preview["totals"]["delivery_fee"] == "40.00"
    assert preview["delivery"]["amount_to_free_delivery"] == "4000.00"
    assert preview["delivery"]["free_delivery_min_order"] == "5000.00"


def test_rule_threshold_for_eligible_categories_only(auth_client, user, shop):
    make_rule("Cement from ₹2,000", "2000", categories=[shop["civil"]])
    add_item(user, shop["gloves"].id, 20)  # ₹2,000 of gloves doesn't count
    add_item(user, shop["cement"].id, 4)  # ₹1,600 of cement
    address = create_address(user)
    preview = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    assert preview["totals"]["delivery_fee"] == "40.00"
    assert preview["totals"]["amount_to_free_delivery"] == "400.00"  # nearer than ₹1,400 to the ₹5,000 threshold
    assert preview["delivery"]["free_delivery_hint"] == "Civil"
    add_item(user, shop["cement"].id, 1)
    preview = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    assert preview["totals"]["delivery_fee"] == "0.00"
    assert preview["totals"]["free_delivery"] is True
    assert preview["delivery"]["free_delivery_reason"] == "Cement from ₹2,000"


def test_rule_dates_active_flag_and_zone(user, shop):
    rule = make_rule("Weekend", "500", ends_at=timezone.now() - timedelta(minutes=1))
    zone = DeliveryZone.objects.get(store=shop["store"])
    other_zone = DeliveryZone.objects.create(store=create_store(), name="Elsewhere")
    lines = [line_from_variant(shop["gloves"], 6)]  # ₹600
    from apps.delivery.fulfillment import FeeRule

    assert price_lines(lines, fee_rule=FeeRule.for_zone(zone), user=user).totals.delivery_fee == D("40.00")
    FreeDeliveryRule.objects.filter(pk=rule.pk).update(ends_at=None)
    assert price_lines(lines, fee_rule=FeeRule.for_zone(zone), user=user).totals.delivery_fee == D("0.00")
    rule.zones.set([other_zone])
    assert price_lines(lines, fee_rule=FeeRule.for_zone(zone), user=user).totals.delivery_fee == D("40.00")
    rule.zones.set([zone])
    assert price_lines(lines, fee_rule=FeeRule.for_zone(zone), user=user).totals.delivery_fee == D("0.00")
    FreeDeliveryRule.objects.filter(pk=rule.pk).update(is_active=False)
    switched_off = price_lines(lines, fee_rule=FeeRule.for_zone(zone), user=user).totals
    assert switched_off.delivery_fee == D("40.00") and switched_off.free_delivery_reason == ""


def test_order_records_why_delivery_was_free(user, shop):
    make_rule("Everything from ₹500", "500")
    placed = order(user, (shop["gloves"], 6))
    assert placed.delivery_fee == D("0.00") and placed.free_delivery_reason == "Everything from ₹500"


def test_dashboard_free_delivery_rules(admin_client, staff_client, shop):
    zone = DeliveryZone.objects.get(store=shop["store"])
    payload = {
        "name": "Cement",
        "threshold": "2000",
        "zones": [zone.id],
        "categories": [shop["cement_cat"].id],
        "starts_at": timezone.now().isoformat(),
    }
    created = admin_client.post("/api/admin/free-delivery-rules/", payload, format="json")
    assert created.status_code == 201, created.data
    assert created.data["state"] == "live" and created.data["summary"].startswith("Free delivery from ₹2,000 of Cement")
    bad = admin_client.post(
        "/api/admin/free-delivery-rules/",
        {**payload, "ends_at": (timezone.now() - timedelta(days=1)).isoformat()},
        format="json",
    )
    assert bad.status_code == 400
    assert staff_client.get("/api/admin/free-delivery-rules/").status_code == 403


# --- Cash on delivery ----------------------------------------------------------------------------


def cod_option(preview):
    return next(m for m in preview["payment_methods"] if m["value"] == "cod")


def test_cod_limit_is_10000_by_default(auth_client, user, shop):
    assert PaymentSettings.load().cod_max_order_value == D("10000.00")
    add_item(user, shop["cement"].id, 25)  # ₹10,000 exactly (free delivery from ₹5,000)
    address = create_address(user)
    preview = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    assert preview["totals"]["grand_total"] == "10000.00" and cod_option(preview)["available"] is True
    add_item(user, shop["cement"].id, 1)
    preview = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    cod = cod_option(preview)
    assert cod["available"] is False and cod["reason_code"] == "cod_limit"
    assert cod["message"] == "Cash on Delivery isn't available for orders above ₹10,000."
    refused = auth_client.post("/api/orders/", {"address_id": address.id, "payment_method": "cod"}, format="json")
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "cod_unavailable"
    online = auth_client.post("/api/orders/", {"address_id": address.id, "payment_method": "online"}, format="json")
    assert online.status_code == 201


def test_cod_limit_is_configurable_and_can_be_switched_off(user, shop):
    settings = PaymentSettings.load()
    settings.cod_max_order_value = D("500.00")
    settings.save()
    with pytest.raises(ServiceError) as exc:
        order(user, (shop["gloves"], 6))
    assert "₹500" in str(exc.value.detail)
    settings.cod_max_order_value = None  # no limit
    settings.save()
    assert order(user, (shop["gloves"], 6)).payment_method == "cod"
    settings.cod_enabled = False
    settings.save()
    with pytest.raises(ServiceError) as exc:
        order(user, (shop["gloves"], 1))
    assert exc.value.error_code == "cod_unavailable"


def test_cod_off_for_a_store_or_a_zone(auth_client, user, shop):
    add_item(user, shop["gloves"].id, 1)
    address = create_address(user)
    shop["store"].cod_enabled = False
    shop["store"].save()
    preview = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    assert cod_option(preview)["reason_code"] == "cod_store"
    shop["store"].cod_enabled = True
    shop["store"].save()
    DeliveryZone.objects.filter(store=shop["store"]).update(cod_enabled=False)
    preview = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    assert cod_option(preview)["reason_code"] == "cod_zone"
    refused = auth_client.post("/api/orders/", {"address_id": address.id, "payment_method": "cod"}, format="json")
    assert refused.status_code == 400
    DeliveryZone.objects.filter(store=shop["store"]).update(cod_enabled=True)
    accepted = auth_client.post("/api/orders/", {"address_id": address.id, "payment_method": "cod"}, format="json")
    assert accepted.status_code == 201 and accepted.json()["status"] == "confirmed"


def test_payment_settings_permissions_and_audit(api_client, auth_client, staff_client, admin_client):
    url = "/api/admin/payment-settings/"
    assert api_client.get(url).status_code == 401
    assert auth_client.get(url).status_code == 403
    assert staff_client.get(url).json()["cod_max_order_value"] == "10000.00"
    assert staff_client.patch(url, {"cod_max_order_value": "5000"}, format="json").status_code == 403
    changed = admin_client.patch(url, {"cod_max_order_value": "15000"}, format="json")
    assert changed.status_code == 200 and changed.json()["cod_max_order_value"] == "15000.00"
    assert admin_client.patch(url, {"cod_max_order_value": "0"}, format="json").status_code == 400
    from apps.core.models import AuditLog

    assert AuditLog.objects.filter(action="payment_settings.update").exists()


def test_inr_format():
    assert format_inr(D("10000")) == "₹10,000"
    assert format_inr(D("125000")) == "₹1,25,000"
    assert format_inr(D("499.50")) == "₹499.50"
