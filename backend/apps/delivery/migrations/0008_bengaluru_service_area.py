"""Bengaluru as the shop's delivery city: every PIN code starting 560 (and the city names customers
type). The ring is an approximate outline of the city for map-pin-only addresses; admins can refine it."""

from decimal import Decimal

from django.db import migrations

# [[lat, lng], ...], roughly around the BBMP area and its edge suburbs (Yelahanka, Whitefield, Electronic City).
BENGALURU_RING = [
    [13.140, 77.480],
    [13.180, 77.580],
    [13.150, 77.700],
    [13.030, 77.790],
    [12.900, 77.790],
    [12.800, 77.700],
    [12.820, 77.560],
    [12.900, 77.450],
    [13.020, 77.420],
]


def create(apps, schema_editor):
    ServiceArea = apps.get_model("delivery", "ServiceArea")
    ServiceArea.objects.get_or_create(
        name="Bengaluru",
        defaults={
            "city_names": "Bengaluru, Bangalore, Bengaluru Urban, Bangalore Urban, Bengaluru City, Bangalore City",
            "postal_code_prefixes": "560",
            "polygon": BENGALURU_RING,
            "assumed_distance_km": Decimal("12.00"),
            "is_active": True,
        },
    )


def remove(apps, schema_editor):
    apps.get_model("delivery", "ServiceArea").objects.filter(name="Bengaluru").delete()


class Migration(migrations.Migration):
    dependencies = [("delivery", "0007_service_area")]

    operations = [migrations.RunPython(create, remove)]
