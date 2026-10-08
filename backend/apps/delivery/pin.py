"""What the shopper's chosen PIN code means for browsing (Phase 16).

Product cards and listings show "fast delivery" only for the PIN the shopper picked: an item gets the
badge when it is in stock at a store that the Phase 9 engine says can deliver fast to that PIN right now
(zone covers the PIN, fast delivery enabled, store open, rider capacity, ETA within the cutoff). Without a
PIN no fast badge is shown at all, so nobody is promised fast delivery that their address can't get.

The answer is the same estimate the `/delivery/check/` endpoint gives (one item, nearest store), cached
for a minute per PIN so a listing page costs one lookup, not one per product.
"""

from dataclasses import dataclass, field

from django.core.cache import cache

from .eta import estimate
from .fulfillment import covering_candidates
from .locations import resolve_location
from .service_areas import not_covered_message

CACHE_SECONDS = 60
PIN_PATTERN_LENGTH = 6


@dataclass(frozen=True)
class PinContext:
    postal_code: str
    serviceable: bool
    fast_available: bool
    label: str = ""
    message: str = ""
    fast_unavailable_reason: str = ""
    serving_store_ids: frozenset[int] = field(default_factory=frozenset)
    fast_store_ids: frozenset[int] = field(default_factory=frozenset)
    zone_id: int | None = None  # the best store's zone (free-delivery rules can be per zone)

    def as_dict(self) -> dict:
        return {
            "postal_code": self.postal_code,
            "serviceable": self.serviceable,
            "fast_delivery_available": self.fast_available,
            "label": self.label,
            "message": self.message,
            "fast_unavailable_reason": self.fast_unavailable_reason,
        }


def valid_pin(value) -> str:
    value = (value or "").strip()
    if len(value) == PIN_PATTERN_LENGTH and value.isdigit() and value[0] != "0":
        return value
    return ""


def _compute(postal_code: str) -> PinContext:
    location = resolve_location(postal_code=postal_code)
    estimates = [estimate(store, zone, location, line_count=1) for store, zone in covering_candidates(location)]
    if not estimates:
        return PinContext(postal_code, False, False, message=not_covered_message(location))
    estimates.sort(key=lambda e: e.sort_key())
    best = estimates[0]
    lead = "⚡ Fast delivery available" if best.fast_available else "🚚 Standard delivery"
    return PinContext(
        postal_code=postal_code,
        serviceable=True,
        fast_available=best.fast_available,
        label=best.label,
        message=f"{lead} · {best.label}",
        fast_unavailable_reason="" if best.fast_available else best.fast_unavailable_reason,
        serving_store_ids=frozenset(e.store.pk for e in estimates),
        fast_store_ids=frozenset(e.store.pk for e in estimates if e.fast_available),
        zone_id=best.zone.pk if best.zone is not None else None,
    )


def pin_context(postal_code) -> PinContext | None:
    """None when no (valid) PIN was given."""
    postal_code = valid_pin(postal_code)
    if not postal_code:
        return None
    key = f"delivery:pin-context:{postal_code}"
    context = cache.get(key)
    if context is None:
        context = _compute(postal_code)
        cache.set(key, context, CACHE_SECONDS)
    return context
