"""Fulfilment plan: which store(s) ship an order, and when it arrives (Phase 9).

Selection (documented in docs/ARCHITECTURE.md "Fulfilment engine"):

1. Candidates: active stores/dark stores that accept orders and have an active delivery zone
   covering the customer (PIN listed in the zone, within the zone radius/polygon, or — with no
   coordinates at all — the store's own PIN). Warehouses never ship to customers.
2. Single-store plans: every candidate holding *all* lines in the required quantity is estimated
   (eta.estimate). Best = fast-eligible first, then lowest ETA, then shortest distance, then store id.
3. Split plan (SPLIT_FULFILLMENT_ENABLED, up to MAX_SHIPMENTS_PER_ORDER): when no single store
   has everything, lines are assigned greedily to the store covering the most remaining lines
   (ties: best estimate). A line is never split between stores. The order is fast only if every
   shipment is fast; its ETA is the latest shipment's.
4. Nothing fits: not deliverable, with the reason (`out_of_zone`, `location_unknown`, `insufficient_stock`).

Stock is only *read* here. `place_order` reserves it per shipment with row locks, so a plan that
went stale (another order took the stock) fails with `insufficient_stock` and nothing is written.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.core.money import q
from apps.inventory.models import Inventory
from apps.stores.models import Store
from integrations.maps import point_in_polygon

from .eta import Estimate, estimate, store_capacity, straight_line_km
from .locations import Location
from .models import DeliveryZone


@dataclass(frozen=True)
class FeeRule:
    fee: Decimal
    free_min: Decimal

    @classmethod
    def default(cls) -> "FeeRule":
        return cls(q(settings.DELIVERY_FEE), q(settings.FREE_DELIVERY_MIN_ORDER))

    @classmethod
    def for_zone(cls, zone) -> "FeeRule":
        default = cls.default()
        if zone is None:
            return default
        return cls(
            q(zone.delivery_fee_override) if zone.delivery_fee_override is not None else default.fee,
            q(zone.free_delivery_min_order) if zone.free_delivery_min_order is not None else default.free_min,
        )


@dataclass
class ShipmentPlan:
    store: Store
    zone: DeliveryZone | None
    lines: dict[int, int]  # variant_id → quantity
    estimate: Estimate | None


@dataclass
class Plan:
    deliverable: bool
    location: Location | None
    shipments: list[ShipmentPlan] = field(default_factory=list)
    reason_code: str = ""
    message: str = ""
    fast_unavailable_reason: str = ""

    @property
    def primary(self) -> ShipmentPlan | None:
        return max(self.shipments, key=lambda s: len(s.lines)) if self.shipments else None

    @property
    def is_split(self) -> bool:
        return len(self.shipments) > 1

    @property
    def fee_rule(self) -> FeeRule:
        return FeeRule.for_zone(self.primary.zone if self.primary else None)

    @property
    def estimates(self) -> list[Estimate]:
        return [s.estimate for s in self.shipments if s.estimate]

    @property
    def latest(self) -> Estimate | None:
        return max(self.estimates, key=lambda e: e.delivery_at) if self.estimates else None

    @property
    def delivery_type(self) -> str | None:
        if not self.estimates:
            return None
        return "fast" if all(e.fast_available for e in self.estimates) else "standard"


# --- Coverage ----------------------------------------------------------------------------------


def zone_covers(zone: DeliveryZone, store: Store, location: Location) -> bool:
    if location.postal_code and location.postal_code in zone.postal_code_set:
        return True
    distance = straight_line_km(store, location)
    if distance is not None:
        if distance > float(zone.radius_km):
            return False
        return location.precision != "exact" or not zone.polygon or point_in_polygon(location.point, zone.polygon)
    # No coordinates on one side: fall back to "same PIN as the store".
    return bool(location.postal_code) and location.postal_code == store.postal_code


def fulfilment_stores():
    return Store.objects.filter(
        is_active=True, is_deleted=False, accepts_orders=True, kind__in=Store.FULFILLMENT_KINDS
    ).order_by("pk")


def covering_candidates(location: Location) -> list[tuple[Store, DeliveryZone]]:
    """(store, best covering zone) for every store that delivers to `location`."""
    zones = defaultdict(list)
    for zone in DeliveryZone.objects.filter(is_active=True, store__in=fulfilment_stores()).select_related("store"):
        zones[zone.store_id].append(zone)
    result = []
    for store_zones in zones.values():
        covering = [z for z in store_zones if zone_covers(z, z.store, location)]
        if covering:
            # Prefer a fast-delivery zone, then the cheapest fee, then the smallest (most specific) radius.
            covering.sort(key=lambda z: (not z.fast_delivery_enabled, FeeRule.for_zone(z).fee, z.radius_km))
            result.append((covering[0].store, covering[0]))
    return sorted(result, key=lambda pair: pair[0].pk)


def stock_levels(store_ids, variant_ids) -> dict[tuple[int, int], int]:
    rows = Inventory.objects.filter(store_id__in=store_ids, variant_id__in=variant_ids, is_active=True)
    return {(r.store_id, r.variant_id): r.available_quantity for r in rows}


# --- Planning ----------------------------------------------------------------------------------


def plan_fulfillment(requirements: dict[int, int], location: Location | None, *, now: datetime | None = None) -> Plan:
    """Choose the fulfilment plan for `requirements` (variant_id → quantity).

    `location=None` (no address chosen yet): zones and ETAs are skipped; the plan only says
    whether the stock can be supplied at all.
    """
    now = now or timezone.now()
    requirements = {v: qty for v, qty in requirements.items() if qty > 0}
    if not requirements:
        return Plan(False, location, reason_code="cart_empty", message="Your cart is empty.")

    if location is None:
        candidates = [(store, None) for store in fulfilment_stores()]
    else:
        candidates = covering_candidates(location)
        if not candidates:
            if not location.known and not location.postal_code:
                return Plan(False, location, reason_code="location_unknown",
                            message="Add a delivery address or PIN code to check delivery.")  # fmt: skip
            where = f"PIN {location.postal_code}" if location.postal_code else "this address"
            return Plan(False, location, reason_code="out_of_zone", message=f"We don't deliver to {where} yet.")

    stock = stock_levels([s.pk for s, _ in candidates], list(requirements))
    capacities: dict[int, object] = {}

    def has(store, variant_id):
        return stock.get((store.pk, variant_id), 0) >= requirements[variant_id]

    def est(store, zone, line_count):
        if location is None:
            return None
        if store.pk not in capacities:
            capacities[store.pk] = store_capacity(store)
        return estimate(store, zone, location, line_count=line_count, now=now, capacity=capacities[store.pk])

    def key(store, estimate_):
        return estimate_.sort_key() if estimate_ else (0, 0, 0, store.pk)

    # 1. One store for everything.
    singles = []
    for store, zone in candidates:
        if all(has(store, v) for v in requirements):
            singles.append(ShipmentPlan(store, zone, dict(requirements), est(store, zone, len(requirements))))
    if singles:
        best = min(singles, key=lambda s: key(s.store, s.estimate))
        return _finish(Plan(True, location, [best]))

    # 2. Split across stores (greedy set cover).
    if settings.SPLIT_FULFILLMENT_ENABLED:
        remaining = set(requirements)
        shipments: list[ShipmentPlan] = []
        pool = list(candidates)
        while remaining and pool and len(shipments) < settings.MAX_SHIPMENTS_PER_ORDER:
            options = []
            for store, zone in pool:
                covered = {v for v in remaining if has(store, v)}
                if covered:
                    options.append((len(covered), store, zone, covered))
            if not options:
                break
            best_count = max(o[0] for o in options)
            top = [o for o in options if o[0] == best_count]
            _, store, zone, covered = min(top, key=lambda o: key(o[1], est(o[1], o[2], len(o[3]))))
            shipments.append(ShipmentPlan(store, zone, {v: requirements[v] for v in covered}, None))
            remaining -= covered
            pool = [(s, z) for s, z in pool if s.pk != store.pk]
        if not remaining:
            for shipment in shipments:
                shipment.estimate = est(shipment.store, shipment.zone, len(shipment.lines))
            return _finish(Plan(True, location, shipments))

    where = "" if location is None else " for delivery to this address"
    return Plan(
        False,
        location,
        reason_code="insufficient_stock",
        message=f"Some items aren't available together{where} right now. Reduce quantities or remove items.",
    )


def _finish(plan: Plan) -> Plan:
    reasons = [e.fast_unavailable_reason for e in plan.estimates if e.fast_unavailable_reason]
    plan.fast_unavailable_reason = reasons[0] if reasons else ""
    return plan


def reestimate_shipment(shipment, *, now: datetime | None = None) -> Estimate | None:
    """Fresh estimate for an existing shipment (same store), e.g. when an online order is paid later."""
    from .locations import resolve_location

    snapshot = shipment.order.address_snapshot or {}
    location = resolve_location(
        postal_code=snapshot.get("postal_code", ""),
        latitude=snapshot.get("latitude"),
        longitude=snapshot.get("longitude"),
    )
    return estimate(shipment.store, shipment.zone, location, line_count=shipment.items.count(), now=now)
