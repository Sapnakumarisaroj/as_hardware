from collections import defaultdict

from django.conf import settings
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
from .collections import collection_products, live_collections
from .models import Brand, Category, OptionType, Product, ProductVariant, RecentSearch, VariantOption
from .search import get_search_backend, normalize_query
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    CollectionSerializer,
    OptionTypeSerializer,
    ProductDetailSerializer,
    ProductFacetsSerializer,
    ProductListSerializer,
    ProductWriteSerializer,
    RecentSearchSerializer,
    SearchSuggestionsSerializer,
)


def category_product_counts() -> dict[int, int]:
    """Visible products under each category (its own and everything below it)."""
    from .tree import ancestor_ids, parent_map

    parents = parent_map()
    counts: dict[int, int] = defaultdict(int)
    rows = Product.objects.filter(is_active=True, is_published=True).values_list("category_id", "subcategory_id")
    for category_id, subcategory_id in rows:
        for node in set(ancestor_ids(subcategory_id or category_id, parents)) | set(ancestor_ids(category_id, parents)):
            counts[node] += 1
    return counts


def category_cover_images() -> dict[int, str]:
    """Category id → the primary photo of one of its published products (featured first), for tiles and
    menus when the category has no picture of its own. Parents get one of their children's photos."""
    from .models import ProductImage

    covers: dict[int, str] = {}
    rows = (
        ProductImage.objects.filter(product__is_active=True, product__is_published=True, product__is_deleted=False)
        .order_by("-product__is_featured", "product__name", "-is_primary", "sort_order", "id")
        .values_list("product__category_id", "product__subcategory_id", "image")
    )
    for category_id, subcategory_id, path in rows.iterator():
        url = settings.MEDIA_URL + path
        for pk in (subcategory_id, category_id):
            if pk and pk not in covers:
                covers[pk] = url
    parents = dict(Category.objects.filter(parent__isnull=False).values_list("pk", "parent_id"))
    for child, parent in parents.items():
        if child in covers and parent not in covers:
            covers[parent] = covers[child]
    return covers


class CategoryViewSet(viewsets.ModelViewSet):
    """Top-level categories (departments) with their categories and subcategories (up to three
    levels, Phase 15). Writes: admin only."""

    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = "slug"
    pagination_class = None

    def get_queryset(self):
        children = Category.objects.filter(is_active=True)
        qs = Category.objects.select_related("parent").prefetch_related(Prefetch("children", queryset=children))
        if self.action == "list":
            qs = qs.filter(parent__isnull=True)
        if not is_admin(self.request.user):
            qs = qs.filter(is_active=True)
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action in ("list", "retrieve"):
            grandchildren = defaultdict(list)
            for child in Category.objects.filter(is_active=True, parent__parent__isnull=False).order_by(
                "sort_order", "name"
            ):
                grandchildren[child.parent_id].append(child)
            context.update(
                grandchildren=grandchildren, category_counts=self._counts(), cover_images=category_cover_images()
            )
        return context

    def _counts(self) -> dict[int, int]:
        if not hasattr(self, "_category_counts"):
            self._category_counts = category_product_counts()
        return self._category_counts

    def _with_counts(self, categories):
        counts = self._counts()
        for category in categories:
            category.product_count = counts.get(category.pk, 0)
            for child in category.children.all():
                child.product_count = counts.get(child.pk, 0)
        return categories

    def list(self, request, *args, **kwargs):
        categories = self._with_counts(list(self.get_queryset()))
        return Response(self.get_serializer(categories, many=True).data)

    def retrieve(self, request, *args, **kwargs):
        category = self._with_counts([self.get_object()])[0]
        return Response(self.get_serializer(category).data)

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
        visible = Q(products__is_active=True, products__is_published=True, products__is_deleted=False)
        qs = Brand.objects.annotate(visible_products=Count("products", filter=visible)).order_by("name")
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
    OpenApiParameter("bulk_pricing", bool, description="Products with bulk (quantity) prices"),
    OpenApiParameter("opt_<option>", str, description="Option filter, e.g. opt_grade=53-grade (comma = OR)"),
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
        if self.action in ("retrieve", "quote"):
            qs = qs.prefetch_related(
                Prefetch("variants", queryset=ProductVariant.objects.order_by("sort_order", "id")),
                "variants__price_tiers",
                Prefetch(
                    "variants__option_values",
                    queryset=VariantOption.objects.select_related("option_type", "value"),
                ),
                "specifications",
                "relations",
            )
        return qs

    def _pin(self):
        from apps.delivery.pin import pin_context

        return pin_context(self.request.query_params.get("postal_code"))

    def _interpreted(self, base, params):
        """Phase 16: filters the search words name ("53 grade cement" → Cement + Grade 53), applied only
        when they still leave results. `interpret=0` turns this off (the shopper removed them)."""
        from .interpret import interpret

        query = normalize_query(params.get("q"))
        if not query or params.get("interpret") in ("0", "false"):
            return params, None
        found = interpret(query, params)
        if not found:
            return params, None
        merged = params.copy()
        for name, value in found.filters.items():
            merged[name] = value
        if not selectors.filter_products(base, merged).exists():
            return params, None
        return merged, found

    def list(self, request, *args, **kwargs):
        pin = self._pin()
        qs = selectors.annotate_pin(self._base_queryset(), pin)
        params, interpreted = self._interpreted(qs, request.query_params)
        qs = selectors.filter_products(qs, params, search=False)
        result = selectors.apply_search(qs, params)
        qs = selectors.order_products(result.queryset, params.get("ordering"), searching=bool(result.terms))
        page = self.paginate_queryset(qs)
        data = ProductListSerializer(page, many=True, context={"request": request, "pin": pin}).data
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
            if interpreted:
                response.data["search"]["interpreted"] = interpreted.labels
        if pin is not None:
            response.data["delivery_context"] = pin.as_dict()
        return response

    @action(detail=False, methods=["get"])
    def facets(self, request):
        """Filter options + counts for the same parameters as the listing (incl. understood filters)."""
        base = selectors.annotate_pin(self._base_queryset(), self._pin())
        params, _ = self._interpreted(base, request.query_params)
        return Response(selectors.product_facets(base, params))

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

    @extend_schema(
        parameters=[
            OpenApiParameter("variant", int, description="Variant id (or choose by options: opt_<type>=<value>)"),
            OpenApiParameter("quantity", int, description="Units, default 1"),
            OpenApiParameter("opt_<option>", str, description="Option value slug, e.g. opt_grade=53-grade"),
        ],
        responses={200: None},
    )
    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def quote(self, request, slug=None):
        """What `quantity` units would cost, from the shop's pricing engine (bulk tier, live offers,
        free-delivery progress). The cart and checkout price again when ordering; this is a preview."""
        from .quote import quote_product

        product = self.get_object()
        user = request.user if request.user.is_authenticated else None
        return Response(quote_product(product, request.query_params, user=user))


