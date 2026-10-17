from datetime import date, datetime
from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import models as db_models
from django.forms.models import BaseInlineFormSet
from django.utils import timezone

from apps.core.admin import AdminRoleRequiredMixin
from apps.core.audit import record_audit
from apps.inventory.models import Inventory

from . import services
from .models import (
    Brand,
    Category,
    Collection,
    CollectionItem,
    OptionType,
    OptionValue,
    Product,
    ProductImage,
    ProductRelation,
    ProductSpecification,
    ProductVariant,
    RecentSearch,
    SubCategory,
    TopCategory,
    VariantOption,
    VariantPriceTier,
    normalize_sku,
)


def _jsonable(value):
    """A form value as something the AuditLog JSON column can store."""
    if isinstance(value, db_models.Model):
        return value.pk
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float, str, list, dict)):
        return value
    return str(value)


def _form_changes(form) -> dict:
    """{field: [before, after]} for the fields an admin form changed."""
    return {
        field: [_jsonable(form.initial.get(field)), _jsonable(form.cleaned_data.get(field))]
        for field in form.changed_data
    }


def variant_delete_blocker(variant: ProductVariant) -> str | None:
    """Why a variant must not be deleted (orders, stock or quotes point at it), or None.

    Order items keep only a nullable link, so deleting would silently cut a sale off its product;
    stock rows and quotes protect the variant. Such variants are switched off instead."""
    from apps.quotes.models import QuoteItem

    if variant.order_items.exists():
        used = "it appears on customer orders"
    elif variant.inventory.exists():
        used = "it has stock records"
    elif QuoteItem.objects.filter(variant=variant).exists():
        used = "it appears on quotes"
    else:
        return None
    return f"Variant {variant.sku} can't be deleted because {used}. Untick 'Active' to stop selling it instead."


