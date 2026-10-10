"""Catalogue management for the dashboard: products (with variants, specifications and images),
categories, subcategories and brands.

Store managers may read (they need products to manage stock); only administrators may change
anything. Products are written through `catalog.services.save_product`, the same service the
public admin-write API uses, so SKU uniqueness, price ≤ MRP and the single default variant are
enforced in one place. Deleting is a soft delete: past orders keep their snapshots.
"""

from django.db import transaction
from django.db.models import Count, Max, Min, Prefetch, Q, Sum
from django.db.models.deletion import ProtectedError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import services
from apps.catalog.models import Brand, Category, Product, ProductImage, ProductVariant
from apps.catalog.serializers import (
    BrandSerializer,
    ProductImageSerializer,
    ProductSpecificationSerializer,
    ProductWriteSerializer,
)
from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, NotFoundError, ServiceError
from apps.core.permissions import IsAdminOrStaffReadOnly, IsAdminRole, is_admin, managed_store_ids
from apps.inventory.models import Inventory

MAX_IMAGES_PER_PRODUCT = 12


def _ref(obj) -> dict | None:
    return {"id": obj.pk, "name": obj.name, "slug": obj.slug} if obj else None


def _image_url(image, request) -> str:
    url = image.image.url
    return request.build_absolute_uri(url) if request else url


# --- Products ------------------------------------------------------------------------------------


class AdminVariantSerializer(serializers.ModelSerializer):
    stock_available = serializers.SerializerMethodField()
    stock_reserved = serializers.SerializerMethodField()
    price_tiers = serializers.SerializerMethodField()
    options = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "sku",
            "name",
            "attributes",
            "mrp",
            "price",
            "cost_price",
            "weight_grams",
            "length_mm",
            "width_mm",
            "height_mm",
            "is_default",
            "is_active",
            "sort_order",
            "stock_available",
            "stock_reserved",
            "price_tiers",
            "options",
        ]

    def get_price_tiers(self, obj) -> list[dict]:
        return [{"min_quantity": t.min_quantity, "unit_price": str(t.unit_price)} for t in obj.price_tiers.all()]

    def get_options(self, obj) -> list[dict]:
        return [
            {
                "option_type": o.option_type_id,
                "option_name": o.option_type.name,
                "value_id": o.value_id,
                "value": o.value.value,
            }
            for o in obj.option_values.all()
        ]

    def get_stock_available(self, obj) -> int:
        return self.context.get("stock", {}).get(obj.pk, (0, 0))[0]

    def get_stock_reserved(self, obj) -> int:
        return self.context.get("stock", {}).get(obj.pk, (0, 0))[1]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if not is_admin(getattr(request, "user", None)):
            data.pop("cost_price", None)  # purchase cost: administrators only (profit reports)
        return data


class AdminProductListSerializer(serializers.ModelSerializer):
    brand = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    subcategory = serializers.SerializerMethodField()
    variant_count = serializers.IntegerField(read_only=True)
    price_from = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, allow_null=True)
    price_to = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, allow_null=True)
    stock_available = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "slug",
            "sku",
            "brand",
            "category",
            "subcategory",
            "unit",
            "is_active",
            "is_published",
            "is_featured",
            "is_returnable",
            "is_deleted",
            "is_demo",
            "state",
            "variant_count",
            "price_from",
            "price_to",
            "stock_available",
            "image",
            "updated_at",
        ]

    def get_brand(self, obj) -> dict | None:
        return _ref(obj.brand)

    def get_category(self, obj) -> dict | None:
        return _ref(obj.category)

    def get_subcategory(self, obj) -> dict | None:
        return _ref(obj.subcategory)

    def get_stock_available(self, obj) -> int:
        return getattr(obj, "stock_available", None) or 0

    def get_image(self, obj) -> str | None:
        images = list(obj.images.all())
        return _image_url(images[0], self.context.get("request")) if images else None

    def get_state(self, obj) -> str:
        """deleted | inactive | draft (not published) | live"""
        if obj.is_deleted:
            return "deleted"
        if not obj.is_active:
            return "inactive"
        return "live" if obj.is_published else "draft"


