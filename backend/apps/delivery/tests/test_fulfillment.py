"""Phase 9: delivery zones and the choice of fulfilment store(s) (apps/delivery/fulfillment.py)."""

from decimal import Decimal

import pytest

from apps.core.testing import add_stock, create_product
from apps.delivery.fulfillment import FeeRule, covering_candidates, plan_fulfillment, zone_covers
from apps.delivery.locations import Location
from apps.inventory.models import Inventory
from apps.stores.models import Store

from .helpers import ist, location_at, store_at, zone_for

pytestmark = pytest.mark.django_db

NOON = ist(2026, 9, 28, 12)


def _product(stock_by_store: dict, **kwargs):
    _, variant = create_product(**kwargs)
    for store, quantity in stock_by_store.items():
        add_stock(variant, quantity, store=store)
    return variant


# --- Zones ---------------------------------------------------------------------------------------


def test_zone_covers_by_radius_pin_list_and_polygon():
    store = store_at(postal_code="411038")
    zone = zone_for(store, radius="5", postal_codes="411052, 411029")
    assert zone_covers(zone, store, location_at(4.5))
    assert not zone_covers(zone, store, location_at(5.5, postal_code="411001"))
    assert zone_covers(zone, store, location_at(8, postal_code="411052"))  # listed PIN wins over distance
    assert zone_covers(zone, store, Location(None, "411029", "unknown"))
    assert zone_covers(zone, store, Location(None, "411038", "unknown"))  # the store's own PIN
    assert not zone_covers(zone, store, Location(None, "411001", "unknown"))
    assert not zone_covers(zone, store, Location(None, "", "unknown"))

    lat, lng = float(store.latitude), float(store.longitude)
    north_only = [[lat, lng - 0.05], [lat, lng + 0.05], [lat + 0.05, lng + 0.05], [lat + 0.05, lng - 0.05]]
    shaped = zone_for(store, radius="5", name="north", polygon=north_only)
    assert zone_covers(shaped, store, location_at(2))
    assert not zone_covers(shaped, store, location_at(-2))  # inside the radius, outside the polygon


def test_only_active_zones_of_open_fulfilment_stores_count():
    here = location_at(1)
    served = store_at()
    zone_for(served)
    inactive_zone = store_at()
    zone_for(inactive_zone, is_active=False)
    paused = store_at(accepts_orders=False)
    zone_for(paused)
    closed_down = store_at(is_active=False)
    zone_for(closed_down)
    warehouse = store_at(kind=Store.Kind.WAREHOUSE)
    zone_for(warehouse)
    store_at()  # no zone at all
    assert [store.pk for store, _ in covering_candidates(here)] == [served.pk]


def test_best_zone_of_a_store_prefers_fast_then_cheapest():
    store = store_at()
    zone_for(store, radius="10", name="wide", fast_delivery_enabled=False, delivery_fee_override=Decimal("20"))
    near = zone_for(store, radius="5", name="near")
    assert covering_candidates(location_at(3)) == [(store, near)]
    ((_, chosen),) = covering_candidates(location_at(8))
    assert chosen.name == "wide"


# --- Single store --------------------------------------------------------------------------------


def test_single_store_fulfilment():
    store = store_at()
    zone = zone_for(store)
    variant = _product({store: 5})
    plan = plan_fulfillment({variant.pk: 2}, location_at(2), now=NOON)
    assert plan.deliverable and not plan.is_split and plan.delivery_type == "fast"
    shipment = plan.primary
    assert shipment.store == store and shipment.zone == zone and shipment.lines == {variant.pk: 2}
    assert plan.latest.eta_minutes == 24 and plan.fast_unavailable_reason == ""


def test_the_fastest_valid_store_wins_not_the_first():
    far = store_at(0)  # created first: the old rule picked this one
    near = store_at(6)
    zone_for(far, radius="10")
    zone_for(near, radius="10")
    variant = _product({far: 5, near: 5})
    plan = plan_fulfillment({variant.pk: 1}, location_at(5), now=NOON)
    assert plan.primary.store == near
    assert plan_fulfillment({variant.pk: 1}, location_at(1), now=NOON).primary.store == far


