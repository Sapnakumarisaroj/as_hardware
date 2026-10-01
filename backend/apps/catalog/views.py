from django.db.models import Count, Prefetch, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.core.permissions import IsAdminOrReadOnly, is_admin

from . import selectors, services
from .models import Brand, Category, ProductVariant, RecentSearch
from .search import get_search_backend, normalize_query
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    ProductDetailSerializer,
    ProductFacetsSerializer,
    ProductListSerializer,
    ProductWriteSerializer,
    RecentSearchSerializer,
    SearchSuggestionsSerializer,
)


class CategoryViewSet(viewsets.ModelViewSet):
    """Top-level categories with nested subcategories. Writes: admin only."""

    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = "slug"
    pagination_class = None

    def get_queryset(self):
        children = Category.objects.filter(is_active=True).annotate(
            product_count=Count("subcategory_products", filter=_visible("subcategory_products"), distinct=True)
        )
        qs = Category.objects.select_related("parent").prefetch_related(Prefetch("children", queryset=children))
        if self.action in ("list", "retrieve"):
            qs = qs.annotate(
                product_count=Count("products", filter=_visible("products"), distinct=True)
                + Count("subcategory_products", filter=_visible("subcategory_products"), distinct=True)
            )
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


def _visible(relation: str) -> Q:
    """Products a customer can see, counted through `relation`."""
    return Q(**{f"{relation}__is_active": True, f"{relation}__is_published": True, f"{relation}__is_deleted": False})


_PRODUCT_FILTERS = [
    OpenApiParameter("q", str, description="Search words (name, brand, category, tags, SKU, specifications)"),
    OpenApiParameter("category", str, description="Category or subcategory slug"),
    OpenApiParameter("subcategory", str, description="Subcategory slug"),
    OpenApiParameter("brand", str, description="Comma-separated brand slugs"),
    OpenApiParameter("min_price", str),
    OpenApiParameter("max_price", str),
    OpenApiParameter("rating", str, description="Minimum average rating, e.g. 4"),
    OpenApiParameter("discount", str, description="Minimum discount %, e.g. 25"),
    OpenApiParameter("in_stock", bool),
    OpenApiParameter("availability", str, enum=["in_stock"]),
    OpenApiParameter("fast_delivery", bool, description="Stocked at a store with fast delivery"),
    OpenApiParameter("featured", bool),
    OpenApiParameter("bestseller", bool, description="Products with at least one sale"),
    OpenApiParameter("exclude", str, description="Comma-separated product slugs to leave out"),
    OpenApiParameter("spec_<key>", str, description="Specification filter, e.g. spec_power=650 (comma = OR)"),
    OpenApiParameter("ordering", str, enum=list(selectors.ORDERINGS)),
    OpenApiParameter("page", int),
    OpenApiParameter("page_size", int, description="Max 100"),
    OpenApiParameter("include_unpublished", bool, description="Admin only"),
]


