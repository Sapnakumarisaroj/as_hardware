"""Concrete maps providers. Only the standard library is used for HTTP (`urllib`).

- `HaversineRouter`: offline. Road distance ≈ straight line × ROAD_DISTANCE_FACTOR; time from
  DELIVERY_AVG_SPEED_KMPH. No network, no limits.
- `OSRMRouter`: OSRM `/route/v1/driving` (self-hosted, or the public demo server
  router.project-osrm.org, which is for light use only: max 1 request/second, no SLA).
  Responses are cached (ROUTE_CACHE_SECONDS) and any error falls back to haversine.
- `NominatimGeocoder`: OpenStreetMap Nominatim search. Usage policy: ≤ 1 request/second,
  an identifying User-Agent (NOMINATIM_USER_AGENT), and results must be cached — callers
  go through `apps.delivery.locations`, which stores every answer in `GeocodeCache`.
- `NoGeocoder`: never calls out (default; PIN centroids come from the admin-managed table).
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache

from .base import Geocoder, GeocodeResult, MapsError, Point, Route, Router, haversine_km


def _get_json(url: str, *, timeout: float, user_agent: str) -> dict | list:
    if not url.startswith("https://") and not url.startswith("http://localhost") and not url.startswith("http://127."):
        raise MapsError("Maps services must use https (or a local server).")
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 — scheme checked above
            return json.loads(res.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
        raise MapsError(str(exc)) from exc


class HaversineRouter(Router):
    name = "haversine"

    def route(self, origin: Point, destination: Point) -> Route:
        distance = haversine_km(origin, destination) * float(settings.ROAD_DISTANCE_FACTOR)
        minutes = distance / max(float(settings.DELIVERY_AVG_SPEED_KMPH), 1.0) * 60
        return Route(distance_km=distance, duration_minutes=minutes, source=self.name)


class OSRMRouter(Router):
    name = "osrm"

    def route(self, origin: Point, destination: Point) -> Route:
        key = (
            f"osrm:{origin.latitude:.5f},{origin.longitude:.5f}:{destination.latitude:.5f},{destination.longitude:.5f}"
        )
        if cached := cache.get(key):
            return Route(**cached)
        coords = f"{origin.longitude},{origin.latitude};{destination.longitude},{destination.latitude}"
        url = f"{settings.OSRM_BASE_URL.rstrip('/')}/route/v1/driving/{coords}?overview=false"
        data = _get_json(url, timeout=settings.MAPS_TIMEOUT_SECONDS, user_agent=settings.NOMINATIM_USER_AGENT)
        if not isinstance(data, dict) or data.get("code") != "Ok" or not data.get("routes"):
            raise MapsError(f"OSRM: {data.get('code') if isinstance(data, dict) else 'bad response'}")
        best = data["routes"][0]
        # OSRM's car profile assumes free-flowing traffic; delivery bikes in Indian cities are slower,
        # so the configured average speed caps the duration from below.
        distance = best["distance"] / 1000
        minutes = max(best["duration"] / 60, distance / max(float(settings.DELIVERY_AVG_SPEED_KMPH), 1.0) * 60)
        result = {"distance_km": distance, "duration_minutes": minutes, "source": self.name}
        cache.set(key, result, settings.ROUTE_CACHE_SECONDS)
        return Route(**result)


class NoGeocoder(Geocoder):
    name = "none"

    def geocode(self, *, query: str = "", postal_code: str = "", country: str = "in") -> GeocodeResult | None:
        return None


class NominatimGeocoder(Geocoder):
    name = "nominatim"
    _lock = threading.Lock()
    _last_call = 0.0

    def geocode(self, *, query: str = "", postal_code: str = "", country: str = "in") -> GeocodeResult | None:
        params = {"format": "jsonv2", "limit": 1, "countrycodes": country}
        if postal_code and not query:
            params["postalcode"] = postal_code
        else:
            params["q"] = query or postal_code
        url = f"{settings.NOMINATIM_BASE_URL.rstrip('/')}/search?{urllib.parse.urlencode(params)}"
        with self._lock:  # usage policy: at most one request per second from this process
            wait = 1.0 - (time.monotonic() - NominatimGeocoder._last_call)
            if wait > 0:
                time.sleep(wait)
            NominatimGeocoder._last_call = time.monotonic()
        data = _get_json(url, timeout=settings.MAPS_TIMEOUT_SECONDS, user_agent=settings.NOMINATIM_USER_AGENT)
        if not data:
            return None
        first = data[0]
        return GeocodeResult(
            point=Point(float(first["lat"]), float(first["lon"])),
            display_name=first.get("display_name", "")[:255],
            source=self.name,
        )
