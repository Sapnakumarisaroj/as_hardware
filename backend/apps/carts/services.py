"""Cart and wishlist workflows. Stock and purchasability are validated on every add/change."""

from dataclasses import dataclass, field

from django.db import IntegrityError, transaction

from apps.catalog.models import Product, ProductVariant
from apps.core.exceptions import NotFoundError, ServiceError
from apps.inventory.services import InsufficientStock, total_available
from apps.orders.pricing import PricedLine, Totals, calculate_totals, line_from_variant

from .models import Cart, CartItem, Wishlist, WishlistItem


class CartError(ServiceError):
    default_code = "cart_error"


def get_cart(user) -> Cart:
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


def _purchasable_variant(variant_id: int) -> ProductVariant:
    variant = (
        ProductVariant.objects.select_related("product")
        .filter(pk=variant_id, is_active=True, product__is_deleted=False)
        .first()
    )
    if variant is None or not variant.product.is_purchasable:
        raise CartError("This product is not available.", code="product_unavailable")
    return variant


def _validate_quantity(variant: ProductVariant, quantity: int) -> None:
    if quantity < 1:
        raise CartError("Quantity must be at least 1.", code="invalid_quantity")
    limit = variant.product.max_order_quantity
    if quantity > limit:
        raise CartError(
            f"You can order at most {limit} of this item.", code="max_quantity_exceeded", details={"max": limit}
        )
    available = total_available(variant.id)
    if quantity > available:
        raise InsufficientStock(
            f"Only {available} unit(s) available." if available else "This item is out of stock.",
            details={"sku": variant.sku, "available": available},
        )


@transaction.atomic
def add_item(user, variant_id: int, quantity: int = 1) -> CartItem:
    """Add to cart, or increase the quantity if the variant is already in it."""
    cart = Cart.objects.select_for_update().get(pk=get_cart(user).pk)
    variant = _purchasable_variant(variant_id)
    item = CartItem.objects.filter(cart=cart, variant=variant).first()
    new_quantity = (item.quantity if item else 0) + quantity
    _validate_quantity(variant, new_quantity)
    if item:
        item.quantity = new_quantity
        item.save(update_fields=["quantity", "updated_at"])
        return item
    return CartItem.objects.create(cart=cart, variant=variant, quantity=new_quantity, price_at_add=variant.price)


@transaction.atomic
def set_item_quantity(user, item_id: int, quantity: int) -> CartItem:
    item = (
        CartItem.objects.select_for_update()
        .select_related("variant__product")
        .filter(pk=item_id, cart__user=user)
        .first()
    )
    if item is None:
        raise NotFoundError("Item not found in your cart.")
    _purchasable_variant(item.variant_id)
    _validate_quantity(item.variant, quantity)
    item.quantity = quantity
    item.save(update_fields=["quantity", "updated_at"])
    return item


def remove_item(user, item_id: int) -> None:
    deleted, _ = CartItem.objects.filter(pk=item_id, cart__user=user).delete()
    if not deleted:
        raise NotFoundError("Item not found in your cart.")


def clear_cart(user) -> None:
    CartItem.objects.filter(cart__user=user).delete()


@dataclass
class CartLineView:
    item: CartItem
    available_quantity: int
    purchasable: bool
    priced: PricedLine | None

    @property
    def in_stock(self) -> bool:
        return self.purchasable and self.available_quantity >= self.item.quantity

    @property
    def price_changed(self) -> bool:
        return self.item.price_at_add != self.item.variant.price


@dataclass
class CartSummary:
    cart: Cart
    lines: list[CartLineView]
    totals: Totals
    issues: list[str] = field(default_factory=list)

    @property
    def can_checkout(self) -> bool:
        return bool(self.lines) and not self.issues

    @property
    def priced_lines(self) -> list[PricedLine]:
        """Lines that count towards totals: purchasable and in stock."""
        return [line.priced for line in self.lines if line.priced is not None and line.in_stock]


def summarize_cart(user) -> CartSummary:
    """Current prices and stock for every line; totals include only purchasable, in-stock lines."""
    cart = get_cart(user)
    items = (
        cart.items.select_related("variant__product__brand")
        .prefetch_related("variant__product__images")
        .order_by("created_at", "id")
    )
    lines, issues = [], []
    for item in items:
        variant, product = item.variant, item.variant.product
        purchasable = variant.is_active and product.is_purchasable
        available = total_available(variant.id) if purchasable else 0
        view = CartLineView(
            item=item,
            available_quantity=available,
            purchasable=purchasable,
            priced=line_from_variant(variant, item.quantity) if purchasable else None,
        )
        if not purchasable:
            issues.append(f"{product.name} is no longer available.")
        elif not view.in_stock:
            issues.append(f"Only {available} unit(s) of {view.item.variant} available.")
        lines.append(view)
    summary = CartSummary(cart=cart, lines=lines, totals=calculate_totals([]), issues=issues)
    summary.totals = calculate_totals(summary.priced_lines)
    return summary


# --- Wishlist ---------------------------------------------------------------------


def get_wishlist(user) -> Wishlist:
    wishlist, _ = Wishlist.objects.get_or_create(user=user)
    return wishlist


def add_to_wishlist(user, product_id: int) -> WishlistItem:
    product = Product.objects.filter(pk=product_id, is_active=True, is_published=True).first()
    if product is None:
        raise ServiceError("This product is not available.", code="product_unavailable")
    wishlist = get_wishlist(user)
    try:
        with transaction.atomic():
            item, _ = WishlistItem.objects.get_or_create(wishlist=wishlist, product=product)
    except IntegrityError:  # concurrent duplicate add
        item = WishlistItem.objects.get(wishlist=wishlist, product=product)
    return item


def remove_from_wishlist(user, product_id: int) -> None:
    WishlistItem.objects.filter(wishlist__user=user, product_id=product_id).delete()