@extend_schema_view(
    list=extend_schema(parameters=_PRODUCT_FILTERS),
    facets=extend_schema(parameters=_PRODUCT_FILTERS, responses=ProductFacetsSerializer),
)
class ProductViewSet(viewsets.ModelViewSet):
    """Customers: published, active products. Admins: all products + create/update/soft-delete."""

    permission_classes = [IsAdminOrReadOnly]
    lookup_field = "slug"

    def get_permissions(self):
        if self.action in ("list", "retrieve", "facets"):
            return [AllowAny()]
        return super().get_permissions()

    def _base_queryset(self):
        include_unpublished = is_admin(self.request.user) and (
            self.action not in ("list", "facets")
            or self.request.query_params.get("include_unpublished") in ("1", "true")
        )
        return selectors.product_queryset(include_unpublished=include_unpublished)

    def get_queryset(self):
        qs = self._base_queryset()
        if self.action == "retrieve":
            qs = qs.prefetch_related(
                Prefetch("variants", queryset=ProductVariant.objects.order_by("sort_order", "id")),
                "specifications",
            )
        return qs

    def list(self, request, *args, **kwargs):
        params = request.query_params
        qs = selectors.filter_products(self._base_queryset(), params, search=False)
        result = selectors.apply_search(qs, params)
        qs = selectors.order_products(result.queryset, params.get("ordering"), searching=bool(result.terms))
        page = self.paginate_queryset(qs)
        data = ProductListSerializer(page, many=True, context={"request": request}).data
        if result.reasons:
            for item in data:
                if reason := result.reasons.get(item["id"]):
                    item["match_reason"] = reason["text"]
                    item["match_type"] = reason["type"]
        response = self.get_paginated_response(data)
        if result.terms:
            response.data["search"] = {"query": params.get("q", "").strip(), "matched": result.matched}
            if result.mode == "hybrid":  # additive: plain keyword results keep the Phase 4 shape
                response.data["search"].update(mode=result.mode, related_terms=list(result.related_terms))
        return response

    @action(detail=False, methods=["get"])
    def facets(self, request):
        """Filter options + counts for the same parameters as the listing."""
        return Response(selectors.product_facets(self._base_queryset(), request.query_params))

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        if self.action == "retrieve":
            return ProductDetailSerializer
        return ProductWriteSerializer

    def retrieve(self, request, *args, **kwargs):
        product = self.get_object()
        return Response(_detail_data(product, request))

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
        return _detail_data(selectors.product_queryset(include_unpublished=True).get(pk=product.pk), request)

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


def _detail_data(product, request) -> dict:
    variant_ids = [v.id for v in product.variants.all()]
    context = {
        "request": request,
        "stock_map": selectors.variant_stock_map(variant_ids),
        "fast_variant_ids": selectors.variant_fast_delivery_ids(variant_ids),
    }
    return ProductDetailSerializer(product, context=context).data


# --- Search helpers -------------------------------------------------------------------------

SUGGEST_PRODUCTS = 6
SUGGEST_OTHERS = 4


class SearchSuggestView(APIView):
    """Type-ahead: a few products, categories and brands for the typed text (public)."""

    permission_classes = [AllowAny]

    @extend_schema(parameters=[OpenApiParameter("q", str, required=True)], responses=SearchSuggestionsSerializer)
    def get(self, request):
        query = normalize_query(request.query_params.get("q"))
        empty = {"query": query, "products": [], "categories": [], "brands": []}
        if len(query) < 2:
            return Response(empty)
        result = get_search_backend().search(selectors.product_queryset(), query)
        products = result.queryset.order_by(*selectors.ORDERINGS["relevance"])[:SUGGEST_PRODUCTS]
        categories = (
            Category.objects.filter(is_active=True, name__icontains=query)
            .select_related("parent")
            .order_by("parent_id", "sort_order", "name")[:SUGGEST_OTHERS]
        )
        brands = Brand.objects.filter(is_active=True, name__icontains=query)[:SUGGEST_OTHERS]
        product_data = ProductListSerializer(products, many=True, context={"request": request}).data
        for item in product_data:
            if (reason := result.reasons.get(item["id"])) and reason["type"] != "keyword":
                item["match_reason"] = reason["text"]
        payload = {
            "query": query,
            "products": product_data,
            "categories": [
                {"name": c.name, "slug": c.slug, "parent_name": c.parent.name if c.parent_id else None}
                for c in categories
            ],
            "brands": [{"name": b.name, "slug": b.slug} for b in brands],
        }
        return Response(SearchSuggestionsSerializer(payload).data)


class RecentSearchView(APIView):
    """The signed-in customer's recent searches (newest first)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=RecentSearchSerializer(many=True))
    def get(self, request):
        return Response(RecentSearchSerializer(RecentSearch.objects.filter(user=request.user), many=True).data)

    @extend_schema(request=RecentSearchSerializer, responses={201: RecentSearchSerializer, 204: None})
    def post(self, request):
        serializer = RecentSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = services.record_recent_search(request.user, serializer.validated_data["query"])
        if entry is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(RecentSearchSerializer(entry).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None})
    def delete(self, request):
        RecentSearch.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
