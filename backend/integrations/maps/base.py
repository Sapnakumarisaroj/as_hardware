"""Maps interface: geocoding (text/PIN → coordinates) and routing (distance + travel time).

Business code (apps/delivery) depends only on `MapsProvider`. The default is fully offline
(haversine distance × road factor ÷ configured speed); OpenStreetMap services are optional:

- geocoding:  none (default) | nominatim   — GEOCODING_PROVIDER
- routing:    haversine (default) | osrm    — ROUTING_PROVIDER

Network providers are always wrapped so that a timeout or outage falls back to the offline
estimate instead of blocking checkout.
"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Point:
    latitude: float
    longitude: float

    @classmethod
    def of(cls, latitude, longitude) -> "Point | None":
        if latitude is None or longitude is None:
            return None
        return cls(float(latitude), float(longitude))


@dataclass(frozen=True)
class GeocodeResult:
    point: Point
    display_name: str = ""
    source: str = "none"


@dataclass(frozen=True)
class Route:
    distance_km: float
    duration_minutes: float
    source: str  # "haversine" | "osrm" | …


class MapsError(Exception):
    """Temporary provider failure; callers fall back to the offline estimate."""


def haversine_km(a: Point, b: Point) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.latitude, a.longitude, b.latitude, b.longitude))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def point_in_polygon(point: Point, ring: list) -> bool:
    """Ray casting over [[lat, lng], …]. Good enough for city-scale delivery zones."""
    inside = False
    n = len(ring)
    for i in range(n):
        lat_i, lng_i = float(ring[i][0]), float(ring[i][1])
        lat_j, lng_j = float(ring[i - 1][0]), float(ring[i - 1][1])
        crosses = (lng_i > point.longitude) != (lng_j > point.longitude)
        if crosses:
            lat_at = (lat_j - lat_i) * (point.longitude - lng_i) / (lng_j - lng_i) + lat_i
            if point.latitude < lat_at:
                inside = not inside
    return inside


class Geocoder(ABC):
    name: str

    @abstractmethod
    def geocode(self, *, query: str = "", postal_code: str = "", country: str = "in") -> GeocodeResult | None: ...


class Router(ABC):
    name: str

    @abstractmethod
    def route(self, origin: Point, destination: Point) -> Route: ...


class MapsProvider:
    """Geocoder + router pair used by the delivery engine."""

    def __init__(self, geocoder: Geocoder, router: Router, fallback_router: Router):
        self.geocoder, self.router, self.fallback_router = geocoder, router, fallback_router

    def geocode(self, **kwargs) -> GeocodeResult | None:
        try:
            return self.geocoder.geocode(**kwargs)
        except MapsError:
            return None

    def route(self, origin: Point, destination: Point) -> Route:
        try:
            return self.router.route(origin, destination)
        except MapsError:
            return self.fallback_router.route(origin, destination)


def km(value: float) -> Decimal:
    return Decimal(str(round(value, 2)))
