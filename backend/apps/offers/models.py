"""Coupons (customer enters a code) and offers (applied automatically).

Coupon rules live in `offers.services`; the automatic offer engine is `offers.engine`
(Phase 6). Both are applied by `orders.pricing.price_lines`: offers first, then the coupon.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.core.money import MONEY_FIELD_KWARGS


class DiscountType(models.TextChoices):
    PERCENT = "percent", "Percentage"
    FIXED = "fixed", "Fixed amount"


class DiscountRuleMixin(models.Model):
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices)
    value = models.DecimalField(**MONEY_FIELD_KWARGS, validators=[MinValueValidator(Decimal("0.01"))])
    max_discount_amount = models.DecimalField(
        **MONEY_FIELD_KWARGS, null=True, blank=True, help_text="Cap for percentage discounts."
    )
    min_order_value = models.DecimalField(**MONEY_FIELD_KWARGS, default=Decimal("0.00"))
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True

    def clean(self):
        if self.discount_type == DiscountType.PERCENT and self.value is not None and self.value > 100:
            raise ValidationError({"value": "Percentage cannot exceed 100."})
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "End must be after start."})


class Coupon(DiscountRuleMixin, TimeStampedModel):
    code = models.CharField(max_length=30, unique=True, help_text="Stored upper-case.")
    description = models.CharField(max_length=255, blank=True)
    usage_limit = models.PositiveIntegerField(
        null=True, blank=True, help_text="Total redemptions allowed; blank = unlimited."
    )
    per_customer_limit = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)
    show_in_checkout = models.BooleanField(
        default=False,
        help_text="List this code under 'Available coupons' at checkout. Leave off for private/partner codes.",
    )
    # Empty = applies to the whole cart. Otherwise only matching lines count towards the discount.
    products = models.ManyToManyField("catalog.Product", blank=True, related_name="coupons")
    categories = models.ManyToManyField("catalog.Category", blank=True, related_name="coupons")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["is_active", "starts_at", "ends_at"])]
        constraints = [
            models.CheckConstraint(
                condition=~Q(discount_type="percent") | Q(value__lte=100), name="coupon_percent_lte_100"
            ),
        ]

    def __str__(self) -> str:
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)


class CouponRedemption(models.Model):
    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, related_name="redemptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="coupon_redemptions")
    order = models.OneToOneField("orders.Order", on_delete=models.CASCADE, related_name="coupon_redemption")
    discount_amount = models.DecimalField(**MONEY_FIELD_KWARGS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["coupon", "user"])]

    def __str__(self) -> str:
        return f"{self.coupon.code} on {self.order_id}"


class Offer(DiscountRuleMixin, TimeStampedModel):
    """Automatic promotion targeting products and/or categories (none = whole cart). See `offers.engine`.

    Phase 15 additions (all optional, defaults keep the Phase 6 behaviour):
    - `benefit`: a discount (percent/fixed, as before) or free delivery for the order.
    - `min_quantity`: a line counts only when it has at least this many units ("10+ bags: 5% off").
    - `max_prior_orders`: only for customers with at most this many earlier orders (0 = first order only;
      4 = first five orders). Visitors who are not signed in never get these.
    - `campaign`: a label such as "Diwali" shown with the offer (festival offers are date-bound offers).
    - `usage_limit` / `per_customer_limit`: orders that may use the offer, counted by `OfferRedemption`.
    """

    class Benefit(models.TextChoices):
        DISCOUNT = "discount", "Discount"
        FREE_DELIVERY = "free_delivery", "Free delivery"

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    products = models.ManyToManyField("catalog.Product", blank=True, related_name="offers")
    categories = models.ManyToManyField("catalog.Category", blank=True, related_name="offers")
    priority = models.PositiveSmallIntegerField(default=100, help_text="Lower number wins when offers overlap.")
    # Free-delivery offers have no amount, so 0 is allowed here; `clean` requires > 0 for discounts.
    value = models.DecimalField(**MONEY_FIELD_KWARGS, default=Decimal("0.00"), validators=[MinValueValidator(0)])
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT)
    benefit = models.CharField(max_length=15, choices=Benefit.choices, default=Benefit.DISCOUNT)
    min_quantity = models.PositiveIntegerField(
        default=0, help_text="Each counted line needs at least this many units (0 = any quantity)."
    )
    max_prior_orders = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Only customers with at most this many earlier orders (0 = first order only)."
    )
    campaign = models.CharField(max_length=60, blank=True, help_text='Festival or campaign label, e.g. "Diwali".')
    usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Orders in total; blank = unlimited.")
    per_customer_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Orders per customer.")
    used_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["priority", "-starts_at"]
        indexes = [models.Index(fields=["is_active", "starts_at", "ends_at"])]
        constraints = [
            models.CheckConstraint(
                condition=~Q(discount_type="percent") | Q(value__lte=100), name="offer_percent_lte_100"
            ),
            models.CheckConstraint(condition=Q(value__gte=0), name="offer_value_non_negative"),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        super().clean()
        if self.benefit == self.Benefit.DISCOUNT and (self.value is None or self.value <= 0):
            raise ValidationError({"value": "Enter the discount (more than 0)."})

    @property
    def is_free_delivery(self) -> bool:
        return self.benefit == self.Benefit.FREE_DELIVERY


class OfferRedemption(models.Model):
    """An order that used an offer (for usage limits). Removed again when the order is cancelled."""

    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="offer_redemptions")
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="offer_redemptions")
    discount_amount = models.DecimalField(**MONEY_FIELD_KWARGS, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["offer", "user"])]
        constraints = [models.UniqueConstraint(fields=["offer", "order"], name="uniq_offer_redemption_order")]

    def __str__(self) -> str:
        return f"{self.offer_id} on {self.order_id}"
