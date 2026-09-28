"""Phase 9: the ETA engine (apps/delivery/eta.py) and the maps providers behind it."""

import math
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest

from apps.delivery.eta import Capacity, delivery_label, estimate, is_open, next_opening, store_capacity
from apps.delivery.locations import Location, resolve_location
from apps.delivery.models import GeocodeCache, PinCode
from integrations.maps import MapsError, Point, get_maps_provider, haversine_km, point_in_polygon
from integrations.maps.base import GeocodeResult
from integrations.maps.providers import NominatimGeocoder, OSRMRouter

from .helpers import EVERY_DAY_9_TO_21, create_partner, ist, location_at, point, store_at, zone_for

pytestmark = pytest.mark.django_db

NOON = ist(2026, 9, 28, 12)  # a Monday


@pytest.fixture(autouse=True)
def eta_settings(settings):
    settings.DELIVERY_AVG_SPEED_KMPH = 18.0
    settings.ROAD_DISTANCE_FACTOR = 1.35
    settings.DELIVERY_HANDOVER_MINUTES = 4
    settings.DELIVERY_RIDER_TURNAROUND_MINUTES = 35
    settings.FAST_DELIVERY_MAX_MINUTES = 60
    settings.FAST_WINDOW_MINUTES = 15
    settings.STANDARD_DISPATCH_DELAY_MINUTES = 120
    settings.STANDARD_WINDOW_MINUTES = 120
    return settings


def expected_minutes(km_north: float, *, prep: int, wait: int = 0, speed: float = 18.0) -> int:
    road_km = haversine_km(point(0), point(km_north)) * 1.35
    return math.ceil(prep + wait + road_km / speed * 60 + 4)


# --- Geometry ------------------------------------------------------------------------------------


def test_haversine_matches_a_known_distance():
    pune, mumbai = Point(18.5204, 73.8567), Point(19.0760, 72.8777)
    assert haversine_km(pune, mumbai) == pytest.approx(120, abs=2)
    assert haversine_km(pune, pune) == 0


def test_point_in_polygon():
    square = [[18.50, 73.80], [18.50, 73.82], [18.52, 73.82], [18.52, 73.80]]
    assert point_in_polygon(Point(18.51, 73.81), square) is True
    assert point_in_polygon(Point(18.53, 73.81), square) is False


# --- The estimate --------------------------------------------------------------------------------


def test_eta_is_prep_plus_travel_plus_handover():
    store = store_at(avg_prep_minutes=10, prep_minutes_per_item=2)
    zone = zone_for(store)
    e = estimate(store, zone, location_at(2), line_count=1, now=NOON)
    assert e.fast_available and e.delivery_type == "fast"
    assert e.prep_minutes == 10 and e.wait_minutes == 0 and e.eta_source == "haversine"
    assert e.distance_km == pytest.approx(2.0 * 1.35, abs=0.02)
    assert e.eta_minutes == expected_minutes(2, prep=10) == 24
    assert e.delivery_at == NOON + timedelta(minutes=24)
    assert e.ready_at == NOON + timedelta(minutes=10)
    assert e.window_start == e.delivery_at and e.window_end == e.delivery_at + timedelta(minutes=15)
    assert e.label == "Delivery in 24 minutes"


def test_eta_is_not_a_fixed_number():
    """Different distance, basket size, store prep time and speed all change the estimate."""
    store = store_at(avg_prep_minutes=10, prep_minutes_per_item=2)
    zone = zone_for(store)
    base = estimate(store, zone, location_at(2), line_count=1, now=NOON).eta_minutes
    assert estimate(store, zone, location_at(4), line_count=1, now=NOON).eta_minutes == expected_minutes(4, prep=10)
    assert estimate(store, zone, location_at(4), line_count=1, now=NOON).eta_minutes > base
    assert estimate(store, zone, location_at(2), line_count=4, now=NOON).eta_minutes == base + 6  # 3 more lines × 2
    store.avg_prep_minutes = 25
    assert estimate(store, zone, location_at(2), line_count=1, now=NOON).eta_minutes == base + 15


