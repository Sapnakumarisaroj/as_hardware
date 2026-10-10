"""Bulk quote requests (RFQ) and the shop's quotations.

A professional buyer lists variants and quantities and asks for a price. Staff answer with a unit
price per line and a validity date; the customer accepts and checks out through the normal order
engine (`orders.services.place_order(quote=...)`), which re-checks stock, delivery and COD rules.
The quoted unit price replaces the catalogue price for that order only; automatic offers and
coupons never stack on top of a quotation.
"""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.core.money import MONEY_FIELD_KWARGS


class Quote(TimeStampedModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        QUOTED = "quoted", "Quoted"
        ACCEPTED = "accepted", "Accepted"
        ORDERED = "ordered", "Ordered"
        DECLINED = "declined", "Declined by customer"
        REJECTED = "rejected", "Rejected by shop"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    number = models.CharField(max_length=20, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="quotes")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    customer_note = models.CharField(max_length=1000, blank=True)
    # Where the goods would go (optional at request time; checkout asks again).
    address = models.ForeignKey(
        "accounts.Address", null=True, blank=True, on_delete=models.SET_NULL, related_name="quotes"
    )
    # Who asked, as the profile said at request time (shown to staff and on the quotation).
    buyer_type = models.CharField(max_length=20, blank=True)
    business_name = models.CharField(max_length=150, blank=True)
    gstin = models.CharField(max_length=15, blank=True)

    shop_note = models.CharField(max_length=1000, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    quoted_at = models.DateTimeField(null=True, blank=True)
    quoted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.CharField(max_length=255, blank=True)
    order = models.OneToOneField("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="quote")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"]), models.Index(fields=["status", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.number} ({self.status})"

    @property
    def is_expired(self) -> bool:
        return self.valid_until is not None and self.valid_until <= timezone.now()


class QuoteItem(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.PROTECT, related_name="+")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    customer_note = models.CharField(max_length=255, blank=True)
    # The catalogue price for this quantity when the line was requested (bulk tier applied); for staff.
    list_unit_price = models.DecimalField(**MONEY_FIELD_KWARGS)
    # Set by staff; GST inclusive like every price. Never above the variant's MRP.
    quoted_unit_price = models.DecimalField(**MONEY_FIELD_KWARGS, null=True, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1), name="quoteitem_quantity_positive"),
            models.UniqueConstraint(fields=["quote", "variant"], name="quoteitem_unique_variant"),
        ]

    def __str__(self) -> str:
        return f"{self.quote.number}: {self.variant_id} × {self.quantity}"

    @property
    def price_at_add(self):
        """Cart-line compatibility for the checkout preview (a quotation line has no "price when added")."""
        return self.quoted_unit_price if self.quoted_unit_price is not None else self.list_unit_price
