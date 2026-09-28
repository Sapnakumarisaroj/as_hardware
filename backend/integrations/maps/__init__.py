from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import GeocodeResult, MapsError, MapsProvider, Point, Route, haversine_km, point_in_polygon
from .providers import HaversineRouter, NoGeocoder, NominatimGeocoder, OSRMRouter

__all__ = [
    "GeocodeResult",
    "MapsError",
    "MapsProvider",
    "Point",
    "Route",
    "get_maps_provider",
    "haversine_km",
    "point_in_polygon",
]

_GEOCODERS = {"none": NoGeocoder, "nominatim": NominatimGeocoder}
_ROUTERS = {"haversine": HaversineRouter, "osrm": OSRMRouter}


def get_maps_provider() -> MapsProvider:
    try:
        geocoder = _GEOCODERS[settings.GEOCODING_PROVIDER]()
        router = _ROUTERS[settings.ROUTING_PROVIDER]()
    except KeyError as exc:
        raise ImproperlyConfigured(f"Unknown maps provider setting: {exc}") from exc
    return MapsProvider(geocoder=geocoder, router=router, fallback_router=HaversineRouter())