def test_delivery_speed_is_configurable(settings):
    store = store_at()
    zone = zone_for(store)
    slow = estimate(store, zone, location_at(3), line_count=1, now=NOON).eta_minutes
    settings.DELIVERY_AVG_SPEED_KMPH = 36.0
    fast = estimate(store, zone, location_at(3), line_count=1, now=NOON).eta_minutes
    assert fast == expected_minutes(3, prep=10, speed=36.0) and fast < slow


def test_workload_adds_waiting_time():
    store = store_at(riders=2)
    zone = zone_for(store)
    idle = estimate(store, zone, location_at(2), line_count=1, now=NOON, capacity=Capacity(2, 2, 0))
    one_ahead = estimate(store, zone, location_at(2), line_count=1, now=NOON, capacity=Capacity(2, 2, 1))
    assert idle.wait_minutes == one_ahead.wait_minutes == 0  # a rider is still free
    # Both riders are taken by the two orders waiting: one turnaround before ours leaves.
    busy = estimate(store, zone, location_at(2), line_count=1, now=NOON, capacity=Capacity(2, 2, 2))
    assert busy.wait_minutes == 35 and busy.eta_minutes == expected_minutes(2, prep=10, wait=35)
    assert busy.ready_at == NOON + timedelta(minutes=45)
    # A long queue pushes the estimate past the fast cutoff → standard delivery.
    swamped = estimate(store, zone, location_at(2), line_count=1, now=NOON, capacity=Capacity(1, 1, 3))
    assert swamped.delivery_type == "standard" and not swamped.fast_available
    assert "fast delivery is up to 60" in swamped.fast_unavailable_reason


def test_no_rider_means_no_fast_delivery():
    store = store_at(riders=0)
    zone = zone_for(store)
    e = estimate(store, zone, location_at(2), line_count=1, now=NOON)
    assert e.delivery_type == "standard" and not e.fast_available
    assert e.fast_unavailable_reason == "No delivery partner is available right now."
    # Dispatched in a batch: prep 10 + 120 + travel ≈ 9 + handover 4 → 14:23 → next half hour.
    assert e.window_start == ist(2026, 9, 28, 14, 30) and e.window_end == ist(2026, 9, 28, 16, 30)
    assert e.label == "Today, 2:30 PM – 4:30 PM"


def test_store_capacity_counts_partners_in_house_riders_and_queue(user):
    from apps.carts.services import add_item
    from apps.core.testing import create_address, create_product
    from apps.orders.services import place_order

    store = store_at(riders=1, zone=True)
    create_partner(store, email="a@example.com")
    create_partner(store, email="b@example.com", status="busy")
    create_partner(store, email="c@example.com", status="offline")
    create_partner(store, email="d@example.com", is_verified=False)
    create_partner(store, email="e@example.com", is_active=False)
    create_partner(store_at(5), email="f@example.com")  # another store's rider
    assert store_capacity(store) == Capacity(available_riders=2, riders_on_shift=3, queue=0)

    _, variant = create_product(stock=5, store=store)
    add_item(user, variant.id, 1)
    place_order(user=user, address_id=create_address(user).id, payment_method="cod")
    assert store_capacity(store).queue == 1  # confirmed, waiting for a rider


def test_fast_cutoff_comes_from_the_zone_or_the_setting(settings):
    store = store_at()
    strict = zone_for(store, fast_delivery_max_minutes=20)
    e = estimate(store, strict, location_at(2), line_count=1, now=NOON)
    assert e.delivery_type == "standard"
    assert e.fast_unavailable_reason == "Delivery would take about 24 minutes (fast delivery is up to 20)."
    relaxed = zone_for(store, name="relaxed")
    assert estimate(store, relaxed, location_at(2), line_count=1, now=NOON).fast_available
    settings.FAST_DELIVERY_MAX_MINUTES = 23
    assert not estimate(store, relaxed, location_at(2), line_count=1, now=NOON).fast_available