class AdminProductDetailSerializer(AdminProductListSerializer):
    variants = serializers.SerializerMethodField()
    specifications = ProductSpecificationSerializer(many=True, read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    option_types = serializers.SerializerMethodField()
    accessories = serializers.SerializerMethodField()

    class Meta(AdminProductListSerializer.Meta):
        fields = AdminProductListSerializer.Meta.fields + [
            "short_description",
            "description",
            "tags",
            "gst_rate",
            "hsn_code",
            "max_order_quantity",
            "rating_avg",
            "rating_count",
            "launch_date",
            "variants",
            "specifications",
            "images",
            "option_types",
            "quick_answer",
            "uses",
            "installation_steps",
            "faqs",
            "accessories",
        ]

    def get_accessories(self, obj) -> list[dict]:
        """Linked products in order: [{id, name, slug, note, kind}] (kind since Phase 21)."""
        return [
            {"id": r.related_id, "name": r.related.name, "slug": r.related.slug, "note": r.note, "kind": r.kind}
            for r in obj.relations.select_related("related").order_by("sort_order", "id")
        ]

    def get_option_types(self, obj) -> list[dict]:
        """Options that can be set on this product's variants (its category's, or shop-wide ones)."""
        return [
            {
                "id": t.pk,
                "name": t.name,
                "unit": t.unit,
                "values": [{"id": v.pk, "value": v.value} for v in t.values.all()],
            }
            for t in services.option_types_for(obj)
        ]

    def get_variants(self, obj) -> list[dict]:
        variants = list(obj.variants.all())
        rows = (
            Inventory.objects.filter(variant__in=variants, is_active=True)
            .values("variant_id")
            .annotate(available=Sum("available_quantity"), reserved=Sum("reserved_quantity"))
        )
        stock = {r["variant_id"]: (r["available"] or 0, r["reserved"] or 0) for r in rows}
        return AdminVariantSerializer(variants, many=True, context={**self.context, "stock": stock}).data


class _ImageSourceFields(serializers.Serializer):
    """Where a picture came from (all optional; see ProductImage)."""

    source_type = serializers.ChoiceField(choices=ProductImage.SourceType.choices, required=False, allow_blank=True)
    image_type = serializers.ChoiceField(choices=ProductImage.ImageType.choices, required=False)
    source_url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    licence = serializers.CharField(max_length=300, required=False, allow_blank=True)


class ImageUploadSerializer(_ImageSourceFields):
    image = serializers.ImageField()
    alt_text = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    variant = serializers.IntegerField(required=False, allow_null=True)
    is_primary = serializers.BooleanField(required=False, default=False)


class ImageUpdateSerializer(_ImageSourceFields):
    alt_text = serializers.CharField(max_length=200, required=False, allow_blank=True)
    sort_order = serializers.IntegerField(min_value=0, required=False)
    is_primary = serializers.BooleanField(required=False)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Name, product SKU or variant SKU"),
            OpenApiParameter("category", int, description="Category or subcategory id"),
            OpenApiParameter("brand", int),
            OpenApiParameter("state", str, enum=["live", "draft", "inactive", "deleted", "all"]),
            OpenApiParameter("featured", bool),
            OpenApiParameter("demo", bool, description="Only demo (true) or only real (false) products"),
            OpenApiParameter("stock", str, enum=["out", "in"]),
            OpenApiParameter("ordering", str, enum=["name", "-name", "-updated_at", "updated_at"]),
        ]
    )
)
class AdminProductViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrStaffReadOnly]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    ORDERINGS = ("name", "-name", "-updated_at", "updated_at")

    def get_serializer_class(self):
        if self.action == "list":
            return AdminProductListSerializer
        if self.action in ("create", "partial_update"):
            return ProductWriteSerializer
        return AdminProductDetailSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Product.objects.none()
        qs = (
            Product.all_objects.select_related("brand", "category", "subcategory")
            .prefetch_related(Prefetch("images", queryset=ProductImage.objects.order_by("-is_primary", "sort_order")))
            .annotate(
                variant_count=Count("variants", filter=Q(variants__is_active=True), distinct=True),
                price_from=Min("variants__price", filter=Q(variants__is_active=True)),
                price_to=Max("variants__price", filter=Q(variants__is_active=True)),
            )
        )
        if self.action != "list":
            return qs.prefetch_related(
                "variants__price_tiers", "variants__option_values__option_type", "variants__option_values__value",
                "specifications",
            )  # fmt: skip
        params = self.request.query_params
        stock = Inventory.objects.filter(is_active=True, store__is_deleted=False)
        allowed = managed_store_ids(self.request.user)  # store managers: their stores' stock only
        if allowed is not None:
            stock = stock.filter(store_id__in=allowed)
        stock = stock.values("variant__product_id").annotate(total=Sum("available_quantity"))
        self._stock = {row["variant__product_id"]: row["total"] or 0 for row in stock}
        state = params.get("state") or "current"
        if state == "deleted":
            qs = qs.filter(is_deleted=True)
        elif state != "all":
            qs = qs.filter(is_deleted=False)
            if state == "live":
                qs = qs.filter(is_active=True, is_published=True)
            elif state == "draft":
                qs = qs.filter(is_active=True, is_published=False)
            elif state == "inactive":
                qs = qs.filter(is_active=False)
        if term := (params.get("q") or "").strip():
            qs = qs.filter(
                Q(name__icontains=term) | Q(sku__icontains=term) | Q(variants__sku__icontains=term)
            ).distinct()
        if (category := params.get("category")) and category.isdigit():
            qs = qs.filter(Q(category_id=category) | Q(subcategory_id=category))
        if (brand := params.get("brand")) and brand.isdigit():
            qs = qs.filter(brand_id=brand)
        if params.get("featured") in ("1", "true"):
            qs = qs.filter(is_featured=True)
        if (demo := params.get("demo")) in ("true", "false"):
            qs = qs.filter(is_demo=demo == "true")
        if params.get("stock") in ("out", "in"):
            stocked = [pk for pk, total in self._stock.items() if total > 0]
            qs = qs.filter(pk__in=stocked) if params["stock"] == "in" else qs.exclude(pk__in=stocked)
        ordering = params.get("ordering")
        return qs.order_by(ordering if ordering in self.ORDERINGS else "name", "id")

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        for product in page:
            product.stock_available = self._stock.get(product.pk, 0)
        return self.get_paginated_response(
            AdminProductListSerializer(page, many=True, context={"request": request}).data
        )

    def _detail(self, product, status_code=status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=product.pk)
        return Response(AdminProductDetailSerializer(fresh, context={"request": self.request}).data, status=status_code)

    def retrieve(self, request, *args, **kwargs):
        return self._detail(self.get_object())

    @transaction.atomic  # a refused variant must not leave a half-saved product behind
    def _save(self, request, instance=None):
        serializer = ProductWriteSerializer(
            instance, data=request.data, partial=instance is not None, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        changed = sorted(serializer.validated_data)
        before = services.relation_rows(instance) if instance and "accessories" in serializer.validated_data else None
        product = services.save_product(instance=instance, data=dict(serializer.validated_data), actor=request.user)
        changes = {"fields": changed}
        if "accessories" in serializer.validated_data:
            after = services.relation_rows(product)
            if after != before:  # Phase 21: product links drive compatibility, so each change is recorded in full
                changes["relations"] = {"before": before or [], "after": after}
        record_audit(
            action="product.update" if instance else "product.create",
            actor=request.user,
            target=product,
            request=request,
            changes=changes,
        )
        return product

    @extend_schema(request=ProductWriteSerializer, responses={201: AdminProductDetailSerializer})
    def create(self, request, *args, **kwargs):
        return self._detail(self._save(request), status.HTTP_201_CREATED)

    @extend_schema(request=ProductWriteSerializer, responses=AdminProductDetailSerializer)
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_deleted:
            raise ConflictError("Restore this product before changing it.", code="product_deleted")
        return self._detail(self._save(request, instance))

    def destroy(self, request, *args, **kwargs):
        """Soft delete: hidden from customers and lists; past orders keep their snapshots."""
        product = self.get_object()
        if not product.is_deleted:
            product.delete()
            record_audit(action="product.delete", actor=request.user, target=product, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=AdminProductDetailSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """Bring a deleted product back, unpublished, so it can be checked before it is sold again."""
        product = self.get_object()
        if product.is_deleted:
            Product.all_objects.filter(pk=product.pk).update(is_deleted=False, deleted_at=None, is_published=False)
            record_audit(action="product.restore", actor=request.user, target=product, request=request)
        return self._detail(product)

    # --- Images ----------------------------------------------------------------------------------

    @extend_schema(
        request={"multipart/form-data": ImageUploadSerializer}, responses={201: AdminProductDetailSerializer}
    )
    @action(detail=True, methods=["post"], url_path="images")
    @transaction.atomic
    def add_image(self, request, pk=None):
        product = self.get_object()
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if product.images.count() >= MAX_IMAGES_PER_PRODUCT:
            raise ServiceError(f"A product can have at most {MAX_IMAGES_PER_PRODUCT} pictures.", code="too_many_images")
        variant = None
        if data.get("variant"):
            variant = product.variants.filter(pk=data["variant"]).first()
            if variant is None:
                raise ServiceError("That variant does not belong to this product.", code="invalid_variant")
        first = not product.images.exists()
        image = ProductImage(
            product=product,
            variant=variant,
            image=data["image"],
            alt_text=data["alt_text"],
            is_primary=data["is_primary"] or first,
            sort_order=product.images.count(),
            **{field: data[field] for field in ("source_type", "image_type", "source_url", "licence") if field in data},
        )
        image.full_clean(exclude=["product", "variant"])  # extension and size validators
        image.save()
        if image.is_primary:
            product.images.exclude(pk=image.pk).update(is_primary=False)
        record_audit(action="product.image_add", actor=request.user, target=product, request=request)
        return self._detail(product, status.HTTP_201_CREATED)

    @extend_schema(methods=["patch"], request=ImageUpdateSerializer, responses=AdminProductDetailSerializer)
    @extend_schema(methods=["delete"], responses=AdminProductDetailSerializer)
    @action(detail=True, methods=["patch", "delete"], url_path=r"images/(?P<image_id>\d+)")
    @transaction.atomic
    def image(self, request, pk=None, image_id=None):
        product = self.get_object()
        image = product.images.filter(pk=image_id).first()
        if image is None:
            raise NotFoundError("Picture not found.")
        if request.method == "DELETE":
            was_primary, stored = image.is_primary, image.image
            image.delete()
            transaction.on_commit(lambda: stored.storage.delete(stored.name))
            if was_primary and (replacement := product.images.order_by("sort_order", "id").first()):
                ProductImage.objects.filter(pk=replacement.pk).update(is_primary=True)
            record_audit(action="product.image_delete", actor=request.user, target=product, request=request)
            return self._detail(product)
        serializer = ImageUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(image, field, value)
        image.save()
        if serializer.validated_data.get("is_primary"):
            product.images.exclude(pk=image.pk).update(is_primary=False)
        return self._detail(product)


class VariantSearchView(viewsets.ViewSet):
    """Find a variant by product name or SKU, e.g. to add a stock record (staff)."""

    permission_classes = [IsAdminOrStaffReadOnly]

    @extend_schema(parameters=[OpenApiParameter("q", str, required=True)], responses={200: None})
    def list(self, request):
        term = (request.query_params.get("q") or "").strip()
        if len(term) < 2:
            return Response([])
        variants = (
            ProductVariant.objects.filter(is_active=True, product__is_deleted=False)
            .filter(Q(sku__icontains=term) | Q(product__name__icontains=term) | Q(name__icontains=term))
            .select_related("product")
            .order_by("product__name", "sort_order")[:20]
        )
        return Response(
            [
                {
                    "id": v.pk,
                    "sku": v.sku,
                    "product_name": v.product.name,
                    "variant_name": v.name,
                    "price": str(v.price),
                }
                for v in variants
            ]
        )


# --- Spreadsheet import / export (apps/catalog/importer.py, docs/CATALOG_IMPORT.md) ---------------


class CatalogImportSerializer(serializers.Serializer):
    file = serializers.FileField(help_text=".csv (UTF-8) or .xlsx, at most 5 MB, one row per variant")
    dry_run = serializers.BooleanField(required=False, default=True, help_text="Check only (default); false saves")
    sheet = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    allow_demo = serializers.BooleanField(required=False, default=False, help_text="Also update demo rows")


def _download(content: bytes, fmt: str, name: str):
    from django.http import HttpResponse

    from apps.catalog.importer_export import CONTENT_TYPES

    response = HttpResponse(content, content_type=CONTENT_TYPES[fmt])
    response["Content-Disposition"] = f'attachment; filename="{name}.{fmt}"'
    return response


class _FileFormatMixin:
    """`?format=csv|xlsx` names the file type here, not a DRF renderer."""

    def perform_content_negotiation(self, request, force=False):
        return super().perform_content_negotiation(request, force=True)

    def _format(self, request) -> str:
        fmt = (request.query_params.get("format") or "xlsx").lower()
        if fmt not in ("csv", "xlsx"):
            raise ServiceError("Choose format=csv or format=xlsx.", code="invalid_format")
        return fmt


class CatalogImportView(APIView):
    """Upload a spreadsheet: every row is checked first; a dry run (the default) saves nothing and
    returns what would happen. A real import is all or nothing. Administrators only."""

    permission_classes = [IsAdminRole]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request={"multipart/form-data": CatalogImportSerializer}, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        from apps.catalog.importer import MAX_FILE_BYTES, ImportFileError, import_file

        serializer = CatalogImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        upload = data["file"]
        if upload.size > MAX_FILE_BYTES:
            raise ImportFileError(
                f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB. Split it into smaller files.",
                code="file_too_large",
            )
        report = import_file(
            upload.read(),
            upload.name,
            sheet=data["sheet"] or None,
            dry_run=data["dry_run"],
            allow_demo=data["allow_demo"],
            actor=request.user,
        )
        return Response(report.as_dict())


class CatalogExportView(_FileFormatMixin, APIView):
    """The catalogue in the import columns (re-importable). Includes purchase costs: administrators only."""

    permission_classes = [IsAdminRole]

    @extend_schema(
        parameters=[
            OpenApiParameter("format", str, enum=["xlsx", "csv"]),
            OpenApiParameter("include_demo", bool),
            OpenApiParameter("include_deleted", bool),
        ],
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY},
    )
    def get(self, request):
        from apps.catalog.importer_export import export_rows, write_csv, write_xlsx

        fmt = self._format(request)
        params = request.query_params
        rows = export_rows(
            include_demo=params.get("include_demo") in ("1", "true"),
            include_deleted=params.get("include_deleted") in ("1", "true"),
        )
        record_audit(action="catalog.export", actor=request.user, request=request, changes={"rows": len(rows)})
        return _download(write_xlsx(rows) if fmt == "xlsx" else write_csv(rows), fmt, "catalogue")


class CatalogTemplateView(_FileFormatMixin, APIView):
    """A blank import file (the Excel one has a 'Columns' sheet explaining every column)."""

    permission_classes = [IsAdminRole]

    @extend_schema(
        parameters=[OpenApiParameter("format", str, enum=["xlsx", "csv"])],
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY},
    )
    def get(self, request):
        from apps.catalog.importer_export import template

        fmt = self._format(request)
        return _download(template(fmt), fmt, "catalogue-template")


