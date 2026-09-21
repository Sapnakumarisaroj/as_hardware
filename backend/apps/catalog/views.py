from django.db.models import Prefetch
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core.audit import record_audit
from apps.core.permissions import IsAdminOrReadOnly, is_admin

from . import selectors, services
from .models import Brand, Category, ProductVariant
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    ProductWriteSerializer,
)


class CategoryViewSet(viewsets.ModelViewSet):
    """Top-level categories with nested subcategories. Writes: admin only."""

    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = "slug"
    pagination_class = None

    def get_queryset(self):
        qs = Category.objects.prefetch_related("children")
        if self.action == "list":
            qs = qs.filter(parent__isnull=True)
        if not is_admin(self.request.user):
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save()
        record_audit(action="category.create", actor=self.request.user, target=obj, request=self.request)

    def perform_update(self, serializer):
        obj = serializer.save()
        record_audit(action="category.update", actor=self.request.user, target=obj, request=self.request)

    def perform_destroy(self, instance):
        services.delete_category(instance)
        record_audit(action="category.delete", actor=self.request.user, target=instance, request=self.request)


class BrandViewSet(viewsets.ModelViewSet):
    serializer_class = BrandSerializer
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = "slug"
    pagination_class = None

    def get_queryset(self):
        qs = Brand.objects.all()
        return qs if is_admin(self.request.user) else qs.filter(is_active=True)

    def perform_create(self, serializer):
        obj = serializer.save()
        record_audit(action="brand.create", actor=self.request.user, target=obj, request=self.request)

    def perform_update(self, serializer):
        obj = serializer.save()
        record_audit(action="brand.update", actor=self.request.user, target=obj, request=self.request)

    def perform_destroy(self, instance):
        instance.delete()  # soft delete; products keep their brand reference
        record_audit(action="brand.delete", actor=self.request.user, target=instance, request=self.request)


_PRODUCT_FILTERS = [
    OpenApiParameter("category", str, description="Category or subcategory slug"),
    OpenApiParameter("subcategory", str),
    OpenApiParameter("brand", str, description="Comma-separated brand slugs"),
    OpenApiParameter("min_price", float),
    OpenApiParameter("max_price", float),
    OpenApiParameter("in_stock", bool),
    OpenApiParameter("featured", bool),
    OpenApiParameter("q", str, description="Keyword (name, SKU, brand)"),
    OpenApiParameter("ordering", str, enum=list(selectors.ORDERINGS)),
    OpenApiParameter("include_unpublished", bool, description="Admin only"),
]


@extend_schema_view(list=extend_schema(parameters=_PRODUCT_FILTERS))
class ProductViewSet(viewsets.ModelViewSet):
    """Customers: published, active products. Admins: all products + create/update/soft-delete."""

    permission_classes = [IsAdminOrReadOnly]
    lookup_field = "slug"

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return super().get_permissions()

    def get_queryset(self):
        include_unpublished = is_admin(self.request.user) and (
            self.action not in ("list",) or self.request.query_params.get("include_unpublished") in ("1", "true")
        )
        qs = selectors.product_queryset(include_unpublished=include_unpublished)
        if self.action == "retrieve":
            qs = qs.prefetch_related(
                Prefetch("variants", queryset=ProductVariant.objects.order_by("sort_order", "id")),
                "specifications",
            )
        if self.action == "list":
            qs = selectors.filter_products(qs, self.request.query_params)
            qs = selectors.order_products(qs, self.request.query_params.get("ordering"))
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        if self.action == "retrieve":
            return ProductDetailSerializer
        return ProductWriteSerializer

    def retrieve(self, request, *args, **kwargs):
        product = self.get_object()
        stock_map = selectors.variant_stock_map(v.id for v in product.variants.all())
        data = ProductDetailSerializer(product, context={"request": request, "stock_map": stock_map}).data
        return Response(data)

    def _save(self, request, instance=None, partial=False):
        serializer = ProductWriteSerializer(instance, data=request.data, partial=partial, context={"request": request})
        serializer.is_valid(raise_exception=True)
        product = services.save_product(instance=instance, data=dict(serializer.validated_data), actor=request.user)
        record_audit(
            action="product.update" if instance else "product.create",
            actor=request.user,
            target=product,
            request=request,
        )
        product = selectors.product_queryset(include_unpublished=True).get(pk=product.pk)
        stock_map = selectors.variant_stock_map(product.variants.values_list("id", flat=True))
        return ProductDetailSerializer(product, context={"request": request, "stock_map": stock_map}).data

    @extend_schema(request=ProductWriteSerializer, responses={201: ProductDetailSerializer})
    def create(self, request, *args, **kwargs):
        return Response(self._save(request), status=status.HTTP_201_CREATED)

    @extend_schema(request=ProductWriteSerializer, responses=ProductDetailSerializer)
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        return Response(self._save(request, instance=self.get_object(), partial=partial))

    def perform_destroy(self, instance):
        instance.delete()  # soft delete: past orders keep their snapshots
        record_audit(action="product.delete", actor=self.request.user, target=instance, request=self.request)
