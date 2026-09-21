from decimal import Decimal

import pytest

from apps.carts.services import add_item
from apps.core.exceptions import ServiceError
from apps.core.testing import create_address, create_product
from apps.orders.services import place_order, transition_order
from apps.reviews.models import Review
from apps.reviews.services import ReviewError, create_review, moderate_review

pytestmark = pytest.mark.django_db


def _deliver(user, staff, variant):
    add_item(user, variant.id, 1)
    order, _ = place_order(user=user, address_id=create_address(user).id, payment_method="cod")
    for status in ("processing", "packed", "assigned", "picked_up", "out_for_delivery", "delivered"):
        order = transition_order(order, status, actor=staff)
    return order


def test_review_requires_delivered_purchase(user, staff_user):
    product, variant = create_product(stock=5)
    with pytest.raises(ReviewError) as exc:
        create_review(user=user, product=product, rating=5)
    assert exc.value.error_code == "not_purchased"

    _deliver(user, staff_user, variant)
    review = create_review(user=user, product=product, rating=4, body="Solid drill")
    assert review.is_verified_purchase and review.status == Review.Status.PENDING


def test_duplicate_review_rejected(user, staff_user):
    product, variant = create_product(stock=5)
    _deliver(user, staff_user, variant)
    create_review(user=user, product=product, rating=4)
    with pytest.raises(ServiceError) as exc:
        create_review(user=user, product=product, rating=1)
    assert exc.value.error_code == "duplicate_review"


@pytest.mark.parametrize("rating", [0, 6, -1])
def test_rating_must_be_1_to_5(user, staff_user, rating):
    product, variant = create_product(stock=5)
    _deliver(user, staff_user, variant)
    with pytest.raises(ReviewError):
        create_review(user=user, product=product, rating=rating)


def test_only_approved_reviews_are_public_and_rated(user, staff_user, api_client):
    product, variant = create_product(stock=5)
    _deliver(user, staff_user, variant)
    review = create_review(user=user, product=product, rating=4, body="Good")
    assert api_client.get(f"/api/products/{product.slug}/reviews/").json()["count"] == 0

    moderate_review(review, status=Review.Status.APPROVED, moderator=staff_user)
    body = api_client.get(f"/api/products/{product.slug}/reviews/").json()
    assert body["count"] == 1 and body["results"][0]["author"] == "Asha"
    product.refresh_from_db()
    assert product.rating_avg == Decimal("4.00") and product.rating_count == 1


def test_review_api_requires_login_and_purchase(auth_client, api_client):
    product, _ = create_product(stock=5)
    url = f"/api/products/{product.slug}/reviews/"
    assert api_client.post(url, {"rating": 5}, format="json").status_code == 401
    res = auth_client.post(url, {"rating": 5}, format="json")
    assert res.status_code == 400 and res.json()["error"]["code"] == "not_purchased"
