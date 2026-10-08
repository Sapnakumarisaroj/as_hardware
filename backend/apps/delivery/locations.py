"""Where is the customer? Turns an address, a PIN code or coordinates into a `Location`.

Precision, best first:
  exact    coordinates from the map pin (Leaflet picker) or geocoding of the full address
  pin      centre of the PIN code (admin-managed `PinCode` table, else geocoded once and cached)
  unknown  only the PIN code string is known (zones can still serve it by PIN list / same PIN)

Geocoding is off by default (GEOCODING_PROVIDER=none). With Nominatim enabled, every answer —
including "not found" — is stored in `GeocodeCache`, so each query reaches OpenStreetMap once.
"""

from dataclasses import dataclass
from decimal import Decimal

from integrations.maps import Point, get_maps_provider

from .models import GeocodeCache, PinCode


@dataclass(frozen=True)
class Location:
    point: Point | None
    postal_code: str
    precision: str  # exact | pin | unknown
    label: str = ""
    city: str = ""  # typed, from the saved address, or from the PIN table (service areas use it)

    @property
    def known(self) -> bool:
        return self.point is not None


def _cached_geocode(key: str, **query) -> Point | None:
    row = GeocodeCache.objects.filter(query=key[:255]).first()
    if row is not None:
        return Point.of(row.latitude, row.longitude)
    provider = get_maps_provider()
    if provider.geocoder.name == "none":
        return None  # nothing to ask; don't cache so enabling geocoding later works
    result = provider.geocode(**query)
    GeocodeCache.objects.get_or_create(
        query=key[:255],
        defaults={
            "latitude": Decimal(str(round(result.point.latitude, 6))) if result else None,
            "longitude": Decimal(str(round(result.point.longitude, 6))) if result else None,
            "display_name": result.display_name if result else "",
            "source": provider.geocoder.name,
        },
    )
    return result.point if result else None


def pin_centroid(postal_code: str) -> Point | None:
    postal_code = (postal_code or "").strip()
    if not postal_code:
        return None
    pin = PinCode.objects.filter(postal_code=postal_code, is_active=True).first()
    if pin is not None:
        return Point.of(pin.latitude, pin.longitude)
    return _cached_geocode(f"pin:{postal_code}", postal_code=postal_code)


def resolve_location(*, address=None, postal_code: str = "", latitude=None, longitude=None, city: str = "") -> Location:
    city = (city or "").strip()
    if latitude is not None and longitude is not None:
        return Location(Point.of(latitude, longitude), (postal_code or "").strip(), "exact", city=city)
    if address is not None:
        label = ", ".join(filter(None, [address.area, address.city, address.postal_code]))
        city = address.city
        if address.latitude is not None and address.longitude is not None:
            return Location(
                Point.of(address.latitude, address.longitude), address.postal_code, "exact", label, city=city
            )
        query = ", ".join(
            filter(
                None, [address.address_line1, address.area, address.city, address.state, address.postal_code, "India"]
            )
        )
        if point := _cached_geocode(f"addr:{query.lower()}", query=query):
            return Location(point, address.postal_code, "exact", label, city=city)
        postal_code = address.postal_code
    postal_code = (postal_code or "").strip()
    if not city and postal_code:
        city = (
            PinCode.objects.filter(postal_code=postal_code, is_active=True).values_list("city", flat=True).first() or ""
        )
    if point := pin_centroid(postal_code):
        return Location(point, postal_code, "pin", postal_code, city=city)
    return Location(None, postal_code, "unknown", postal_code, city=city)
