from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
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