# --- Categories and brands -----------------------------------------------------------------------


class AdminCategorySerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(source="parent.name", read_only=True, default=None)
    product_count = serializers.IntegerField(read_only=True, default=0)
    children = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "slug",
            "parent",
            "parent_name",
            "description",
            "image",
            "sort_order",
            "is_active",
            "product_count",
            "children",
            "level",
        ]
        extra_kwargs = {"slug": {"required": False}, "image": {"required": False}}

    def get_level(self, obj) -> int:
        levels = self.context.get("levels")
        return levels.get(obj.pk, 1) if levels else obj.level

    def get_children(self, obj) -> list[dict]:
        """Nested children down to the third level (department › category › subcategory)."""
        if not self.context.get("with_children"):
            return []
        tree = self.context.get("tree", {})
        children = tree.get(obj.pk)
        if children is None:
            children = [c for c in obj.children.all() if not c.is_deleted]
        return AdminCategorySerializer(children, many=True, context=self.context).data

    def validate(self, attrs):
        from django.core.exceptions import ValidationError as DjangoValidationError

        instance = self.instance or Category()
        previous = {key: getattr(instance, key, None) for key in attrs}
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        finally:
            if self.instance is not None:
                for key, value in previous.items():
                    setattr(instance, key, value)
        return attrs