def _detail_data(product, request) -> dict:
    from apps.delivery.pin import pin_context

    variant_ids = [v.id for v in product.variants.all()]
    pin = pin_context(request.query_params.get("postal_code"))
    context = {
        "request": request,
        "stock_map": selectors.variant_stock_map(variant_ids),
        # With a PIN, a variant is "fast" only when a store fast to that PIN holds it (Phase 16).
        "fast_variant_ids": selectors.variant_fast_delivery_ids(variant_ids, pin),
        "pin": pin,
    }
    if pin is not None:
        context["pin_variant_ids"] = selectors.variant_ids_at_stores(variant_ids, pin.serving_store_ids)
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


# --- Phase 15: options and curated lists ---------------------------------------------------------


class OptionTypeListView(APIView):
    """Option types and their values (Grade, Bag size, …), for filters and the assistant (public)."""

    permission_classes = [AllowAny]

    @extend_schema(responses=OptionTypeSerializer(many=True))
    def get(self, request):
        types = OptionType.objects.filter(is_active=True).prefetch_related("values").order_by("sort_order", "name")
        return Response(OptionTypeSerializer(types, many=True).data)


def _with_pin_stock(products, request):
    """Phase 16: add the shopper's PIN delivery flags to products loaded outside the listing query."""
    from apps.delivery.pin import pin_context

    pin = pin_context(request.query_params.get("postal_code"))
    if pin is None or not products:
        return pin
    rows = selectors.annotate_pin(Product.objects.filter(pk__in=[p.pk for p in products]), pin).values_list(
        "pk", "pin_stock", "pin_fast_stock"
    )
    stock = {pk: (s, f) for pk, s, f in rows}
    for product in products:
        product.pin_stock, product.pin_fast_stock = stock.get(product.pk, (0, 0))
    return pin


class CollectionListView(APIView):
    """Live curated lists that have products right now, each with its product cards (public).
    Empty or out-of-date lists are left out, so the shop front never shows an empty section."""

    permission_classes = [AllowAny]

    @extend_schema(responses=CollectionSerializer(many=True))
    def get(self, request):
        collections = list(live_collections())
        products = {c.pk: collection_products(c) for c in collections}
        visible = [c for c in collections if products[c.pk]]
        pin = _with_pin_stock([p for c in visible for p in products[c.pk]], request)
        context = {"request": request, "collection_products": products, "pin": pin}
        return Response(CollectionSerializer(visible, many=True, context=context).data)


class CollectionDetailView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=CollectionSerializer)
    def get(self, request, slug):
        from apps.core.exceptions import NotFoundError

        collection = live_collections().filter(slug=slug).first()
        products = collection_products(collection) if collection else []
        if not products:
            raise NotFoundError("This list isn't available right now.")
        pin = _with_pin_stock(products, request)
        context = {"request": request, "collection_products": {collection.pk: products}, "pin": pin}
        return Response(CollectionSerializer(collection, context=context).data)