def test_a_slower_kitchen_loses_to_a_farther_but_quicker_store():
    near_slow = store_at(0, avg_prep_minutes=40)
    far_quick = store_at(3, avg_prep_minutes=5)
    zone_for(near_slow, radius="10")
    zone_for(far_quick, radius="10")
    variant = _product({near_slow: 5, far_quick: 5})
    plan = plan_fulfillment({variant.pk: 1}, location_at(0.5), now=NOON)
    assert plan.primary.store == far_quick


def test_a_store_that_can_deliver_fast_beats_a_nearer_one_that_cannot():
    near_no_rider = store_at(0, riders=0)
    far_with_rider = store_at(3, riders=1)
    zone_for(near_no_rider, radius="10")
    zone_for(far_with_rider, radius="10")
    variant = _product({near_no_rider: 5, far_with_rider: 5})
    plan = plan_fulfillment({variant.pk: 1}, location_at(0.5), now=NOON)
    assert plan.primary.store == far_with_rider and plan.delivery_type == "fast"


def test_stores_without_enough_stock_are_skipped():
    near = store_at(0)
    far = store_at(3)
    zone_for(near, radius="10")
    zone_for(far, radius="10")
    variant = _product({near: 1, far: 5})
    assert plan_fulfillment({variant.pk: 1}, location_at(0.5), now=NOON).primary.store == near
    assert plan_fulfillment({variant.pk: 2}, location_at(0.5), now=NOON).primary.store == far
    Inventory.objects.filter(store=far).update(is_active=False)
    plan = plan_fulfillment({variant.pk: 2}, location_at(0.5), now=NOON)
    assert not plan.deliverable and plan.reason_code == "insufficient_stock"


def test_reserved_stock_is_not_counted():
    store = store_at()
    zone_for(store)
    variant = _product({store: 3})
    Inventory.objects.filter(store=store, variant=variant).update(available_quantity=1, reserved_quantity=2)
    assert plan_fulfillment({variant.pk: 1}, location_at(1), now=NOON).deliverable
    assert not plan_fulfillment({variant.pk: 2}, location_at(1), now=NOON).deliverable


def test_stock_in_a_store_that_does_not_serve_the_address_does_not_help():
    local_empty = store_at(0)
    distant_stocked = store_at(30)
    zone_for(local_empty)
    zone_for(distant_stocked)
    warehouse = store_at(1, kind=Store.Kind.WAREHOUSE)
    variant = _product({distant_stocked: 9, warehouse: 99})
    plan = plan_fulfillment({variant.pk: 1}, location_at(1), now=NOON)
    assert not plan.deliverable and plan.reason_code == "insufficient_stock"


# --- Outside the zones ---------------------------------------------------------------------------


def test_out_of_zone_address():
    store = store_at()
    zone_for(store)
    variant = _product({store: 5})
    plan = plan_fulfillment({variant.pk: 1}, location_at(9, postal_code="411014"), now=NOON)
    assert not plan.deliverable and plan.reason_code == "out_of_zone" and plan.shipments == []
    assert plan.message == "We don't deliver to PIN 411014 yet."


def test_unknown_location_and_empty_cart():
    store = store_at()
    zone_for(store)
    variant = _product({store: 5})
    plan = plan_fulfillment({variant.pk: 1}, Location(None, "", "unknown"), now=NOON)
    assert plan.reason_code == "location_unknown"
    assert plan_fulfillment({}, location_at(1), now=NOON).reason_code == "cart_empty"
    assert plan_fulfillment({variant.pk: 0}, location_at(1), now=NOON).reason_code == "cart_empty"


def test_without_an_address_only_stock_is_checked():
    store = store_at()  # no zone needed yet
    variant = _product({store: 5})
    plan = plan_fulfillment({variant.pk: 1}, None)
    assert plan.deliverable and plan.primary.store == store and plan.latest is None and plan.delivery_type is None


# --- Several stores ------------------------------------------------------------------------------


def test_order_is_split_when_no_store_has_everything(settings):
    a, b = store_at(0), store_at(3)
    zone_for(a, radius="10")
    zone_for(b, radius="10")
    drill = _product({a: 5}, name="Drill")
    tape = _product({b: 5}, name="Tape")
    saw = _product({a: 5, b: 5}, name="Saw")
    plan = plan_fulfillment({drill.pk: 1, tape.pk: 2, saw.pk: 1}, location_at(1), now=NOON)
    assert plan.deliverable and plan.is_split and len(plan.shipments) == 2
    lines = {s.store.pk: s.lines for s in plan.shipments}
    # The nearer store takes the two lines it can; a line is never divided between stores.
    assert lines == {a.pk: {drill.pk: 1, saw.pk: 1}, b.pk: {tape.pk: 2}}
    assert plan.primary.store == a
    assert plan.latest.delivery_at == max(s.estimate.delivery_at for s in plan.shipments)

    settings.SPLIT_FULFILLMENT_ENABLED = False
    blocked = plan_fulfillment({drill.pk: 1, tape.pk: 2}, location_at(1), now=NOON)
    assert not blocked.deliverable and blocked.reason_code == "insufficient_stock"


