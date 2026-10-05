"""Loyalty credits and cashback (Phase 17).

Credits are shop credit, never cash. Every change is a `CreditEntry` row; a customer's balance is the
sum of their counted entries and is never stored. Credit entries (cashback, promotional, referral,
restored) are *lots* with their own expiry; debits (redemption, expiry) say which lots they used through
`CreditAllocation`, oldest-expiring first. Rules: `LoyaltySettings` (share of an order, expiry, referral
rewards), `CashbackRule` (who earns how much). See docs/ARCHITECTURE.md → Loyalty credits.
"""

import secrets
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.core.money import MONEY_FIELD_KWARGS


class LoyaltySettings(models.Model):
    """Shop-wide credit rules (one row, pk=1), changed by administrators in the dashboard."""

    credits_enabled = models.BooleanField(default=True, help_text="Customers can use credits at checkout.")
    max_order_share = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("20.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        help_text="Credits pay at most this % of an order (goods after offers and coupon).",
    )
    expiry_days = models.PositiveSmallIntegerField(
        default=90,
        validators=[MinValueValidator(1), MaxValueValidator(3650)],
        help_text="Each credit expires this many days after it becomes available.",
    )
    referral_reward = models.DecimalField(
        **MONEY_FIELD_KWARGS,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Credit for the person who referred a new customer, after that customer's first order "
        "is delivered and its return window has passed. 0 = off.",
    )
    referee_reward = models.DecimalField(
        **MONEY_FIELD_KWARGS,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Credit for the new customer on the same terms. 0 = off.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "loyalty settings"
        verbose_name_plural = "loyalty settings"

    def __str__(self) -> str:
        return "Loyalty settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "LoyaltySettings":
        row, _ = cls.objects.get_or_create(pk=1)
        return row


class CreditEntry(models.Model):
    """One line of a customer's credit ledger. Credits are positive, debits negative."""

    class Kind(models.TextChoices):
        CASHBACK = "cashback", "Cashback"
        PROMO = "promo", "Promotional credit"
        REFERRAL = "referral", "Referral reward"
        RESTORE = "restore", "Credits given back"
        REDEMPTION = "redemption", "Used on an order"
        EXPIRY = "expiry", "Expired"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"  # earned on an order that isn't delivered yet
        ELIGIBLE = "eligible", "Eligible"  # delivered; usable once the return window ends (`available_at`)
        AVAILABLE = "available", "Credited"  # usable until `expires_at`
        EXPIRED = "expired", "Expired"  # a lot whose unused part expired (offset by an expiry debit)
        REVERSED = "reversed", "Reversed"  # pending credit cancelled (order cancelled or returned)
        POSTED = "posted", "Posted"  # debits

    CREDIT_KINDS = (Kind.CASHBACK, Kind.PROMO, Kind.REFERRAL, Kind.RESTORE)
    #: Credits earned but not usable yet.
    WAITING = (Status.PENDING, Status.ELIGIBLE)
    DEBIT_KINDS = (Kind.REDEMPTION, Kind.EXPIRY)
    #: Entries that make up the balance. An expired lot still counts: its expiry debit offsets it.
    COUNTED = (Status.AVAILABLE, Status.EXPIRED, Status.POSTED)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="credit_entries")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices)
    amount = models.DecimalField(**MONEY_FIELD_KWARGS)
    available_at = models.DateTimeField(null=True, blank=True, help_text="When a pending credit becomes usable.")
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    order = models.ForeignKey(
        "orders.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="credit_entries"
    )
    return_request = models.ForeignKey(
        "orders.ReturnRequest", null=True, blank=True, on_delete=models.PROTECT, related_name="credit_entries"
    )
    source = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="derived",
        help_text="Restored credits: the lot they were used from. Replacement cashback: the one replaced.",
    )
    reference = models.CharField(max_length=80, help_text="Order number, return number or why (required).")
    description = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "available_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(Q(kind__in=["cashback", "promo", "referral", "restore"]) & Q(amount__gt=0))
                | (Q(kind__in=["redemption", "expiry"]) & Q(amount__lt=0)),
                name="credit_entry_sign_matches_kind",
            ),
            models.CheckConstraint(condition=~Q(reference=""), name="credit_entry_has_reference"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.kind} {self.amount} ({self.status})"

    @property
    def is_credit(self) -> bool:
        return self.kind in self.CREDIT_KINDS