def test_zone_without_fast_delivery_is_standard():
    store = store_at()
    zone = zone_for(store, fast_delivery_enabled=False)
    e = estimate(store, zone, location_at(2), line_count=1, now=NOON)
    assert e.delivery_type == "standard" and e.fast_unavailable_reason == "Fast delivery isn't offered in this area."


def test_closed_store_delivers_in_the_next_opening_hours():
    store = store_at(opening_hours=EVERY_DAY_9_TO_21)
    zone = zone_for(store)
    late = ist(2026, 9, 28, 22, 30)
    assert is_open(store, NOON) and not is_open(store, late)
    assert next_opening(store, late) == (ist(2026, 9, 29, 9), ist(2026, 9, 29, 21))
    e = estimate(store, zone, location_at(2), line_count=1, now=late)
    assert e.delivery_type == "standard" and e.fast_unavailable_reason == "The store is closed right now."
    # Opens 09:00 → ready 09:10 → + 120 + 9 + 4 → 11:23 → 11:30.
    assert e.ready_at == ist(2026, 9, 29, 9, 10)
    assert e.window_start == ist(2026, 9, 29, 11, 30)
    assert e.label == "Tomorrow, 11:30 AM – 1:30 PM"
    assert e.eta_minutes == 13 * 60  # 22:30 → 11:30


def test_standard_delivery_rolls_to_the_next_day_near_closing_time():
    store = store_at(riders=0, opening_hours=EVERY_DAY_9_TO_21)
    zone = zone_for(store)
    e = estimate(store, zone, location_at(2), line_count=1, now=ist(2026, 9, 28, 20, 30))
    assert e.window_start == ist(2026, 9, 29, 11, 30)  # 20:30 + 143 min is after closing + grace


def test_closed_days_are_skipped():
    hours = {**EVERY_DAY_9_TO_21, "tue": None}
    store = store_at(opening_hours=hours)
    assert next_opening(store, ist(2026, 9, 28, 22)) == (ist(2026, 9, 30, 9), ist(2026, 9, 30, 21))
    e = estimate(store, zone_for(store), location_at(2), line_count=1, now=ist(2026, 9, 28, 22))
    assert e.label == "Wed 30 Sep, 11:30 AM – 1:30 PM"


def test_labels():
    now = ist(2026, 9, 28, 12)
    assert delivery_label("fast", 38, None, None, now) == "Delivery in 38 minutes"
    start = ist(2026, 9, 29, 10)
    assert delivery_label("standard", None, start, start + timedelta(hours=2), now) == "Tomorrow, 10:00 AM – 12:00 PM"
    assert delivery_label("standard", None, None, None, now) == ""


def test_missing_coordinates_fall_back_to_pin_or_zone_radius(settings):
    settings.SAME_PIN_DISTANCE_KM = 2.0
    store = store_at(latitude=None, longitude=None, postal_code="411038")
    zone = zone_for(store, radius="4", postal_codes="411052")
    same_pin = estimate(store, zone, Location(None, "411038", "unknown"), line_count=1, now=NOON)
    assert same_pin.eta_source == "pin" and same_pin.distance_km == 2.0
    listed = estimate(store, zone, Location(None, "411052", "unknown"), line_count=1, now=NOON)
    assert listed.eta_source == "zone" and listed.distance_km == pytest.approx(4 * 1.35)
    assert listed.eta_minutes > same_pin.eta_minutes


# --- Locations -----------------------------------------------------------------------------------


def test_location_precision(user):
    from .helpers import address_at

    exact = resolve_location(address=address_at(user, 1))
    assert exact.precision == "exact" and exact.known
    PinCode.objects.create(postal_code="411045", area="Baner", latitude=Decimal("18.559"), longitude=Decimal("73.7868"))
    pin = resolve_location(postal_code="411045")
    assert pin.precision == "pin" and pin.point == Point(18.559, 73.7868)
    unknown = resolve_location(postal_code="411099")
    assert unknown.precision == "unknown" and not unknown.known and unknown.postal_code == "411099"
    PinCode.objects.filter(postal_code="411045").update(is_active=False)
    assert resolve_location(postal_code="411045").precision == "unknown"


