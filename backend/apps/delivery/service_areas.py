"""City-wide service areas (e.g. Bengaluru): is an address inside, and what to tell the customer if not.

Rules (see `ServiceArea`): a PIN code decides when there is one (prefix rule, plus extra / minus
excluded codes); without a PIN, a map pin inside the area's polygon, else the typed city name.
Being inside only makes an address *eligible*: stores, stock, hours, riders and the ETA engine still
decide whether and how fast an order can be delivered.
"""

from django.conf import settings

from integrations.maps import point_in_polygon

from .locations import Location
from .models import ServiceArea


def active_areas() -> list[ServiceArea]:
    return list(ServiceArea.objects.filter(is_active=True))


def area_contains(area: ServiceArea, location: Location) -> bool:
    if location.postal_code:
        return area.covers_postal_code(location.postal_code)
    if location.point is not None and area.polygon:
        return point_in_polygon(location.point, area.polygon)
    return area.covers_city(location.city)


def area_for(location: Location, areas: list[ServiceArea] | None = None) -> ServiceArea | None:
    for area in active_areas() if areas is None else areas:
        if area_contains(area, location):
            return area
    return None


def restricted_areas() -> list[ServiceArea]:
    """The areas deliveries are limited to; empty = no city restriction (zones alone decide)."""
    return active_areas() if settings.DELIVERY_RESTRICT_TO_SERVICE_AREAS else []


def outside_message(areas: list[ServiceArea]) -> str:
    names = [area.name for area in areas]
    where = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"Currently we deliver only within {where}."


def not_covered_message(location: Location) -> str:
    """Why no store serves `location`: outside the city, or inside it with no store taking orders."""
    if areas := restricted_areas():
        area = area_for(location, areas)
        if area is None:
            return outside_message(areas)
        return f"We deliver across {area.name}, but no store can take orders right now. Please try again later."
    where = f"PIN {location.postal_code}" if location.postal_code else "this address"
    return f"We don't deliver to {where} yet."
