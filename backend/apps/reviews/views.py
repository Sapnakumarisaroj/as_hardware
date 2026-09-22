from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import SAFE_METHODS, AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.catalog.models import Product

from . import services
from .models import Review


class ReviewSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ["id", "rating", "title", "body", "author", "is_verified_purchase", "status", "created_at"]
        read_only_fields = ["is_verified_purchase", "status", "created_at"]

    def get_author(self, obj) -> str:
        # First name only: never expose customer emails/phones publicly.
        return obj.user.get_short_name() if obj.user.full_name else "Customer"


class ReviewCreateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    title = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    body = serializers.CharField(max_length=3000, required=False, allow_blank=True, default="")


class ProductReviewsView(GenericAPIView):
    """GET: approved reviews of a product (public). POST: review a product you received."""

    serializer_class = ReviewSerializer

    def get_permissions(self):
        return [AllowAny()] if self.request.method in SAFE_METHODS else [IsAuthenticated()]

    def _product(self, slug):
        return get_object_or_404(Product, slug=slug, is_active=True, is_published=True)

    def get(self, request, slug):
        product = self._product(slug)
        qs = Review.objects.filter(product=product, status=Review.Status.APPROVED).select_related("user")
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(ReviewSerializer(page, many=True).data)

    @extend_schema(request=ReviewCreateSerializer, responses={201: ReviewSerializer})
    def post(self, request, slug):
        product = self._product(slug)
        serializer = ReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = services.create_review(user=request.user, product=product, **serializer.validated_data)
        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)


class MyReviewSerializer(ReviewSerializer):
    product_slug = serializers.CharField(source="product.slug", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta(ReviewSerializer.Meta):
        fields = ReviewSerializer.Meta.fields + ["product_slug", "product_name"]


class ReviewUpdateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5, required=False)
    title = serializers.CharField(max_length=120, required=False, allow_blank=True)
    body = serializers.CharField(max_length=3000, required=False, allow_blank=True)


class MyReviewViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """The signed-in customer's own reviews (any moderation status). Edits go back to moderation."""

    serializer_class = MyReviewSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Review.objects.none()
        return Review.objects.filter(user=self.request.user).select_related("product", "user")

    @extend_schema(request=ReviewUpdateSerializer, responses=MyReviewSerializer)
    def partial_update(self, request, pk=None):
        review = self.get_object()
        serializer = ReviewUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        review = services.update_own_review(review, **serializer.validated_data)
        return Response(MyReviewSerializer(review).data)

    def perform_destroy(self, instance):
        services.delete_own_review(instance)
