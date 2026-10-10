"""Server-side cart and wishlist.

One cart per customer (OneToOne, a portable DB guarantee). Placing an order empties it.
`price_at_add` is informational only (to show "price changed" notices); totals are always
recalculated from current catalog prices by `orders.pricing`.
"""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.core.money import MONEY_FIELD_KWARGS


class Cart(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart")
    # Cart-recovery reminder: when the last one was sent (one per cart change; see carts.jobs).
    reminded_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Cart<{self.user_id}>"


class CartItem(TimeStampedModel):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE, related_name="+")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    price_at_add = models.DecimalField(**MONEY_FIELD_KWARGS)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["cart", "variant"], name="uniq_cart_variant"),
            models.CheckConstraint(condition=Q(quantity__gte=1), name="cartitem_quantity_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.variant_id}"


class Wishlist(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlist")

    def __str__(self) -> str:
        return f"Wishlist<{self.user_id}>"


class WishlistItem(models.Model):
    wishlist = models.ForeignKey(Wishlist, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["wishlist", "product"], name="uniq_wishlist_product")]

    def __str__(self) -> str:
        return f"{self.product_id} in {self.wishlist_id}"
