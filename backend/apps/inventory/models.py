"""Stock per (store, variant) plus an append-only movement ledger.

Quantities:
- `available_quantity`: sellable right now.
- `reserved_quantity`:  held for placed orders that have not left the store yet.

Movement effects (applied only through `inventory.services`):
  purchase    available += n
  reservation available -= n, reserved += n
  release     reserved -= n, available += n     (order cancelled before pickup)
  sale        reserved -= n                     (order picked up; stock physically gone)
  return      available += n                    (returned item restocked)
  adjustment  available += n (n may be negative; stock count corrections)
Database CHECK constraints guarantee neither quantity can go negative.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class Inventory(TimeStampedModel):
    store = models.ForeignKey("stores.Store", on_delete=models.PROTECT, related_name="inventory")
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.PROTECT, related_name="inventory")
    available_quantity = models.IntegerField(default=0)
    reserved_quantity = models.IntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "inventory"
        ordering = ["store_id", "variant_id"]
        constraints = [
            models.UniqueConstraint(fields=["store", "variant"], name="uniq_inventory_store_variant"),
            models.CheckConstraint(condition=Q(available_quantity__gte=0), name="inventory_available_non_negative"),
            models.CheckConstraint(condition=Q(reserved_quantity__gte=0), name="inventory_reserved_non_negative"),
        ]
        indexes = [models.Index(fields=["variant", "is_active", "available_quantity"])]

    def __str__(self) -> str:
        return f"{self.variant} @ {self.store.code}: {self.available_quantity} avail / {self.reserved_quantity} rsv"

    @property
    def is_low_stock(self) -> bool:
        return self.available_quantity <= self.low_stock_threshold

    @property
    def on_hand_quantity(self) -> int:
        return self.available_quantity + self.reserved_quantity


class StockMovement(models.Model):
    class Type(models.TextChoices):
        PURCHASE = "purchase", "Purchase / stock received"
        RESERVATION = "reservation", "Reserved for order"
        RELEASE = "release", "Reservation released"
        SALE = "sale", "Sold (left store)"
        RETURN = "return", "Customer return restocked"
        ADJUSTMENT = "adjustment", "Manual adjustment"

    inventory = models.ForeignKey(Inventory, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=12, choices=Type.choices)
    quantity = models.IntegerField(help_text="Units moved. Positive, except adjustments which may be negative.")
    available_after = models.IntegerField()
    reserved_after = models.IntegerField()
    reason = models.CharField(max_length=255, blank=True)
    reference_type = models.CharField(max_length=40, blank=True, help_text="e.g. 'order', 'purchase_invoice'.")
    reference_id = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["inventory", "created_at"]),
            models.Index(fields=["reference_type", "reference_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.movement_type} {self.quantity} ({self.inventory_id})"
