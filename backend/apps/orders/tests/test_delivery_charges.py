"""Distance-based delivery charges, Bengaluru-wide coverage, "first N orders free" and the unloading service."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.testing import create_address, create_product
from apps.delivery.fulfillment import distance_fee
from apps.delivery.models import CoverageReview, DeliveryCharges, DeliveryZone, PinCode, ServiceArea
from apps.orders.models import Order
from apps.stores.models import Store

pytestmark = pytest.mark.django_db

JAYANAGAR = ("12.925000", "77.593800")
NEAR = {"latitude": "12.906300", "longitude": "77.585700", "postal_code": "560078", "area": "JP Nagar"}  # ~2 km
FAR = {"latitude": "13.100700", "longitude": "77.596300", "postal_code": "560064", "area": "Yelahanka"}  # ~20 km


def bands(**extra) -> DeliveryCharges:
    return DeliveryCharges(
        distance_bands=[{"up_to_km": "3", "fee": "30"}, {"up_to_km": "5", "fee": "50"},
                        {"up_to_km": "8", "fee": "80"}, {"up_to_km": "12", "fee": "120"}],
        **extra,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("km", "fee"),
    [
        (0.5, "30"),
        (3, "30"),
        (3.01, "50"),
        (5, "50"),
        (7.9, "80"),
        (8, "80"),
        (11.2, "120"),
        (12, "120"),
        (19.5, "120"),
    ],
)
def test_distance_bands(km, fee):
    assert distance_fee(km, bands()) == Decimal(fee)


def test_beyond_the_last_band_adds_the_per_km_rate_for_each_started_km():
    charges = bands(extra_per_km=Decimal("10"))
    assert distance_fee(12.4, charges) == Decimal("130.00")  # 1 started km above 12
    assert distance_fee(20, charges) == Decimal("200.00")


def test_no_bands_means_the_flat_fee():
    assert distance_fee(7, DeliveryCharges(distance_bands=[])) is None


@pytest.mark.parametrize(
    "raw",
    [[{"up_to_km": "0", "fee": "10"}], [{"up_to_km": "3"}], [{"up_to_km": "3", "fee": "-1"}],
     [{"up_to_km": "3", "fee": "10"}, {"up_to_km": "3", "fee": "20"}], "3:30"],
)  # fmt: skip
def test_invalid_bands_are_refused(raw):
    with pytest.raises(ValidationError):
        DeliveryCharges(distance_bands=raw).full_clean()


@pytest.fixture
def city(settings, user):
    settings.DELIVERY_RESTRICT_TO_SERVICE_AREAS = True
    area = ServiceArea.objects.get(name="Bengaluru")
    store = Store.objects.create(
        name="Kalkere Store", code="BLR-T", kind=Store.Kind.STORE, address_line1="1 Test Road", city="Bengaluru",
        state="Karnataka", postal_code="560041", latitude=JAYANAGAR[0], longitude=JAYANAGAR[1], own_riders=2,
    )  # fmt: skip
    zone = DeliveryZone.objects.create(store=store, name="Bengaluru", radius_km=Decimal("3"), service_area=area)
    _, drill = create_product(name="Drill", price="300.00", mrp="400.00", stock=50, store=store)
    for pin in (NEAR, FAR):
        PinCode.objects.create(postal_code=pin["postal_code"], area=pin["area"], city="Bengaluru",
                               latitude=pin["latitude"], longitude=pin["longitude"])  # fmt: skip

    def address(where, **extra):
        return create_address(
            user, city="Bengaluru", state="Karnataka", postal_code=where["postal_code"],
            latitude=where["latitude"], longitude=where["longitude"], **extra,
        )  # fmt: skip

    return {"store": store, "zone": zone, "drill": drill, "near": address(NEAR), "far": address(FAR)}


def _add(client, variant, quantity=1):
    assert (
        client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": quantity}, format="json").status_code
        == 201
    )


def _preview(client, address, **body):
    res = client.post("/api/checkout/preview/", {"address_id": address.id, **body}, format="json")
    assert res.status_code == 200, res.json()
    return res.json()


def _order(client, address, key=None, **body):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return client.post(
        "/api/orders/", {"address_id": address.id, "payment_method": "cod", **body}, format="json", **headers
    )


@pytest.mark.delivery_charges
def test_delivery_across_the_city_is_charged_by_distance_beyond_the_zone_radius(auth_client, city):
    DeliveryCharges.objects.update_or_create(pk=1, defaults={"free_first_orders": 0})
    _add(auth_client, city["drill"])
    near = _preview(auth_client, city["near"])["delivery"]
    far = _preview(auth_client, city["far"])["delivery"]
    # The far address is ~20 km away, well beyond the zone's 3 km radius, and still served (city-wide).
    assert near["available"] and far["available"]
    assert far["distance_km"] > 12 > near["distance_km"]
    # Shop policy bands: ₹40 up to 5 km, ₹80 beyond.
    assert Decimal(near["fee"]) in {Decimal("40"), Decimal("80")} and Decimal(far["fee"]) == Decimal("80")
    # Straight line × road factor is an estimate, never presented as a routed distance.
    assert near["distance_estimated"] is True and far["distance_estimated"] is True
    DeliveryCharges.objects.filter(pk=1).update(extra_per_km=Decimal("10"))
    # extra_per_km applies only beyond the last band (60 km): ~20 km stays ₹80 (beyond 60 km: tested with `bands`).
    assert Decimal(_preview(auth_client, city["far"])["delivery"]["fee"]) == Decimal("80")


@pytest.mark.delivery_charges
def test_zone_fee_override_still_wins(auth_client, city):
    DeliveryCharges.objects.update_or_create(pk=1, defaults={"free_first_orders": 0})
    DeliveryZone.objects.filter(pk=city["zone"].pk).update(delivery_fee_override=Decimal("25"))
    _add(auth_client, city["drill"])
    assert _preview(auth_client, city["far"])["delivery"]["fee"] == "25.00"


@pytest.mark.delivery_charges
def test_missing_store_coordinates_give_a_labelled_estimate(auth_client, city):
    DeliveryCharges.objects.update_or_create(pk=1, defaults={"free_first_orders": 0})
    Store.objects.filter(pk=city["store"].pk).update(latitude=None, longitude=None)
    _add(auth_client, city["drill"])
    delivery = _preview(auth_client, city["far"])["delivery"]
    assert delivery["available"] is True and delivery["distance_estimated"] is True
    assert Decimal(delivery["fee"]) > 0


def test_an_address_outside_bengaluru_is_not_offered_delivery(auth_client, user, city):
    _add(auth_client, city["drill"])
    pune = create_address(user)  # 411001
    data = _preview(auth_client, pune)
    assert data["delivery"]["available"] is False and data["can_place_order"] is False
    issue = next(i for i in data["blocking_issues"] if i["code"] == "not_deliverable")
    assert "passed this address to our team to review" in issue["message"]
    _preview(auth_client, pune)  # previewing again doesn't add another review
    review = CoverageReview.objects.get()
    assert (review.address_id, review.postal_code, review.status) == (pune.id, "411001", "open")
    assert _order(auth_client, pune).status_code >= 400


@pytest.mark.delivery_charges
def test_first_three_orders_have_free_delivery_shown_against_the_normal_charge(auth_client, city):
    # The promotion is off by shop policy (default 0); an administrator can still switch it on deliberately.
    DeliveryCharges.objects.update_or_create(pk=1, defaults={"free_first_orders": 3})
    for n in range(1, 4):
        _add(auth_client, city["drill"])
        preview = _preview(auth_client, city["near"])
        totals, delivery = preview["totals"], preview["delivery"]
        assert totals["delivery_fee"] == "0.00" and Decimal(totals["delivery_charge"]) > 0
        assert totals["delivery_discount"] == totals["delivery_charge"] and totals["first_order_free_delivery"]
        assert delivery["free_delivery_reason"] == f"Free delivery on your first 3 orders ({n} of 3)"
        res = _order(auth_client, city["near"], key=f"first-order-key-{n:04d}")
        assert res.status_code == 201, res.json()
        # A repeat of the same request is the same order and doesn't use another free delivery.
        assert _order(auth_client, city["near"], key=f"first-order-key-{n:04d}").status_code == 200
    order = Order.objects.order_by("-id").first()
    assert order.first_order_free_delivery and order.delivery_fee == 0 and order.delivery_charge > 0
    assert Order.objects.filter(first_order_free_delivery=True).count() == 3

    _add(auth_client, city["drill"])
    fourth = _preview(auth_client, city["near"])["totals"]
    assert Decimal(fourth["delivery_fee"]) > 0 and not fourth["first_order_free_delivery"]

    # Cancelling one of them gives its free delivery back.
    number = order.order_number
    assert (
        auth_client.post(f"/api/orders/{number}/cancel/", {"reason": "Changed my mind"}, format="json").status_code
        == 200
    )
    assert _preview(auth_client, city["near"])["totals"]["delivery_fee"] == "0.00"


@pytest.mark.delivery_charges
def test_an_order_that_is_free_anyway_does_not_use_a_free_first_delivery(auth_client, city, settings):
    settings.FREE_DELIVERY_MIN_ORDER = Decimal("250.00")
    _add(auth_client, city["drill"])
    totals = _preview(auth_client, city["near"])["totals"]
    assert totals["delivery_fee"] == "0.00" and not totals["first_order_free_delivery"]
    assert _order(auth_client, city["near"]).status_code == 201
    assert not Order.objects.get().first_order_free_delivery


def test_unloading_is_offered_only_where_configured_and_priced_on_the_server(auth_client, city):
    _add(auth_client, city["drill"])
    off = _preview(auth_client, city["near"], unloading=True)
    assert off["unloading"]["available"] is False and off["unloading"]["selected"] is False
    assert off["totals"]["unloading_fee"] == "0.00"
    refused = _order(auth_client, city["near"], unloading=True)
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "unloading_unavailable"

    DeliveryZone.objects.filter(pk=city["zone"].pk).update(unloading_available=True)
    without = _preview(auth_client, city["near"])
    on = _preview(auth_client, city["near"], unloading=True)
    assert on["unloading"]["selected"] and on["unloading"]["fee"] == "199.00"
    assert "ground level" in on["unloading"]["message"] and "upstairs" in on["unloading"]["message"]
    assert Decimal(on["totals"]["grand_total"]) == Decimal(without["totals"]["grand_total"]) + Decimal("199.00")
    res = _order(auth_client, city["near"], unloading=True, expected_total=on["totals"]["grand_total"])
    assert res.status_code == 201, res.json()
    order = Order.objects.get()
    assert order.unloading_requested and order.unloading_fee == Decimal("199.00")
    assert res.json()["unloading_fee"] == "199.00"
