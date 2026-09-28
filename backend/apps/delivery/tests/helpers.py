"""Builders for the Phase 9 delivery tests. Distances are along a meridian, so they are easy to
reason about: 0.009° of latitude ≈ 1 km."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model

from apps.core.testing import create_address, create_store
from apps.delivery.locations import Location
from apps.delivery.models import DeliveryPartner, DeliveryZone
from integrations.maps import Point

STORE_LAT, STORE_LNG = Decimal("18.507400"), Decimal("73.807700")
KM = Decimal("0.009")  # degrees of latitude per km (approximately)
IST = ZoneInfo("Asia/Kolkata")
EVERY_DAY_9_TO_21 = {day: ["09:00", "21:00"] for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def ist(year, month, day, hour, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


def store_at(km_north: float = 0, *, riders: int = 1, zone: bool = False, **kwargs):
    """A store `km_north` of the reference point with `riders` in-house riders and no zone
    (add zones with `zone_for`), unless `zone=True` (default 5 km test zone)."""
    kwargs.setdefault("latitude", STORE_LAT + KM * Decimal(str(km_north)))
    kwargs.setdefault("longitude", STORE_LNG)
    return create_store(zone=zone, own_riders=riders, **kwargs)


def zone_for(store, radius="5", **kwargs) -> DeliveryZone:
    return DeliveryZone.objects.create(
        store=store, name=kwargs.pop("name", f"{radius} km"), radius_km=Decimal(radius), **kwargs
    )


def point(km_north: float) -> Point:
    return Point(float(STORE_LAT + KM * Decimal(str(km_north))), float(STORE_LNG))


def location_at(km_north: float, postal_code: str = "411038") -> Location:
    return Location(point(km_north), postal_code, "exact")


def address_at(user, km_north: float, **kwargs):
    kwargs.setdefault("postal_code", "411038")
    return create_address(user, latitude=STORE_LAT + KM * Decimal(str(km_north)), longitude=STORE_LNG, **kwargs)


def create_partner(store=None, *, email="rider1@example.com", status="available", **kwargs) -> DeliveryPartner:
    user = get_user_model().objects.create_user(
        email, "S3cure-pass!", role="delivery_partner", full_name=f"Rider {email.split('@')[0]}"
    )
    kwargs.setdefault("is_verified", True)
    return DeliveryPartner.objects.create(user=user, phone="9123456780", home_store=store, status=status, **kwargs)
