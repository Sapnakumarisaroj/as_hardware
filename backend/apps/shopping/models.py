"""Smart shopping (Phase 22): bundles of real catalogue products and "complete the project" rules.

Prices are never stored here: a bundle is priced by the shop's pricing engine every time it is shown, so its total
always matches what the cart will charge. Product-to-product links (needed with it, compatible, alternatives, goes
with) stay in `catalog.ProductRelation` (Phases 16 and 21); this app adds what those can't express.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import TimeStampedModel


class Bundle(TimeStampedModel):
    class Kind(models.TextChoices):
        DIY_REPAIR = "diy_repair", "DIY repair kit"
        PLUMBING = "plumbing", "Plumbing kit"
        ELECTRICAL = "electrical", "Electrical kit"
        PAINTING = "painting", "Painting kit"
        DRILLING = "drilling", "Drilling kit"
        TILING = "tiling", "Tile / fixing kit"
        CONSTRUCTION = "construction", "Basic construction kit"
        CUSTOM = "custom", "Custom kit"

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CUSTOM)
    description = models.CharField(max_length=300, blank=True)
    promo_label = models.CharField(max_length=40, blank=True, help_text='Optional badge, e.g. "Monsoon ready".')
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    priority = models.PositiveSmallIntegerField(default=100, help_text="Lower comes first.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["priority", "name"]
        indexes = [models.Index(fields=["is_active", "priority"])]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "End must be after start."})

    def is_live(self, now=None) -> bool:
        now = now or timezone.now()
        return (
            self.is_active
            and (self.starts_at is None or self.starts_at <= now)
            and (self.ends_at is None or self.ends_at > now)
        )


class BundleItem(models.Model):
    bundle = models.ForeignKey(Bundle, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="bundle_items")
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Empty = the product's default (or cheapest) variant.",
    )
    quantity = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(999)])
    note = models.CharField(max_length=120, blank=True)
    is_optional = models.BooleanField(default=False, help_text="Shown in the bundle, not ticked by default.")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [models.UniqueConstraint(fields=["bundle", "product"], name="uniq_bundle_product")]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.product_id}"


class RecommendationRule(TimeStampedModel):
    """ "Complete the project": customers looking at a product in `source_category` are shown popular, in-stock
    products of `target_category` (e.g. Wall Paints → Painting Tools). A category covers its subcategories."""

    source_category = models.ForeignKey(
        "catalog.Category", on_delete=models.CASCADE, related_name="recommendation_rules"
    )
    target_category = models.ForeignKey("catalog.Category", on_delete=models.CASCADE, related_name="+")
    label = models.CharField(max_length=60, blank=True, help_text='Shown as the reason, e.g. "Tools for painting".')
    priority = models.PositiveSmallIntegerField(default=100, help_text="Lower comes first.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["priority", "id"]
        constraints = [
            models.UniqueConstraint(fields=["source_category", "target_category"], name="uniq_recommendation_rule"),
            models.CheckConstraint(
                condition=~Q(source_category=F("target_category")), name="recommendation_rule_not_self"
            ),
        ]
        indexes = [models.Index(fields=["source_category", "is_active"])]

    def __str__(self) -> str:
        return f"{self.source_category_id} → {self.target_category_id}"
