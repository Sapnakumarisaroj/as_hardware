"""Physical stock locations.

Stores, dark stores and warehouses share one table (`kind`) so inventory has a single
foreign key. `Warehouse` is a proxy for admin convenience. Retail stores and dark stores
fulfil customer orders; warehouses hold replenishment stock.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import SoftDeleteManager, SoftDeleteModel
from apps.core.validators import phone_validator, postal_code_validator


class Store(SoftDeleteModel):
    class Kind(models.TextChoices):
        STORE = "store", "Retail store"
        DARK_STORE = "dark_store", "Dark store (delivery only)"
        WAREHOUSE = "warehouse", "Warehouse"

    FULFILLMENT_KINDS = (Kind.STORE, Kind.DARK_STORE)

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True, help_text="Short internal code, e.g. PUN-01.")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.STORE, db_index=True)
    phone = models.CharField(max_length=15, blank=True, validators=[phone_validator])
    email = models.EmailField(blank=True)
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    area = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=80)
    postal_code = models.CharField(max_length=6, validators=[postal_code_validator])
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    # {"mon": ["09:00", "21:00"], ..., "sun": null}. Empty = open all day, every day. A day that is
    # missing or null = closed. Used by the ETA engine (apps/delivery/eta.py).
    opening_hours = models.JSONField(
        default=dict,
        blank=True,
        help_text='e.g. {"mon": ["09:00", "21:00"], "sun": null}. Empty = always open; missing/null day = closed.',
    )
    avg_prep_minutes = models.PositiveSmallIntegerField(
        default=10, help_text="Pick-and-pack time for an order with one line (ETA engine)."
    )
    prep_minutes_per_item = models.PositiveSmallIntegerField(
        default=1, help_text="Extra pick-and-pack minutes for each additional order line."
    )
    own_riders = models.PositiveSmallIntegerField(
        default=0,
        help_text="In-house riders on duty who don't use the partner app. Added to available app partners "
        "when estimating delivery capacity.",
    )
    is_active = models.BooleanField(default=True)
    is_demo = models.BooleanField(default=False, db_index=True, editable=False, help_text="Created by the demo seed.")
    accepts_orders = models.BooleanField(default=True, help_text="Temporarily pause new orders without deactivating.")
    cod_enabled = models.BooleanField(default=True, help_text="Allow cash on delivery for orders shipped from here.")
    # Store managers only see inventory/orders of stores they are assigned to.
    managers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="managed_stores",
        limit_choices_to={"role": "store_manager"},
    )

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["kind", "is_active", "accepts_orders"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def clean(self):
        self.code = (self.code or "").strip().upper()

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()  # identical uniqueness on every DB vendor
        super().save(*args, **kwargs)

    @property
    def can_fulfill_orders(self) -> bool:
        return self.is_active and self.accepts_orders and self.kind in self.FULFILLMENT_KINDS


class WarehouseManager(SoftDeleteManager):
    def get_queryset(self):
        return super().get_queryset().filter(kind=Store.Kind.WAREHOUSE)


class Warehouse(Store):
    objects = WarehouseManager()

    class Meta:
        proxy = True

    def save(self, *args, **kwargs):
        self.kind = Store.Kind.WAREHOUSE
        super().save(*args, **kwargs)