class SubCategoryInline(admin.TabularInline):
    model = SubCategory
    fk_name = "parent"
    fields = ("name", "slug", "sort_order", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    extra = 0


@admin.register(TopCategory)
class CategoryAdmin(AdminRoleRequiredMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "subcategory_count", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    exclude = ("parent", "is_deleted", "deleted_at")
    inlines = [SubCategoryInline]

    @admin.display(description="Subcategories")
    def subcategory_count(self, obj):
        return obj.children.count()


@admin.register(SubCategory)
class SubCategoryAdmin(AdminRoleRequiredMixin, admin.ModelAdmin):
    list_display = ("name", "parent", "slug", "sort_order", "is_active")
    list_filter = ("parent", "is_active")
    search_fields = ("name", "slug", "parent__name")
    prepopulated_fields = {"slug": ("name",)}
    exclude = ("is_deleted", "deleted_at")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Phase 15: any category can be a parent; the model refuses a fourth level or a loop.
        if db_field.name == "parent":
            kwargs["queryset"] = Category.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Brand)
class BrandAdmin(AdminRoleRequiredMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    exclude = ("is_deleted", "deleted_at")


class VariantInlineFormSet(BaseInlineFormSet):
    """The product's variants as one set: a published product keeps an active variant, a price edit
    can't leave a bulk-price tier dearer than the new price, and variants that orders, stock or
    quotes point at are never deleted (they are switched off instead)."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active = 0
        for form in self.forms:
            if not getattr(form, "cleaned_data", None):
                continue
            variant = form.instance
            if self.can_delete and self._should_delete_form(form):
                blocker = variant.pk and variant_delete_blocker(variant)
                if blocker:
                    raise ValidationError(blocker)
                continue
            if form.cleaned_data.get("is_active"):
                active += 1
            tiers = list(variant.price_tiers.values("min_quantity", "unit_price")) if variant.pk else []
            if tiers:
                try:
                    services.validate_price_tiers(variant, tiers)
                except services.CatalogRuleError as exc:
                    form.add_error("price", f"{exc.detail} Change the bulk prices in the dashboard first.")
        if self.instance.is_published and not active:
            raise ValidationError("A published product needs at least one active variant with an approved price.")


class VariantInline(admin.TabularInline):
    model = ProductVariant
    formset = VariantInlineFormSet
    fields = (
        "sku", "name", "attributes", "mrp", "price", "weight_grams", "is_default", "is_active", "price_approved",
        "sort_order",
    )  # fmt: skip
    extra = 0
    min_num = 1


class SpecificationInline(admin.TabularInline):
    model = ProductSpecification
    fields = ("name", "value", "unit", "sort_order")
    extra = 1


class ImageInline(admin.TabularInline):
    model = ProductImage
    fields = (
        "image",
        "alt_text",
        "variant",
        "is_primary",
        "sort_order",
        "source_type",
        "image_type",
        "source_url",
        "licence",
    )
    extra = 0


class AccessoryInline(admin.TabularInline):
    model = ProductRelation
    fk_name = "product"
    fields = ("related", "kind", "note", "sort_order")
    autocomplete_fields = ("related",)
    extra = 0
    verbose_name = "Recommended accessory"


class ProductAdminForm(forms.ModelForm):
    """Checks the rules the model can't see on its own: archived products still own their SKU/slug
    (the default manager hides them, so Django's unique check would miss the clash and fail on the
    database), an archived product must be restored before it is published, and HSN codes are digits."""

    class Meta:
        model = Product
        fields = ("sku", "slug", "hsn_code", "is_published")  # the admin's fieldsets add the rest

    def clean(self):
        data = super().clean()
        for field, value in (("sku", normalize_sku(data.get("sku") or "")), ("slug", data.get("slug"))):
            if field in self.fields and value:
                clash = Product.all_objects.filter(is_deleted=True, **{field: value}).exclude(pk=self.instance.pk)
                if clash.exists():
                    self.add_error(
                        field, f"'{value}' belongs to an archived product. Restore that one or pick another."
                    )
        hsn = data.get("hsn_code") or ""
        if "hsn_code" in self.changed_data and hsn and not (hsn.isdigit() and len(hsn) in (4, 6, 8)):
            self.add_error("hsn_code", "HSN codes are 4, 6 or 8 digits.")
        if data.get("is_published") and self.instance.is_deleted:
            self.add_error("is_published", "This product is archived. Restore it before publishing.")
        return data


class ProductChangelistForm(ProductAdminForm):
    """The list page's quick 'published' tick-box has no variant rows next to it, so check the saved ones."""

    def clean(self):
        data = super().clean()
        if "is_published" in self.changed_data and data.get("is_published"):
            if not self.instance.variants.filter(is_active=True).exists():
                self.add_error("is_published", "Add an active variant with an approved price before publishing.")
        return data


class ArchivedFilter(admin.SimpleListFilter):
    """Archived (soft-deleted) products stay in the database for old orders; the list shows live ones by default."""

    title = "archive status"
    parameter_name = "archived"

    def lookups(self, request, model_admin):
        return [("yes", "Archived"), ("all", "All products")]

    def choices(self, changelist):
        yield {
            "selected": self.value() is None,
            "query_string": changelist.get_query_string(remove=[self.parameter_name]),
            "display": "Live (not archived)",
        }
        for lookup, title in self.lookup_choices:
            yield {
                "selected": self.value() == lookup,
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": title,
            }

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(is_deleted=True)
        if self.value() == "all":
            return queryset
        return queryset.filter(is_deleted=False)


@admin.register(Product)
class ProductAdmin(AdminRoleRequiredMixin, admin.ModelAdmin):
    """Products are never deleted here: orders, reviews and stock history point at them. 'Archive'
    hides a product (unpublished, soft-deleted) and 'Restore' brings it back as a draft. Catalogue
    edits never touch stock; quantities change only through Inventory movements."""

    form = ProductAdminForm
    list_display = (
        "name", "sku", "brand", "category", "subcategory", "gst_rate", "hsn_code", "is_published", "is_active",
        "is_featured", "archived",
    )  # fmt: skip
    list_filter = (ArchivedFilter, "is_published", "is_active", "is_featured", "gst_rate", "category", "brand")
    list_editable = ("is_published", "is_featured")
    list_per_page = 50
    search_fields = ("name", "sku", "variants__sku", "variants__name", "brand__name", "hsn_code")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("brand",)
    readonly_fields = ("rating_avg", "rating_count", "created_at", "updated_at", "deleted_at")
    list_select_related = ("brand", "category", "subcategory")
    inlines = [VariantInline, SpecificationInline, ImageInline, AccessoryInline]
    actions = ["publish", "unpublish", "archive", "restore", "update_search_index"]
    fieldsets = (
        (None, {"fields": ("name", "slug", "sku", "brand", "category", "subcategory", "unit")}),
        ("Content", {"fields": ("short_description", "description", "tags")}),
        ("Product page", {"fields": ("quick_answer", "highlights", "uses", "installation_steps", "faqs")}),
        ("Tax & limits", {"fields": ("gst_rate", "hsn_code", "max_order_quantity", "is_returnable")}),
        ("Visibility", {"fields": ("is_active", "is_published", "is_featured", "launch_date", "deleted_at")}),
        ("Ratings", {"fields": ("rating_avg", "rating_count", "created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        # Archived products too, so they can be found (ArchivedFilter) and restored.
        return Product.all_objects.all()

    def get_search_results(self, request, queryset, search_term):
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        if "autocomplete" in request.path:  # accessory / collection pickers offer live products only
            queryset = queryset.filter(is_deleted=False)
        return queryset, may_have_duplicates

    def get_changelist_form(self, request, **kwargs):
        kwargs.setdefault("form", ProductChangelistForm)
        return super().get_changelist_form(request, **kwargs)

    def has_delete_permission(self, request, obj=None):
        return False  # archive instead; see the class docstring

    @admin.display(boolean=True, description="Archived", ordering="is_deleted")
    def archived(self, obj):
        return obj.is_deleted

    # --- change history (AuditLog, next to Django's own per-object History) ----------------------

    def _audit(self, request, action: str, target, changes: dict | None = None):
        record_audit(action=action, actor=request.user, target=target, changes=changes, request=request)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change or form.changed_data:
            action = "catalog.product.updated" if change else "catalog.product.created"
            self._audit(request, action, obj, _form_changes(form))

    def save_formset(self, request, form, formset, change):
        variant_changes = []
        if formset.model is ProductVariant:
            for f in formset.forms:
                if getattr(f, "cleaned_data", None) and f.has_changed() and not formset._should_delete_form(f):
                    variant_changes.append((f, bool(f.instance.pk), _form_changes(f)))
        super().save_formset(request, form, formset, change)
        for f, existed, changes in variant_changes:
            action = "catalog.variant.updated" if existed else "catalog.variant.created"
            self._audit(request, action, f.instance, {"product": form.instance.sku, **changes})

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        services._ensure_single_default_variant(form.instance)

    # --- actions (each checks the `change` permission on the server) -----------------------------

    @staticmethod
    def _publish_blocker(product: Product) -> str | None:
        if product.is_deleted:
            return "archived (restore it first)"
        if not product.variants.filter(is_active=True).exists():
            return "no active variant with an approved price"
        if product.images.filter(source_type=ProductImage.SourceType.UNVERIFIED).exists():
            return "has pictures marked 'unverified'"
        return None

    @admin.action(description="Publish the selected products", permissions=["change"])
    def publish(self, request, queryset):
        done, skipped = 0, []
        for product in queryset.filter(is_published=False):
            reason = self._publish_blocker(product)
            if reason:
                skipped.append(f"{product.sku}: {reason}")
                continue
            product.is_published = True
            product.save(update_fields=["is_published", "updated_at"])
            self._audit(request, "catalog.product.published", product)
            done += 1
        self.message_user(request, f"{done} product(s) published.")
        if skipped:
            self.message_user(request, "Not published — " + "; ".join(skipped), level=messages.WARNING)

    @admin.action(description="Unpublish the selected products (hide from customers)", permissions=["change"])
    def unpublish(self, request, queryset):
        done = 0
        for product in queryset.filter(is_published=True):
            product.is_published = False
            product.save(update_fields=["is_published", "updated_at"])
            self._audit(request, "catalog.product.unpublished", product)
            done += 1
        self.message_user(request, f"{done} product(s) unpublished.")

    @admin.action(description="Archive the selected products (keeps orders and stock history)", permissions=["change"])
    def archive(self, request, queryset):
        done = 0
        for product in queryset.filter(is_deleted=False):
            product.is_published = product.is_featured = False
            product.is_deleted, product.deleted_at = True, timezone.now()
            product.save(update_fields=["is_published", "is_featured", "is_deleted", "deleted_at", "updated_at"])
            self._audit(request, "catalog.product.archived", product)
            done += 1
        self.message_user(request, f"{done} product(s) archived. Orders, stock and history are kept.")

    @admin.action(description="Restore the selected archived products (as unpublished drafts)", permissions=["change"])
    def restore(self, request, queryset):
        done = 0
        for product in queryset.filter(is_deleted=True):
            product.restore()
            self._audit(request, "catalog.product.restored", product)
            done += 1
        self.message_user(request, f"{done} product(s) restored as unpublished drafts.")

    @admin.action(description="Update semantic search index for the selected products", permissions=["change"])
    def update_search_index(self, request, queryset):
        from .semantic import index

        try:
            result = index.sync_products(list(queryset.filter(is_deleted=False)), force=True)
        except RuntimeError as exc:
            self.message_user(request, f"{exc} Keyword search keeps working.", level="error")
            return
        self.message_user(request, f"Search index updated for {result.embedded} product(s).")


class _ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class PriceTierInline(_ReadOnlyInline):
    """Shown for reference. Bulk prices are edited in the dashboard product form, which checks the
    tier rules (no overlaps, cheaper with quantity, at most the MRP)."""

    model = VariantPriceTier
    fields = ("min_quantity", "unit_price")
    readonly_fields = fields


class VariantOptionFormSet(BaseInlineFormSet):
    """A variant's options: only option types offered for the product's category, and no two active
    variants of one product with the same combination (the storefront picks a variant by its options)."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        variant = self.instance
        allowed = {t.id for t in services.option_types_for(variant.product)}
        combo = set()
        for form in self.forms:
            if not getattr(form, "cleaned_data", None) or self._should_delete_form(form):
                continue
            option_type, value = form.cleaned_data.get("option_type"), form.cleaned_data.get("value")
            if form.has_changed() and option_type and option_type.id not in allowed:
                form.add_error("option_type", "This option isn't used for the product's category.")
            if option_type and value:
                combo.add((option_type.id, value.id))
        if not combo or not variant.is_active:
            return
        siblings = (
            variant.product.variants.filter(is_active=True).exclude(pk=variant.pk).prefetch_related("option_values")
        )
        for sibling in siblings:
            if {(o.option_type_id, o.value_id) for o in sibling.option_values.all()} == combo:
                raise ValidationError(f"Variant {sibling.sku} already has these options; each variant needs its own.")


class VariantOptionInline(admin.TabularInline):
    model = VariantOption
    formset = VariantOptionFormSet
    fields = ("option_type", "value")
    extra = 0


class StockInline(admin.TabularInline):
    """Stock of this option per store, for reference. Quantities change only through the Inventory page,
    which books every change as a stock movement."""

    model = Inventory
    fields = ("store", "available_quantity", "reserved_quantity", "low_stock_threshold", "is_active")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True
    verbose_name_plural = "stock per store (change it on the Inventory page)"

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ProductVariantAdminForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ("price", "mrp", "is_active")  # the admin adds the rest

    def clean(self):
        data = super().clean()
        variant = self.instance
        if not variant.pk:
            return data
        if "is_active" in self.changed_data and not data.get("is_active") and variant.product.is_published:
            if not variant.product.variants.filter(is_active=True).exclude(pk=variant.pk).exists():
                self.add_error("is_active", "This is the published product's only active variant. Unpublish it first.")
        tiers = list(variant.price_tiers.values("min_quantity", "unit_price"))
        if tiers and {"price", "mrp"} & set(self.changed_data):
            candidate = ProductVariant(product=variant.product, mrp=data.get("mrp"), price=data.get("price"))
            try:
                services.validate_price_tiers(candidate, tiers)
            except services.CatalogRuleError as exc:
                self.add_error("price", f"{exc.detail} Change the bulk prices in the dashboard first.")
        return data


@admin.register(ProductVariant)
class ProductVariantAdmin(AdminRoleRequiredMixin, admin.ModelAdmin):
    """Each option (variant) of a product: price, SKU and option values, with its stock per store shown
    read-only. Mainly edited inline on Product; also used for search/autocomplete (e.g. inventory)."""

    form = ProductVariantAdminForm
    list_display = ("sku", "product", "name", "mrp", "price", "price_approved", "is_active")
    list_filter = ("is_active", "price_approved", "product__category")
    list_per_page = 50
    search_fields = ("sku", "name", "product__name", "product__sku")
    list_select_related = ("product",)
    inlines = [PriceTierInline, VariantOptionInline, StockInline]

    def get_readonly_fields(self, request, obj=None):
        # Moving an option to another product would carry its stock and order history along.
        return ("product",) if obj else ()

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)  # bulk delete would skip the per-variant check below
        return actions

    def has_delete_permission(self, request, obj=None):
        if obj is not None and variant_delete_blocker(obj):
            return False
        return super().has_delete_permission(request, obj)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change or form.changed_data:
            action = "catalog.variant.updated" if change else "catalog.variant.created"
            changes = {"product": obj.product.sku, **_form_changes(form)}
            record_audit(action=action, actor=request.user, target=obj, changes=changes, request=request)

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        if formset.model is VariantOption and formset.has_changed():
            _sync_variant_attributes(form.instance)


def _sync_variant_attributes(variant: ProductVariant) -> None:
    """`attributes` is the display copy of the options that older screens read (option name → value)."""
    options = {o.option_type.name: o.value.value for o in variant.option_values.select_related("option_type", "value")}
    names = set(OptionType.objects.values_list("name", flat=True))
    attributes = {k: v for k, v in (variant.attributes or {}).items() if k not in names}
    attributes.update(options)
    if attributes != variant.attributes:
        ProductVariant.objects.filter(pk=variant.pk).update(attributes=attributes)
        variant.attributes = attributes


@admin.register(RecentSearch)
class RecentSearchAdmin(AdminRoleRequiredMixin, admin.ModelAdmin):
    """Customers' search history: viewable/deletable by admins, never edited."""

    list_display = ("query", "user", "searched_at")
    search_fields = ("query", "user__email")
    list_select_related = ("user",)
    readonly_fields = ("user", "query", "normalized", "searched_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class OptionValueInline(admin.TabularInline):
    model = OptionValue
    fields = ("value", "slug", "sort_order")
    prepopulated_fields = {"slug": ("value",)}
    extra = 0


@admin.register(OptionType)
class OptionTypeAdmin(AdminRoleRequiredMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "unit", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("categories",)
    inlines = [OptionValueInline]


class CollectionItemInline(admin.TabularInline):
    model = CollectionItem
    fields = ("product", "sort_order")
    autocomplete_fields = ("product",)
    extra = 0


@admin.register(Collection)
class CollectionAdmin(AdminRoleRequiredMixin, admin.ModelAdmin):
    list_display = ("name", "rule", "is_active", "starts_at", "ends_at", "sort_order")
    list_editable = ("is_active", "sort_order")
    list_filter = ("rule", "is_active")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("categories",)
    inlines = [CollectionItemInline]