def _product_counts() -> dict[int, int]:
    """Products that are not deleted, counted for their deepest category and every level above it."""
    from apps.catalog.tree import ancestor_ids, parent_map

    parents = parent_map()
    counts: dict[int, int] = {}
    for category_id, subcategory_id in Product.objects.values_list("category_id", "subcategory_id"):
        for node in ancestor_ids(subcategory_id or category_id, parents):
            counts[node] = counts.get(node, 0) + 1
    return counts


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("flat", bool, description="Every category and subcategory in one list"),
            OpenApiParameter("q", str),
        ]
    )
)
class AdminCategoryViewSet(viewsets.ModelViewSet):
    """Categories with their subcategories, including inactive ones."""

    permission_classes = [IsAdminOrStaffReadOnly]
    serializer_class = AdminCategorySerializer
    pagination_class = None
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Category.objects.select_related("parent").prefetch_related("children").order_by("sort_order", "name")

    def get_serializer_context(self):
        flat = self.request.query_params.get("flat") in ("1", "true")
        return {**super().get_serializer_context(), "with_children": self.action in ("list", "retrieve") and not flat}

    def list(self, request, *args, **kwargs):
        from apps.catalog.tree import ancestor_ids, parent_map

        flat = request.query_params.get("flat") in ("1", "true")
        counts = _product_counts()
        everything = list(self.get_queryset())
        parents = parent_map()
        levels = {c.pk: len(ancestor_ids(c.pk, parents)) for c in everything}
        tree: dict[int, list] = {}
        for category in everything:
            category.product_count = counts.get(category.pk, 0)
            tree.setdefault(category.parent_id, []).append(category)
        if term := (request.query_params.get("q") or "").strip():
            hits = {c.pk for c in everything if term.lower() in c.name.lower()}
            # Keep a match's whole branch: its ancestors (to reach it) and its own children.
            keep = {a for pk in hits for a in ancestor_ids(pk, parents)} | {
                c.pk for c in everything if c.parent_id in hits
            }
            everything = [c for c in everything if c.pk in keep]
            tree = {}
            for category in everything:
                tree.setdefault(category.parent_id, []).append(category)
        categories = everything if flat else tree.get(None, [])
        context = {**self.get_serializer_context(), "tree": tree, "levels": levels}
        return Response(self.get_serializer_class()(categories, many=True, context=context).data)

    def perform_create(self, serializer):
        record_audit(action="category.create", actor=self.request.user, target=serializer.save(), request=self.request)

    def perform_update(self, serializer):
        category = serializer.save()
        if not category.is_active and not category.parent_id:
            pass  # subcategories keep their own flag; customers can't reach them through a hidden parent
        record_audit(
            action="category.update",
            actor=self.request.user,
            target=category,
            request=self.request,
            changes={"fields": sorted(serializer.validated_data)},
        )

    def perform_destroy(self, instance):
        services.delete_category(instance)  # refuses while it has subcategories or products
        record_audit(action="category.delete", actor=self.request.user, target=instance, request=self.request)