class CreditAllocation(models.Model):
    """How much of a credit lot a debit used (redemptions and expiries)."""

    debit = models.ForeignKey(CreditEntry, on_delete=models.CASCADE, related_name="allocations")
    lot = models.ForeignKey(CreditEntry, on_delete=models.PROTECT, related_name="used_by")
    amount = models.DecimalField(**MONEY_FIELD_KWARGS)

    class Meta:
        indexes = [models.Index(fields=["lot"])]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="credit_allocation_positive")]

    def __str__(self) -> str:
        return f"{self.amount} of {self.lot_id} for {self.debit_id}"


class CashbackRule(TimeStampedModel):
    """Cashback earned on an order: a % of what the customer pays for eligible items, credited as pending
    when the order is placed and usable once the return window after delivery has passed."""

    class RewardType(models.TextChoices):
        PERCENT = "percent", "% of eligible items"
        FIXED = "fixed", "Fixed amount per order"

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    reward_type = models.CharField(max_length=10, choices=RewardType.choices, default=RewardType.PERCENT)
    percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("100.00"))],
        help_text="For % rules.",
    )
    fixed_amount = models.DecimalField(
        **MONEY_FIELD_KWARGS,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="For fixed rules: credit per qualifying order (never more than the eligible amount).",
    )
    max_amount = models.DecimalField(
        **MONEY_FIELD_KWARGS, null=True, blank=True, help_text="Largest cashback per order. Blank = no cap."
    )
    min_order_value = models.DecimalField(
        **MONEY_FIELD_KWARGS,
        default=Decimal("0.00"),
        help_text="Eligible items must total at least this (after offers, coupon and credits).",
    )
    products = models.ManyToManyField("catalog.Product", blank=True, related_name="cashback_rules")
    categories = models.ManyToManyField("catalog.Category", blank=True, related_name="cashback_rules")
    first_order_only = models.BooleanField(default=False)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveSmallIntegerField(default=100, help_text="Lower wins when several rules apply.")

    class Meta:
        ordering = ["priority", "-starts_at", "id"]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "End must be after start."})
        if self.reward_type == self.RewardType.PERCENT and not self.percent:
            raise ValidationError({"percent": "Enter the cashback %."})
        if self.reward_type == self.RewardType.FIXED and not self.fixed_amount:
            raise ValidationError({"fixed_amount": "Enter the cashback amount."})

    @property
    def summary(self) -> str:
        if self.reward_type == self.RewardType.FIXED:
            return f"₹{self.fixed_amount.normalize():f} cashback"
        return f"{self.percent.normalize():f}% cashback"


def _referral_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


class ReferralCode(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referral_code")
    code = models.CharField(max_length=12, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.code

    @classmethod
    def for_user(cls, user) -> "ReferralCode":
        existing = cls.objects.filter(user=user).first()
        if existing:
            return existing
        for _ in range(10):
            code = _referral_code()
            if not cls.objects.filter(code=code).exists():
                return cls.objects.create(user=user, code=code)
        raise RuntimeError("Could not allocate a referral code.")


class Referral(models.Model):
    """A new customer who joined with someone's code. Rewards (if switched on) follow their first
    delivered order, after its return window. One referral per new customer (`referee` is unique)."""

    class Status(models.TextChoices):
        JOINED = "joined", "Joined, no delivered order yet"
        REWARDED = "rewarded", "Reward earned"
        NO_REWARD = "no_reward", "First order delivered, rewards were off"

    referrer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referrals_made")
    referee = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="referred_by")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.JOINED)
    created_at = models.DateTimeField(auto_now_add=True)
    rewarded_order = models.ForeignKey(
        "orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [models.CheckConstraint(condition=~Q(referrer=models.F("referee")), name="referral_not_self")]

    def __str__(self) -> str:
        return f"{self.referrer_id} → {self.referee_id}"