def test_one_store_is_preferred_over_a_split():
    a, b, everything = store_at(0), store_at(1), store_at(4)
    for store in (a, b, everything):
        zone_for(store, radius="10")
    drill = _product({a: 5, everything: 5}, name="Drill")
    tape = _product({b: 5, everything: 5}, name="Tape")
    plan = plan_fulfillment({drill.pk: 1, tape.pk: 1}, location_at(0.5), now=NOON)
    assert not plan.is_split and plan.primary.store == everything


def test_split_is_fast_only_if_every_shipment_is_fast():
    with_rider, without = store_at(0, riders=1), store_at(1, riders=0)
    zone_for(with_rider, radius="10")
    zone_for(without, radius="10")
    drill = _product({with_rider: 5}, name="Drill")
    tape = _product({without: 5}, name="Tape")
    plan = plan_fulfillment({drill.pk: 1, tape.pk: 1}, location_at(0.5), now=NOON)
    assert plan.is_split and plan.delivery_type == "standard"
    assert {s.estimate.delivery_type for s in plan.shipments} == {"fast", "standard"}
    assert plan.fast_unavailable_reason == "No delivery partner is available right now."
    assert plan.latest.delivery_type == "standard"


def test_split_is_limited_to_the_configured_number_of_shipments(settings):
    stores = [store_at(i) for i in range(3)]
    variants = []
    for index, store in enumerate(stores):
        zone_for(store, radius="10")
        variants.append(_product({store: 5}, name=f"Item {index}"))
    requirements = {v.pk: 1 for v in variants}
    assert len(plan_fulfillment(requirements, location_at(1), now=NOON).shipments) == 3
    settings.MAX_SHIPMENTS_PER_ORDER = 2
    plan = plan_fulfillment(requirements, location_at(1), now=NOON)
    assert not plan.deliverable and plan.reason_code == "insufficient_stock"


def test_a_line_is_never_divided_between_stores():
    a, b = store_at(0), store_at(1)
    zone_for(a, radius="10")
    zone_for(b, radius="10")
    variant = _product({a: 3, b: 3})
    plan = plan_fulfillment({variant.pk: 5}, location_at(0.5), now=NOON)
    assert not plan.deliverable and plan.reason_code == "insufficient_stock"


# --- Delivery fee --------------------------------------------------------------------------------


def test_fee_rule_comes_from_the_zone_or_the_settings(settings):
    from apps.orders.pricing import delivery_fee_for

    settings.DELIVERY_FEE = Decimal("40.00")
    settings.FREE_DELIVERY_MIN_ORDER = Decimal("499.00")
    store = store_at()
    plain = zone_for(store, name="plain")
    priced = zone_for(store, name="priced", delivery_fee_override=Decimal("25"), free_delivery_min_order=Decimal("999"))
    free = zone_for(store, name="free", delivery_fee_override=Decimal("0"))

    assert FeeRule.for_zone(plain) == FeeRule.default() == FeeRule(Decimal("40.00"), Decimal("499.00"))
    assert FeeRule.for_zone(None) == FeeRule.default()
    rule = FeeRule.for_zone(priced)
    assert rule == FeeRule(Decimal("25.00"), Decimal("999.00"))
    assert delivery_fee_for(Decimal("600"), rule) == Decimal("25.00")
    assert delivery_fee_for(Decimal("999"), rule) == Decimal("0.00")
    assert delivery_fee_for(Decimal("600")) == Decimal("0.00")  # global rule: free from 499
    assert delivery_fee_for(Decimal("100")) == Decimal("40.00")
    assert delivery_fee_for(Decimal("0"), rule) == Decimal("0.00")
    assert delivery_fee_for(Decimal("100"), FeeRule.for_zone(free)) == Decimal("0.00")