def test_geocoding_answers_are_cached_including_not_found(settings):
    settings.GEOCODING_PROVIDER = "nominatim"
    found = GeocodeResult(Point(18.5, 73.8), "Somewhere, Pune", "nominatim")
    with mock.patch.object(NominatimGeocoder, "geocode", side_effect=[found, None]) as geocode:
        assert resolve_location(postal_code="411011").point == Point(18.5, 73.8)
        assert resolve_location(postal_code="411011").precision == "pin"
        assert resolve_location(postal_code="411012").precision == "unknown"
        assert resolve_location(postal_code="411012").precision == "unknown"
    assert geocode.call_count == 2
    assert GeocodeCache.objects.get(query="pin:411012").latitude is None


def test_geocoding_is_off_by_default():
    with mock.patch("integrations.maps.providers._get_json") as http:
        assert resolve_location(postal_code="411011").precision == "unknown"
    http.assert_not_called()
    assert not GeocodeCache.objects.exists()


# --- Providers (no network: HTTP is faked) ---------------------------------------------------------


def test_unknown_provider_setting_is_rejected(settings):
    from django.core.exceptions import ImproperlyConfigured

    settings.ROUTING_PROVIDER = "google"
    with pytest.raises(ImproperlyConfigured):
        get_maps_provider()


def test_osrm_route_is_used_cached_and_never_faster_than_the_configured_speed(settings):
    settings.ROUTING_PROVIDER = "osrm"
    answer = {"code": "Ok", "routes": [{"distance": 3600.0, "duration": 300.0}]}
    with mock.patch("integrations.maps.providers._get_json", return_value=answer) as http:
        route = get_maps_provider().route(point(0), point(2))
        again = get_maps_provider().route(point(0), point(2))
    assert route.source == "osrm" and route.distance_km == 3.6
    assert route.duration_minutes == pytest.approx(12.0)  # 3.6 km at 18 km/h, not OSRM's 5 car-minutes
    assert again == route and http.call_count == 1
    url = http.call_args.args[0]
    assert url.startswith("https://router.project-osrm.org/route/v1/driving/73.8077,18.5074;")


def test_osrm_outage_falls_back_to_the_offline_estimate(settings):
    settings.ROUTING_PROVIDER = "osrm"
    store = store_at()
    zone = zone_for(store)
    with mock.patch("integrations.maps.providers._get_json", side_effect=MapsError("timed out")):
        e = estimate(store, zone, location_at(2), line_count=1, now=NOON)
    assert e.eta_source == "haversine" and e.eta_minutes == 24
    with mock.patch("integrations.maps.providers._get_json", return_value={"code": "NoRoute", "routes": []}):
        assert get_maps_provider().route(point(0), point(2)).source == "haversine"


def test_maps_http_is_https_only(settings):
    settings.OSRM_BASE_URL = "http://router.example.com"
    with pytest.raises(MapsError):
        OSRMRouter().route(point(0), point(1))


def test_nominatim_request_and_parsing(settings):
    settings.NOMINATIM_USER_AGENT = "BoltRun-tests"
    answer = [{"lat": "18.5074", "lon": "73.8077", "display_name": "Kothrud, Pune"}]
    with (
        mock.patch("integrations.maps.providers._get_json", return_value=answer) as http,
        mock.patch("integrations.maps.providers.time.sleep"),
    ):
        result = NominatimGeocoder().geocode(postal_code="411038")
        assert NominatimGeocoder().geocode(query="12 MG Road, Pune") is not None
    assert result.point == Point(18.5074, 73.8077) and result.source == "nominatim"
    first, second = (call.args[0] for call in http.call_args_list)
    assert "postalcode=411038" in first and "countrycodes=in" in first
    assert "q=12+MG+Road" in second
    assert http.call_args.kwargs["user_agent"] == "BoltRun-tests"
    with mock.patch("integrations.maps.providers._get_json", return_value=[]):
        with mock.patch("integrations.maps.providers.time.sleep"):
            assert NominatimGeocoder().geocode(postal_code="000000") is None
