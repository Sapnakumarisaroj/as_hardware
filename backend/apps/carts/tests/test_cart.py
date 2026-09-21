import pytest

from apps.carts.models import Cart, CartItem
from apps.core.testing import create_product

pytestmark = pytest.mark.django_db


def test_cart_requires_authentication(api_client):
    assert api_client.get("/api/cart/").status_code == 401


def test_cart_created_empty_on_first_access(auth_client, user):
    res = auth_client.get("/api/cart/")
    assert res.status_code == 200
    assert res.json()["items"] == [] and res.json()["can_checkout"] is False
    assert Cart.objects.filter(user=user).count() == 1


def test_add_increment_and_update_quantity(auth_client):
    _, variant = create_product(price="200.00", mrp="250.00", stock=10)
    res = auth_client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": 2}, format="json")
    assert res.status_code == 201
    res = auth_client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": 3}, format="json")
    body = res.json()
    assert len(body["items"]) == 1 and body["items"][0]["quantity"] == 5
    assert body["totals"]["subtotal"] == "1000.00"
    assert body["totals"]["delivery_fee"] == "0.00"  # above free-delivery threshold (499)

    item_id = body["items"][0]["id"]
    res = auth_client.patch(f"/api/cart/items/{item_id}/", {"quantity": 1}, format="json")
    assert res.json()["items"][0]["quantity"] == 1
    assert res.json()["totals"]["delivery_fee"] == "40.00"
    assert res.json()["totals"]["grand_total"] == "240.00"


def test_stock_validation_on_add_and_update(auth_client):
    _, variant = create_product(stock=3)
    res = auth_client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": 4}, format="json")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "insufficient_stock"
    auth_client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": 3}, format="json")
    res = auth_client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": 1}, format="json")
    assert res.status_code == 409
    item = CartItem.objects.get()
    assert auth_client.patch(f"/api/cart/items/{item.id}/", {"quantity": 9}, format="json").status_code == 409


def test_out_of_stock_and_unpublished_products_rejected(auth_client):
    _, no_stock = create_product()
    _, hidden = create_product(published=False, stock=5)
    assert auth_client.post("/api/cart/items/", {"variant_id": no_stock.id}, format="json").status_code == 409
    res = auth_client.post("/api/cart/items/", {"variant_id": hidden.id}, format="json")
    assert res.status_code == 400 and res.json()["error"]["code"] == "product_unavailable"


def test_max_order_quantity_enforced(auth_client):
    _, variant = create_product(stock=100, max_order_quantity=5)
    res = auth_client.post("/api/cart/items/", {"variant_id": variant.id, "quantity": 6}, format="json")
    assert res.status_code == 400 and res.json()["error"]["code"] == "max_quantity_exceeded"


def test_cart_uses_current_price_and_flags_changes(auth_client):
    _, variant = create_product(price="100.00", mrp="100.00", stock=5)
    auth_client.post("/api/cart/items/", {"variant_id": variant.id}, format="json")
    variant.price = variant.mrp = 120
    variant.save()
    line = auth_client.get("/api/cart/").json()["items"][0]
    assert line["unit_price"] == "120.00" and line["price_at_add"] == "100.00" and line["price_changed"] is True


def test_cannot_touch_another_users_cart_item(auth_client, other_user):
    _, variant = create_product(stock=5)
    other_cart = Cart.objects.create(user=other_user)
    item = CartItem.objects.create(cart=other_cart, variant=variant, quantity=1, price_at_add=variant.price)
    assert auth_client.patch(f"/api/cart/items/{item.id}/", {"quantity": 2}, format="json").status_code == 404
    assert auth_client.delete(f"/api/cart/items/{item.id}/").status_code == 404
    assert CartItem.objects.filter(pk=item.pk).exists()


def test_remove_and_clear(auth_client):
    _, a = create_product(stock=5)
    _, b = create_product(stock=5)
    auth_client.post("/api/cart/items/", {"variant_id": a.id}, format="json")
    res = auth_client.post("/api/cart/items/", {"variant_id": b.id}, format="json")
    first = res.json()["items"][0]["id"]
    assert len(auth_client.delete(f"/api/cart/items/{first}/").json()["items"]) == 1
    assert auth_client.delete("/api/cart/").json()["items"] == []


def test_wishlist_add_list_remove(auth_client):
    product, _ = create_product()
    assert auth_client.post("/api/wishlist/", {"product_id": product.id}, format="json").status_code == 201
    assert (
        auth_client.post("/api/wishlist/", {"product_id": product.id}, format="json").status_code == 201
    )  # idempotent
    items = auth_client.get("/api/wishlist/").json()
    assert len(items) == 1 and items[0]["product"]["id"] == product.id
    assert auth_client.delete(f"/api/wishlist/{product.id}/").status_code == 204
    assert auth_client.get("/api/wishlist/").json() == []


def test_wishlist_rejects_unpublished_product(auth_client):
    product, _ = create_product(published=False)
    assert auth_client.post("/api/wishlist/", {"product_id": product.id}, format="json").status_code == 400
