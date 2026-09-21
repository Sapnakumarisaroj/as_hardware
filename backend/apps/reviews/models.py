"""Customer reviews. One review per customer per product (DB unique constraint); only
customers with a delivered purchase may review (enforced in reviews.services)."""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class Review(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending moderation"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    order_item = models.ForeignKey(
        "orders.OrderItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="reviews"
    )
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=120, blank=True)
    body = models.TextField(max_length=3000, blank=True)
    is_verified_purchase = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderation_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "product"], name="uniq_review_user_product"),
            models.CheckConstraint(condition=Q(rating__gte=1) & Q(rating__lte=5), name="review_rating_1_to_5"),
        ]
        indexes = [models.Index(fields=["product", "status", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.rating}★ by {self.user_id} on {self.product_id}"
