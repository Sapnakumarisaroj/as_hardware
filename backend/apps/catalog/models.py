"""Product catalog.

Design notes
- Category is a self-referencing tree. A *SubCategory* is a Category with a parent
  (exposed as a proxy model for the admin). Products carry both `category` (top level)
  and an optional `subcategory` that must be a child of it.
- Every purchasable unit is a **ProductVariant** (own SKU, MRP, price, weight). A simple
  product has exactly one variant; a wire sold in 1.5 / 2.5 / 4 sq mm has three. Inventory,
  cart lines and order lines always reference a variant, so there is one code path.
- Specifications are rows (name/value/unit), not columns, so any hardware type fits.
- Prices are GST-inclusive (Indian retail convention); `gst_rate` lets orders show the tax part.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils.text import slugify

from apps.core.models import SoftDeleteManager, SoftDeleteModel, TimeStampedModel
from apps.core.money import MONEY_FIELD_KWARGS, q
from apps.core.uploads import (
    ALLOWED_IMAGE_EXTENSIONS,
    brand_logo_path,
    category_image_path,
    product_image_path,
)
from apps.core.validators import MaxFileSizeValidator

IMAGE_VALIDATORS = [FileExtensionValidator(ALLOWED_IMAGE_EXTENSIONS), MaxFileSizeValidator(5)]


def normalize_sku(value: str) -> str:
    """SKUs are stored upper-case so uniqueness behaves identically on PostgreSQL, SQLite
    (case-sensitive) and MySQL/MariaDB (case-insensitive default collation)."""
    return (value or "").strip().upper()


class Category(SoftDeleteModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to=category_image_path, blank=True, validators=IMAGE_VALIDATORS)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        indexes = [models.Index(fields=["parent", "is_active", "sort_order"])]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return f"{self.parent.name} › {self.name}" if self.parent_id else self.name

    @property
    def is_subcategory(self) -> bool:
        return self.parent_id is not None

    def clean(self):
        # Two levels (category › subcategory) keeps navigation simple for customers.
        if self.parent_id:
            if self.parent_id == self.pk:
                raise ValidationError({"parent": "A category cannot be its own parent."})
            if self.parent.parent_id:
                raise ValidationError({"parent": "Subcategories cannot have their own subcategories."})
            if self.pk and self.children.exists():
                raise ValidationError({"parent": "A category with subcategories cannot become a subcategory."})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)


class SubCategoryManager(SoftDeleteManager):
    def get_queryset(self):
        return super().get_queryset().filter(parent__isnull=False)


class TopCategoryManager(SoftDeleteManager):
    def get_queryset(self):
        return super().get_queryset().filter(parent__isnull=True)


class TopCategory(Category):
    """Admin convenience: top-level categories only."""

    objects = TopCategoryManager()

    class Meta:
        proxy = True
        verbose_name = "category"
        verbose_name_plural = "categories"


class SubCategory(Category):
    """Admin convenience: categories that have a parent."""

    objects = SubCategoryManager()

    class Meta:
        proxy = True
        verbose_name = "subcategory"
        verbose_name_plural = "subcategories"


class Brand(SoftDeleteModel):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    logo = models.ImageField(upload_to=brand_logo_path, blank=True, validators=IMAGE_VALIDATORS)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)


class Product(SoftDeleteModel):
    class Unit(models.TextChoices):
        PIECE = "piece", "Piece"
        PACK = "pack", "Pack"
        BOX = "box", "Box"
        METRE = "m", "Metre"
        COIL = "coil", "Coil"
        KG = "kg", "Kilogram"
        LITRE = "l", "Litre"
        BAG = "bag", "Bag"
        PAIR = "pair", "Pair"
        SET = "set", "Set"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    sku = models.CharField(max_length=64, unique=True, help_text="Base/model SKU. Each variant has its own SKU.")
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.PROTECT, related_name="products")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    subcategory = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.PROTECT, related_name="subcategory_products"
    )
    short_description = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True, help_text='List of keywords, e.g. ["pvc", "1/2 inch"].')
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.PIECE)
    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("18.00"),
        validators=[MinValueValidator(0), MaxValueValidator(40)],
        help_text="GST % included in the selling price.",
    )
    hsn_code = models.CharField(max_length=8, blank=True)
    max_order_quantity = models.PositiveSmallIntegerField(default=50, validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True, help_text="Inactive products are hidden and cannot be bought.")
    is_published = models.BooleanField(default=False, help_text="Visible to customers once published.")
    is_featured = models.BooleanField(default=False)
    is_returnable = models.BooleanField(default=True)
    # Denormalised from approved reviews (maintained by reviews.services).
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal("0.00"))
    rating_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["category", "is_active", "is_published"]),
            models.Index(fields=["subcategory", "is_active", "is_published"]),
            models.Index(fields=["brand", "is_active"]),
            models.Index(fields=["is_featured", "is_published"]),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        if self.category_id and self.category.parent_id:
            raise ValidationError({"category": "Choose a top-level category; use 'subcategory' for the child."})
        if self.subcategory_id and self.subcategory.parent_id != self.category_id:
            raise ValidationError({"subcategory": "Subcategory must belong to the selected category."})
        if not isinstance(self.tags, list) or not all(isinstance(t, str) for t in self.tags):
            raise ValidationError({"tags": "Tags must be a list of strings."})
        self.sku = normalize_sku(self.sku)

    def save(self, *args, **kwargs):
        self.sku = normalize_sku(self.sku)
        if not self.slug:
            self.slug = slugify(self.name)[:220]
        super().save(*args, **kwargs)

    @property
    def is_purchasable(self) -> bool:
        return self.is_active and self.is_published and not self.is_deleted


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(
        max_length=120, blank=True, help_text='e.g. "2.5 sq mm, 90 m coil". Blank for simple products.'
    )
    attributes = models.JSONField(
        default=dict, blank=True, help_text='Variant-defining options, e.g. {"size": "2.5 sq mm"}.'
    )
    mrp = models.DecimalField(**MONEY_FIELD_KWARGS, validators=[MinValueValidator(Decimal("0.01"))])
    price = models.DecimalField(
        **MONEY_FIELD_KWARGS,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Selling price (GST inclusive).",
    )
    weight_grams = models.PositiveIntegerField(null=True, blank=True)
    length_mm = models.PositiveIntegerField(null=True, blank=True)
    width_mm = models.PositiveIntegerField(null=True, blank=True)
    height_mm = models.PositiveIntegerField(null=True, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        indexes = [models.Index(fields=["product", "is_active"])]
        constraints = [
            models.CheckConstraint(condition=Q(price__gt=0), name="variant_price_positive"),
            models.CheckConstraint(condition=Q(price__lte=F("mrp")), name="variant_price_lte_mrp"),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} — {self.name}" if self.name else self.product.name

    def clean(self):
        if self.price is not None and self.mrp is not None and self.price > self.mrp:
            raise ValidationError({"price": "Selling price cannot exceed MRP."})
        self.sku = normalize_sku(self.sku)

    def save(self, *args, **kwargs):
        self.sku = normalize_sku(self.sku)
        super().save(*args, **kwargs)

    @property
    def discount_amount(self) -> Decimal:
        return q(self.mrp - self.price)

    @property
    def discount_percent(self) -> Decimal:
        if not self.mrp:
            return Decimal("0.00")
        return q((self.mrp - self.price) * 100 / self.mrp)

    @property
    def display_name(self) -> str:
        return str(self)


class ProductImage(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=product_image_path, validators=IMAGE_VALIDATORS)
    alt_text = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary", "sort_order", "id"]

    def __str__(self) -> str:
        return f"Image {self.pk} of {self.product_id}"


class RecentSearch(models.Model):
    """A signed-in customer's recent search terms (shown as shortcuts; the customer can clear them)."""

    MAX_PER_USER = 10

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recent_searches")
    query = models.CharField(max_length=100)
    normalized = models.CharField(max_length=100)
    searched_at = models.DateTimeField()

    class Meta:
        ordering = ["-searched_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["user", "normalized"], name="uniq_recent_search_per_user")]

    def __str__(self) -> str:
        return self.query


class ProductSpecification(TimeStampedModel):
    """Flexible key/value spec, e.g. Power = 650 W. `numeric_value` enables range filters later."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="specifications")
    name = models.CharField(max_length=80)
    key = models.SlugField(max_length=80, help_text="Normalised name used for filtering, e.g. 'chuck-size'.")
    value = models.CharField(max_length=200)
    unit = models.CharField(max_length=20, blank=True)
    numeric_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [models.UniqueConstraint(fields=["product", "key"], name="uniq_product_spec_key")]
        indexes = [models.Index(fields=["key", "numeric_value"]), models.Index(fields=["key", "value"])]

    def __str__(self) -> str:
        return f"{self.name}: {self.value}{(' ' + self.unit) if self.unit else ''}"

    def save(self, *args, **kwargs):
        self.key = slugify(self.name)[:80]
        if self.numeric_value is None:
            try:
                self.numeric_value = Decimal(str(self.value).strip())
            except (ArithmeticError, ValueError):
                self.numeric_value = None
        super().save(*args, **kwargs)
