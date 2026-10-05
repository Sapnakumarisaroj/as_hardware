"""Product catalog.

Design notes
- Category is a self-referencing tree of at most three levels (Phase 15): department ›
  category › subcategory, e.g. Civil & Interiors › Cement › Grey Cement. A *SubCategory* is a
  Category with a parent (proxy model for the admin). Products carry `category` (level 1 or 2)
  and an optional `subcategory` that must be a direct child of it, so the Phase 4 shape
  (top-level category + child) keeps working unchanged. Tree helpers: `catalog.tree`.
- Every purchasable unit is a **ProductVariant** (own SKU, MRP, price, weight). A simple
  product has exactly one variant; a wire sold in 1.5 / 2.5 / 4 sq mm has three. Inventory,
  cart lines and order lines always reference a variant, so there is one code path.
- Specifications are rows (name/value/unit), not columns, so any hardware type fits.
- Prices are GST-inclusive (Indian retail convention); `gst_rate` lets orders show the tax part.
- Bulk pricing (Phase 15): `VariantPriceTier` rows give a lower unit price from a minimum
  quantity. `orders.pricing.line_from_variant` picks the tier; nothing else prices a line.
- Options (Phase 15): `OptionType` (Grade, Bag size, …) with `OptionValue`s; each variant's
  choice is a `VariantOption` row. `ProductVariant.attributes` stays as the display copy.
- Curated lists (Phase 15): `Collection` (manual picks or automatic rules) + `CollectionItem`.
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


def valid_faqs(value) -> bool:
    """[{"question": str, "answer": str}, …] with both texts filled."""
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict) or set(item) - {"question", "answer"}:
            return False
        question, answer = item.get("question"), item.get("answer")
        if not isinstance(question, str) or not isinstance(answer, str) or not question.strip() or not answer.strip():
            return False
    return True


def unique_slug(instance, max_length: int) -> str:
    """A slug from the name that no other row (deleted ones included) uses: "drill", "drill-2", …"""
    base = slugify(instance.name)[: max_length - 4] or "item"
    rows = type(instance)._base_manager.exclude(pk=instance.pk) if instance.pk else type(instance)._base_manager
    slug, n = base, 2
    while rows.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


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

    MAX_DEPTH = 3  # department › category › subcategory

    @property
    def level(self) -> int:
        """1 for a department/top-level category, 2 for its children, 3 below that."""
        from .tree import level_of

        return level_of(self.pk, parent_id=self.parent_id)

    def clean(self):
        from .tree import ancestor_ids, subtree_height

        if not self.parent_id:
            return
        if self.pk and self.parent_id == self.pk:
            raise ValidationError({"parent": "A category cannot be its own parent."})
        parents = ancestor_ids(self.parent_id)  # the parent and everything above it
        if self.pk and self.pk in parents:
            raise ValidationError({"parent": "A category cannot be moved under one of its own subcategories."})
        below = subtree_height(self.pk) if self.pk else 0  # levels under this category
        if len(parents) + 1 + below > self.MAX_DEPTH:
            limit = f"Categories can be at most {self.MAX_DEPTH} levels deep"
            raise ValidationError({"parent": f"{limit} (department › category › subcategory)."})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, 140)
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
            self.slug = unique_slug(self, 140)
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
    launch_date = models.DateField(
        null=True, blank=True, help_text="When the product was launched; drives the automatic 'New launches' list."
    )
    # Phase 16 product-page content, written by the shop (all optional; a section is shown only when filled).
    quick_answer = models.CharField(
        max_length=300,
        blank=True,
        help_text='One-line answer shown near the price, e.g. "Use for RCC slabs and columns".',
    )
    uses = models.TextField(blank=True, help_text="Recommended uses, one per line.")
    installation_steps = models.TextField(blank=True, help_text="Installation / usage steps, one per line, in order.")
    faqs = models.JSONField(
        default=list, blank=True, help_text='Questions and answers: [{"question": "…", "answer": "…"}].'
    )
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
        if self.category_id and self.category.level >= Category.MAX_DEPTH:
            raise ValidationError(
                {"category": "Choose a department or a category; put the most specific level in 'subcategory'."}
            )
        if self.subcategory_id and self.subcategory.parent_id != self.category_id:
            raise ValidationError({"subcategory": "Subcategory must belong to the selected category."})
        if not isinstance(self.tags, list) or not all(isinstance(t, str) for t in self.tags):
            raise ValidationError({"tags": "Tags must be a list of strings."})
        if not valid_faqs(self.faqs):
            raise ValidationError({"faqs": 'FAQs must be a list of {"question": "…", "answer": "…"} with both filled.'})
        self.sku = normalize_sku(self.sku)

    def save(self, *args, **kwargs):
        self.sku = normalize_sku(self.sku)
        if not self.slug:
            self.slug = unique_slug(self, 220)
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


class ProductEmbedding(models.Model):
    """The search vector of one product (Phase 13). Derived data: safe to delete and rebuild.

    `embedder` names the vector space (`hashing-v1-512`, `st:<model>`), `text_hash` fingerprints the
    product text that was embedded, so a product is only embedded again when its words change.
    """

    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="embedding")
    embedder = models.CharField(max_length=160)
    dimensions = models.PositiveSmallIntegerField()
    vector = models.BinaryField(help_text="little-endian float32 values")
    text_hash = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["embedder"])]

    def __str__(self) -> str:
        return f"embedding of product {self.product_id} ({self.embedder})"


# --- Phase 15: bulk pricing ------------------------------------------------------------------


class VariantPriceTier(TimeStampedModel):
    """A lower unit price from `min_quantity` units of one variant ("10+ bags: ₹415").

    The variant's own `price` is the tier for 1 unit up to the first `min_quantity` − 1. Rules
    (checked by `catalog.services.set_price_tiers`, guarded by constraints): min_quantity ≥ 2 and
    unique per variant (so ranges can't overlap), price > 0 and ≤ MRP, and a higher quantity never
    has a higher price than a lower one (variant price included).
    """

    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="price_tiers")
    min_quantity = models.PositiveIntegerField(validators=[MinValueValidator(2)])
    unit_price = models.DecimalField(**MONEY_FIELD_KWARGS, validators=[MinValueValidator(Decimal("0.01"))])

    class Meta:
        ordering = ["variant_id", "min_quantity"]
        constraints = [
            models.UniqueConstraint(fields=["variant", "min_quantity"], name="uniq_variant_tier_quantity"),
            models.CheckConstraint(condition=Q(min_quantity__gte=2), name="tier_min_quantity_gte_2"),
            models.CheckConstraint(condition=Q(unit_price__gt=0), name="tier_price_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.variant_id}: {self.min_quantity}+ at {self.unit_price}"


# --- Phase 15: structured options --------------------------------------------------------------


class OptionType(TimeStampedModel):
    """A way variants differ: Brand, Grade, Bag size, Thickness, Length, Colour, Pack size…

    `categories` limits where the option is offered (a category also covers everything below it);
    none = any product.
    """

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=70, unique=True)
    unit = models.CharField(max_length=20, blank=True, help_text='Shown after values, e.g. "kg" or "mm".')
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    categories = models.ManyToManyField(Category, blank=True, related_name="option_types")

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:70] or "option"
        super().save(*args, **kwargs)


class OptionValue(TimeStampedModel):
    option_type = models.ForeignKey(OptionType, on_delete=models.CASCADE, related_name="values")
    value = models.CharField(max_length=80)
    slug = models.SlugField(max_length=90)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["option_type_id", "sort_order", "id"]
        constraints = [models.UniqueConstraint(fields=["option_type", "slug"], name="uniq_option_value_slug")]

    def __str__(self) -> str:
        return f"{self.option_type.name}: {self.value}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.value)[:90] or "value"
        super().save(*args, **kwargs)


class VariantOption(models.Model):
    """The value a variant has for one option type (one row per type)."""

    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="option_values")
    option_type = models.ForeignKey(OptionType, on_delete=models.PROTECT, related_name="+")
    value = models.ForeignKey(OptionValue, on_delete=models.PROTECT, related_name="variant_options")

    class Meta:
        ordering = ["option_type__sort_order", "option_type__name"]
        constraints = [models.UniqueConstraint(fields=["variant", "option_type"], name="uniq_variant_option_type")]
        indexes = [models.Index(fields=["value", "variant"])]

    def __str__(self) -> str:
        return f"{self.variant_id}: {self.value}"

    def clean(self):
        if self.value_id and self.option_type_id and self.value.option_type_id != self.option_type_id:
            raise ValidationError({"value": "This value belongs to another option."})


# --- Phase 15: curated product lists -----------------------------------------------------------


class Collection(TimeStampedModel):
    """A product list for the shop front: "Deals of the week", "Construction essentials", …

    `rule` decides where the products come from:
    - manual: the chosen `CollectionItem`s, in their order
    - best_sellers: most units sold in the last `window_days` days (real orders only)
    - new_launches: newest `launch_date` (else creation date) within `window_days`
    - bulk_pricing: products with at least one bulk price tier
    Automatic rules can be narrowed with `categories` (a category covers its subcategories).
    Only published, active products are ever listed; an empty list is simply not shown.
    """

    class Rule(models.TextChoices):
        MANUAL = "manual", "Chosen products"
        BEST_SELLERS = "best_sellers", "Best sellers (from orders)"
        NEW_LAUNCHES = "new_launches", "New launches (by launch date)"
        BULK_PRICING = "bulk_pricing", "Products with bulk prices"

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.CharField(max_length=300, blank=True)
    rule = models.CharField(max_length=20, choices=Rule.choices, default=Rule.MANUAL)
    window_days = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(1), MaxValueValidator(365)],
        help_text="Best sellers / new launches: how many days back to look.",
    )  # fmt: skip
    max_items = models.PositiveSmallIntegerField(default=12, validators=[MinValueValidator(1), MaxValueValidator(60)])
    categories = models.ManyToManyField(Category, blank=True, related_name="collections")
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        indexes = [models.Index(fields=["is_active", "sort_order"])]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "End must be after start."})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, 140)
        super().save(*args, **kwargs)

    def is_live(self, now=None) -> bool:
        from django.utils import timezone

        now = now or timezone.now()
        return (
            self.is_active
            and (self.starts_at is None or self.starts_at <= now)
            and (self.ends_at is None or self.ends_at > now)
        )


class CollectionItem(models.Model):
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="collection_items")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [models.UniqueConstraint(fields=["collection", "product"], name="uniq_collection_product")]

    def __str__(self) -> str:
        return f"{self.collection_id}: {self.product_id}"


class ProductRelation(models.Model):
    """A product the shop links to another (Phase 16): "Recommended accessories" on the product page.
    Chosen by staff; the page shows only published, active, in-catalogue products."""

    class Kind(models.TextChoices):
        ACCESSORY = "accessory", "Accessory / goes with"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="relations")
    related = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="related_from")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.ACCESSORY)
    note = models.CharField(
        max_length=120, blank=True, help_text='Why it goes with the product, e.g. "Needed to fix it".'
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["product", "related", "kind"], name="uniq_product_relation"),
            models.CheckConstraint(condition=~Q(product=F("related")), name="product_relation_not_self"),
        ]

    def __str__(self) -> str:
        return f"{self.product_id} → {self.related_id} ({self.kind})"

    def clean(self):
        if self.product_id and self.product_id == self.related_id:
            raise ValidationError({"related": "A product can't be its own accessory."})
