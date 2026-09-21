from django.contrib import admin

from . import services
from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "user", "rating", "status", "is_verified_purchase", "created_at")
    list_filter = ("status", "rating", "is_verified_purchase")
    search_fields = ("product__name", "user__email", "title", "body")
    list_select_related = ("product", "user")
    readonly_fields = (
        "product",
        "user",
        "order_item",
        "rating",
        "title",
        "body",
        "is_verified_purchase",
        "moderated_by",
        "moderated_at",
    )
    actions = ["approve", "reject"]

    def has_add_permission(self, request):
        return False  # reviews come only from verified buyers via the API

    @admin.action(description="Approve selected reviews")
    def approve(self, request, queryset):
        for review in queryset:
            services.moderate_review(review, status=Review.Status.APPROVED, moderator=request.user)

    @admin.action(description="Reject selected reviews")
    def reject(self, request, queryset):
        for review in queryset:
            services.moderate_review(review, status=Review.Status.REJECTED, moderator=request.user)
