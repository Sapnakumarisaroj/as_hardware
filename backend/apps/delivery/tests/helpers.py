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


# --- Phase 10: jobs ------------------------------------------------------------------------------

JOB_STEPS = ("accepted", "picked_up", "out_for_delivery")


def packed_order(user, *pairs, method: str = "cod", km_north: float = 2, actor=None):
    """An order for (variant, quantity) pairs, confirmed (online orders paid) and packed."""
    from apps.carts.services import add_item
    from apps.orders.services import place_order, transition_order
    from apps.orders.tests.helpers import pay

    for variant, quantity in pairs:
        add_item(user, variant.id, quantity)
    order, payment = place_order(user=user, address_id=address_at(user, km_north).id, payment_method=method)
    if method == "online":
        pay(order, payment)
        order.refresh_from_db()
    for status in ("processing", "packed"):
        order = transition_order(order, status, actor=actor)
    return order


def assign(shipment, partner, actor=None):
    from apps.delivery.assignment import assign_shipment

    return assign_shipment(shipment, partner, actor=actor)


def delivery_code(job) -> str:
    """The code as the customer sees it on the order page."""
    from apps.delivery import otp

    job.refresh_from_db()
    return otp.code_for_customer(job)


def advance(job, to: str):
    """Walk a fresh job forward as its rider: accepted → picked_up → out_for_delivery."""
    from apps.delivery import workflow

    rider = job.partner.user
    steps = {"accepted": workflow.accept, "picked_up": workflow.pickup, "out_for_delivery": workflow.start_delivery}
    job.refresh_from_db()
    done = JOB_STEPS.index(job.status) + 1 if job.status in JOB_STEPS else 0
    for step in JOB_STEPS[done : JOB_STEPS.index(to) + 1]:
        steps[step](job.pk, rider=rider)
    job.refresh_from_db()
    return job


def deliver_job(job, **kwargs):
    """Complete a job that is out for delivery, with the right code and the cash that is due."""
    from apps.delivery import workflow

    job.refresh_from_db()
    if job.cod_amount_due > 0:
        kwargs.setdefault("cod", {"collected": True, "amount": job.cod_amount_due, "method": "cash"})
    return workflow.complete_delivery(job.pk, rider=job.partner.user, code=delivery_code(job), **kwargs)


def photo(fmt: str = "JPEG", size=(640, 480), exif: bool = False, name: str | None = None):
    """An uploaded picture, optionally carrying EXIF data (as phone cameras add)."""
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    image = Image.new("RGB", size, (200, 120, 40))
    out = io.BytesIO()
    extra = {}
    if exif:
        data = Image.Exif()
        data[0x010F] = "PhoneMaker"  # Make
        data[0x0110] = "Secret Model X"  # Model
        extra["exif"] = data.tobytes()
    image.save(out, format=fmt, **extra)
    ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}[fmt]
    return SimpleUploadedFile(name or f"door.{ext}", out.getvalue(), content_type=f"image/{fmt.lower()}")
