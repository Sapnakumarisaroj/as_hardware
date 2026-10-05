from django.contrib import admin

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
)


class SubCategoryInline(admin.TabularInline):
    model = SubCategory
    fk_name = "parent"
    fields = ("name", "slug", "sort_order", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    extra = 0


@admin.register(TopCategory)
class CategoryAdmin(admin.ModelAdmin):
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
class SubCategoryAdmin(admin.ModelAdmin):
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
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    exclude = ("is_deleted", "deleted_at")


class VariantInline(admin.TabularInline):
    model = ProductVariant
    fields = ("sku", "name", "attributes", "mrp", "price", "weight_grams", "is_default", "is_active", "sort_order")
    extra = 0
    min_num = 1


class SpecificationInline(admin.TabularInline):
    model = ProductSpecification
    fields = ("name", "value", "unit", "sort_order")
    extra = 1


class ImageInline(admin.TabularInline):
    model = ProductImage
    fields = ("image", "alt_text", "variant", "is_primary", "sort_order")
    extra = 0


class AccessoryInline(admin.TabularInline):
    model = ProductRelation
    fk_name = "product"
    fields = ("related", "note", "sort_order")
    autocomplete_fields = ("related",)
    extra = 0
    verbose_name = "Recommended accessory"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "brand", "category", "subcategory", "is_published", "is_active", "is_featured")
    list_filter = ("is_published", "is_active", "is_featured", "category", "brand")
    list_editable = ("is_published", "is_featured")
    search_fields = ("name", "sku", "variants__sku", "brand__name")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("brand",)
    readonly_fields = ("rating_avg", "rating_count", "created_at", "updated_at")
    list_select_related = ("brand", "category", "subcategory")
    inlines = [VariantInline, SpecificationInline, ImageInline, AccessoryInline]
    actions = ["update_search_index"]
    fieldsets = (
        (None, {"fields": ("name", "slug", "sku", "brand", "category", "subcategory", "unit")}),
        ("Content", {"fields": ("short_description", "description", "tags")}),
        ("Product page", {"fields": ("quick_answer", "uses", "installation_steps", "faqs")}),
        ("Tax & limits", {"fields": ("gst_rate", "hsn_code", "max_order_quantity", "is_returnable")}),
        ("Visibility", {"fields": ("is_active", "is_published", "is_featured", "launch_date")}),
        ("Ratings", {"fields": ("rating_avg", "rating_count", "created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return Product.objects.all()

    @admin.action(description="Update semantic search index for the selected products")
    def update_search_index(self, request, queryset):
        from .semantic import index

        try:
            result = index.sync_products(list(queryset), force=True)
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


class VariantOptionInline(_ReadOnlyInline):
    model = VariantOption
    fields = ("option_type", "value")
    readonly_fields = fields


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    """Mainly edited inline on Product; registered for search/autocomplete (e.g. inventory)."""

    list_display = ("sku", "product", "name", "mrp", "price", "is_active")
    list_filter = ("is_active",)
    search_fields = ("sku", "name", "product__name")
    list_select_related = ("product",)
    inlines = [PriceTierInline, VariantOptionInline]


@admin.register(RecentSearch)
class RecentSearchAdmin(admin.ModelAdmin):
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
class OptionTypeAdmin(admin.ModelAdmin):
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
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("name", "rule", "is_active", "starts_at", "ends_at", "sort_order")
    list_editable = ("is_active", "sort_order")
    list_filter = ("rule", "is_active")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("categories",)
    inlines = [CollectionItemInline]
