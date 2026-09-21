from django.urls import path

from .views import CartItemDetailView, CartItemsView, CartView, CouponPreviewView, WishlistItemView, WishlistView

urlpatterns = [
    path("cart/", CartView.as_view(), name="cart"),
    path("cart/items/", CartItemsView.as_view(), name="cart-items"),
    path("cart/items/<int:item_id>/", CartItemDetailView.as_view(), name="cart-item-detail"),
    path("cart/coupon-preview/", CouponPreviewView.as_view(), name="cart-coupon-preview"),
    path("wishlist/", WishlistView.as_view(), name="wishlist"),
    path("wishlist/<int:product_id>/", WishlistItemView.as_view(), name="wishlist-item"),
]
