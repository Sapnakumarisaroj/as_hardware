from django.db import IntegrityError, transaction
from django.db.models import Avg, Count
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.exceptions import ConflictError, ServiceError
from apps.core.money import q
from apps.orders.models import OrderItem, OrderStatus

from .models import Review


class ReviewError(ServiceError):
    default_code = "review_error"


@transaction.atomic
def create_review(*, user, product: Product, rating: int, title: str = "", body: str = "") -> Review:
    if not isinstance(rating, int) or not 1 <= rating <= 5:
        raise ReviewError("Rating must be a whole number from 1 to 5.", code="invalid_rating")
    # Only real buyers may review: prevents fake/competitor reviews.
    purchase = (
        OrderItem.objects.filter(order__user=user, product=product, order__status=OrderStatus.DELIVERED)
        .order_by("-order__delivered_at")
        .first()
    )
    if purchase is None:
        raise ReviewError("You can review a product after it has been delivered to you.", code="not_purchased")
    if Review.objects.filter(user=user, product=product).exists():
        raise ConflictError(
            "You have already reviewed this product. Edit your existing review instead.", code="duplicate_review"
        )
    try:
        with transaction.atomic():
            return Review.objects.create(
                user=user,
                product=product,
                order_item=purchase,
                rating=rating,
                title=title.strip()[:120],
                body=body.strip()[:3000],
                is_verified_purchase=True,
            )
    except IntegrityError as exc:  # concurrent duplicate
        raise ConflictError("You have already reviewed this product.", code="duplicate_review") from exc


@transaction.atomic
def moderate_review(review: Review, *, status: str, moderator, note: str = "") -> Review:
    if status not in (Review.Status.APPROVED, Review.Status.REJECTED):
        raise ReviewError("Status must be approved or rejected.", code="invalid_status")
    review.status = status
    review.moderated_by = moderator
    review.moderated_at = timezone.now()
    review.moderation_note = note[:255]
    review.save()
    refresh_product_rating(review.product_id)
    return review


def refresh_product_rating(product_id: int) -> None:
    agg = Review.objects.filter(product_id=product_id, status=Review.Status.APPROVED).aggregate(
        avg=Avg("rating"), count=Count("id")
    )
    Product.all_objects.filter(pk=product_id).update(rating_avg=q(agg["avg"] or 0), rating_count=agg["count"] or 0)