class AdminBrandSerializer(BrandSerializer):
    product_count = serializers.IntegerField(read_only=True, default=0)

    class Meta(BrandSerializer.Meta):
        fields = BrandSerializer.Meta.fields + ["product_count"]
        extra_kwargs = {"slug": {"required": False}, "logo": {"required": False}}


@extend_schema_view(list=extend_schema(parameters=[OpenApiParameter("q", str), OpenApiParameter("is_active", bool)]))
class AdminBrandViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrStaffReadOnly]
    serializer_class = AdminBrandSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Brand.objects.annotate(
            product_count=Count("products", filter=Q(products__is_deleted=False), distinct=True)
        ).order_by("name")
        params = self.request.query_params
        if term := (params.get("q") or "").strip():
            qs = qs.filter(name__icontains=term)
        if (active := params.get("is_active")) in ("true", "false"):
            qs = qs.filter(is_active=active == "true")
        return qs

    def perform_create(self, serializer):
        record_audit(action="brand.create", actor=self.request.user, target=serializer.save(), request=self.request)

    def perform_update(self, serializer):
        record_audit(action="brand.update", actor=self.request.user, target=serializer.save(), request=self.request)

    def perform_destroy(self, instance):
        if Product.objects.filter(brand=instance).exists():
            raise ConflictError(
                "This brand still has products. Deactivate it instead, or move its products to another brand.",
                code="brand_has_products",
            )
        try:
            instance.delete()  # soft delete
        except ProtectedError as exc:  # pragma: no cover - soft delete doesn't cascade
            raise ConflictError("This brand is still in use.", code="brand_in_use") from exc
        record_audit(action="brand.delete", actor=self.request.user, target=instance, request=self.request)
