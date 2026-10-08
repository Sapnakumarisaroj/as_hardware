"""Delivery time estimate for one store → one location (Phase 9).

    eta = preparation + rider wait + travel + handover            (minutes, rounded up)

  preparation  store.avg_prep_minutes + store.prep_minutes_per_item × (lines − 1)
  rider wait   0 if a rider is free after the orders already waiting at the store; otherwise the
               queue is spread over the riders on shift × DELIVERY_RIDER_TURNAROUND_MINUTES
  travel       route(store → customer): OSRM or haversine × ROAD_DISTANCE_FACTOR at
               DELIVERY_AVG_SPEED_KMPH; same-PIN fallback when coordinates are missing
  handover     DELIVERY_HANDOVER_MINUTES

Fast delivery is offered only if the zone allows it, the store is open now, some rider can take
the order, and eta ≤ the zone's (or global) FAST_DELIVERY_MAX_MINUTES. Otherwise the order is a
standard delivery: dispatched in a batch after STANDARD_DISPATCH_DELAY_MINUTES during opening
hours, shown as a STANDARD_WINDOW_MINUTES window ("Today, 4:00–6:00 PM" / "Tomorrow, …").
Nothing here is a fixed promise: every number comes from store, zone and settings data.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from integrations.maps import Point, get_maps_provider, haversine_km

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LATE_DELIVERY_GRACE = timedelta(hours=1)  # riders may finish deliveries up to an hour after closing


# --- Opening hours ------------------------------------------------------------------------------


def _hours_on(store, day: datetime) -> tuple[datetime, datetime] | None:
    """(open, close) for the local calendar day of `day`, or None if closed that day."""
    hours = store.opening_hours or {}
    local = timezone.localtime(day)
    start_of_day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if not hours:
        return start_of_day, start_of_day + timedelta(days=1)  # no hours configured: always open
    spec = hours.get(DAYS[local.weekday()])
    if not spec or len(spec) != 2:
        return None
    try:
        opens, closes = (time.fromisoformat(value) for value in spec)
    except (TypeError, ValueError):
        return None
    open_at = start_of_day.replace(hour=opens.hour, minute=opens.minute)
    close_at = start_of_day.replace(hour=closes.hour, minute=closes.minute)
    if close_at <= open_at:  # "00:00" closing = midnight
        close_at += timedelta(days=1)
    return open_at, close_at


def is_open(store, at: datetime) -> bool:
    today = _hours_on(store, at)
    return today is not None and today[0] <= at < today[1]


def next_opening(store, at: datetime) -> tuple[datetime, datetime] | None:
    """The (open, close) period that is current or next, searching a week ahead."""
    for offset in range(8):
        day = at + timedelta(days=offset)
        period = _hours_on(store, day)
        if period and period[1] > at:
            return max(period[0], at), period[1]
    return None


# --- Capacity -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Capacity:
    available_riders: int  # can take a new order right now
    riders_on_shift: int  # available + busy (+ in-house riders)
    queue: int  # confirmed orders at this store not yet handed to a rider


WAITING_FOR_RIDER = ("confirmed", "processing", "packed")


def store_capacity(store) -> Capacity:
    from .models import DeliveryAssignment, DeliveryPartner

    partners = DeliveryPartner.objects.filter(home_store=store, is_active=True, is_verified=True).annotate(
        active=Count("assignments", filter=Q(assignments__status__in=DeliveryAssignment.ACTIVE_STATUSES))
    )
    available = sum(
        1 for p in partners if p.status == DeliveryPartner.Status.AVAILABLE and p.active < p.max_active_assignments
    )
    on_shift = sum(1 for p in partners if p.status in (DeliveryPartner.Status.AVAILABLE, DeliveryPartner.Status.BUSY))
    from apps.orders.models import OrderShipment

    queue = (
        OrderShipment.objects.filter(store=store, order__status__in=WAITING_FOR_RIDER)
        .exclude(assignments__status__in=DeliveryAssignment.ACTIVE_STATUSES)
        .count()
    )
    return Capacity(available + store.own_riders, on_shift + store.own_riders, queue)


# --- Estimate -----------------------------------------------------------------------------------


@dataclass
class Estimate:
    store: object
    zone: object | None
    delivery_type: str  # fast | standard
    fast_available: bool
    fast_unavailable_reason: str
    distance_km: float | None
    eta_source: str
    prep_minutes: int
    wait_minutes: int
    travel_minutes: int
    eta_minutes: int
    ready_at: datetime
    delivery_at: datetime
    window_start: datetime
    window_end: datetime
    capacity: Capacity | None = field(default=None, repr=False)
    calculated_at: datetime | None = None

    @property
    def label(self) -> str:
        return delivery_label(
            self.delivery_type, self.eta_minutes, self.window_start, self.window_end, self.calculated_at
        )

    def sort_key(self):
        return (0 if self.fast_available else 1, self.eta_minutes, self.distance_km or 1e9, self.store.pk)


def _ceil(minutes: float) -> int:
    return max(0, math.ceil(minutes - 1e-9))


def _round_up(at: datetime, step_minutes: int = 30) -> datetime:
    at = at.replace(second=0, microsecond=0)
    extra = (-at.minute) % step_minutes
    return at + timedelta(minutes=extra)


def travel(store, location, zone) -> tuple[float | None, float, str]:
    """(distance km, minutes, source) from store to customer."""
    store_point = Point.of(store.latitude, store.longitude)
    speed = max(float(settings.DELIVERY_AVG_SPEED_KMPH), 1.0)
    if store_point and location.point:
        route = get_maps_provider().route(store_point, location.point)
        return route.distance_km, route.duration_minutes, route.source
    if location.postal_code and location.postal_code == store.postal_code:
        distance = float(settings.SAME_PIN_DISTANCE_KM)
        return distance, distance / speed * 60, "pin"
    area = getattr(zone, "service_area", None) if zone else None
    if area is not None and not (location.postal_code and location.postal_code in zone.postal_code_set):
        # Served only because the address is in the city: the distance is a guess (standard delivery only).
        distance = float(area.assumed_distance_km) * float(settings.ROAD_DISTANCE_FACTOR)
        return distance, distance / speed * 60, "area"
    # Served by the zone's PIN list but no coordinates anywhere: assume the zone's full radius.
    distance = (
        float(zone.radius_km) * float(settings.ROAD_DISTANCE_FACTOR) if zone else float(settings.SAME_PIN_DISTANCE_KM)
    )
    return distance, distance / speed * 60, "zone"


def estimate(store, zone, location, *, line_count: int, now: datetime | None = None, capacity=None) -> Estimate:
    now = now or timezone.now()
    capacity = capacity or store_capacity(store)
    prep = store.avg_prep_minutes + store.prep_minutes_per_item * max(line_count - 1, 0)
    distance, travel_minutes, source = travel(store, location, zone)
    handover = settings.DELIVERY_HANDOVER_MINUTES

    reason = ""
    wait = 0
    if zone is None or not zone.fast_delivery_enabled:
        reason = "Fast delivery isn't offered in this area."
    elif source == "area":
        reason = "Pin your location on the map (or choose a saved address) to check fast delivery."
    elif not is_open(store, now):
        reason = "The store is closed right now."
    elif capacity.available_riders > capacity.queue:
        wait = 0
    elif capacity.riders_on_shift > 0:
        rounds = math.ceil((capacity.queue - capacity.available_riders + 1) / capacity.riders_on_shift)
        wait = rounds * settings.DELIVERY_RIDER_TURNAROUND_MINUTES
    else:
        reason = "No delivery partner is available right now."
    fast_eta = _ceil(prep + wait + travel_minutes + handover)
    fast_max = (zone.fast_delivery_max_minutes if zone else None) or settings.FAST_DELIVERY_MAX_MINUTES
    if not reason and fast_eta > fast_max:
        reason = f"Delivery would take about {fast_eta} minutes (fast delivery is up to {fast_max})."

    if not reason:
        ready_at = now + timedelta(minutes=prep + wait)
        delivery_at = now + timedelta(minutes=fast_eta)
        return Estimate(store, zone, "fast", True, "", distance, source, prep, wait, _ceil(travel_minutes),
                        fast_eta, ready_at, delivery_at, delivery_at,
                        delivery_at + timedelta(minutes=settings.FAST_WINDOW_MINUTES), capacity, now)  # fmt: skip

    # Standard delivery: batched dispatch during opening hours.
    period = next_opening(store, now)
    start = period[0] if period else now
    ready_at = start + timedelta(minutes=prep)
    earliest = ready_at + timedelta(minutes=settings.STANDARD_DISPATCH_DELAY_MINUTES + travel_minutes + handover)
    if period and earliest > period[1] + LATE_DELIVERY_GRACE:
        following = next_opening(store, period[1] + timedelta(minutes=1))
        if following:
            ready_at = following[0] + timedelta(minutes=prep)
            earliest = ready_at + timedelta(
                minutes=settings.STANDARD_DISPATCH_DELAY_MINUTES + travel_minutes + handover
            )
    window_start = _round_up(earliest)
    window_end = window_start + timedelta(minutes=settings.STANDARD_WINDOW_MINUTES)
    eta = _ceil((window_start - now).total_seconds() / 60)
    return Estimate(store, zone, "standard", False, reason, distance, source, prep, 0, _ceil(travel_minutes),
                    eta, ready_at, window_start, window_start, window_end, capacity, now)  # fmt: skip


# --- Wording ------------------------------------------------------------------------------------


def _clock(at: datetime) -> str:
    local = timezone.localtime(at)
    return local.strftime("%I:%M %p").lstrip("0")


def _day(at: datetime, now: datetime) -> str:
    local, today = timezone.localtime(at).date(), timezone.localtime(now).date()
    if local == today:
        return "Today"
    if local == today + timedelta(days=1):
        return "Tomorrow"
    return timezone.localtime(at).strftime("%a %d %b")


def delivery_label(delivery_type: str, eta_minutes: int | None, window_start, window_end, now=None) -> str:
    now = now or timezone.now()
    if delivery_type == "fast" and eta_minutes is not None:
        return f"Delivery in {eta_minutes} minutes"
    if window_start and window_end:
        return f"{_day(window_start, now)}, {_clock(window_start)} – {_clock(window_end)}"
    return ""


def straight_line_km(store, location) -> float | None:
    store_point = Point.of(store.latitude, store.longitude)
    if store_point and location.point:
        return haversine_km(store_point, location.point)
    return None
