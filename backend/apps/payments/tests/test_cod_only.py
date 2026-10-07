"""Phase 26: a cash-on-delivery-only shop (PAYMENT_PROVIDER=none). Before this, production could only
start with a real gateway or with ALLOW_MOCK_PAYMENTS_IN_PROD, which lets anyone confirm an online order
without paying."""

import pytest

from apps.carts.services import add_item
from apps.core.testing import create_address, create_product
from apps.orders.services import OrderError, place_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def cart(user):
    _, variant = create_product(price="500.00", mrp="600.00", stock=10)
    add_item(user, variant.id, 1)
    return create_address(user)


def test_checkout_offers_cod_only_without_a_gateway(settings, auth_client, cart):
    settings.PAYMENT_PROVIDER = "none"
    preview = auth_client.post("/api/checkout/preview/", {"address_id": cart.id}, format="json").json()
    methods = {m["value"]: m for m in preview["payment_methods"]}
    assert methods["online"]["available"] is False and methods["online"]["reason_code"] == "online_unavailable"
    assert methods["online"]["test_mode"] is False and methods["cod"]["available"] is True


def test_online_orders_are_refused_and_cod_still_works(settings, user, cart):
    settings.PAYMENT_PROVIDER = "none"
    with pytest.raises(OrderError) as exc:
        place_order(user=user, address_id=cart.id, payment_method="online")
    assert exc.value.error_code == "online_payment_unavailable"
    order, payment = place_order(user=user, address_id=cart.id, payment_method="cod")
    assert order.status == "confirmed" and payment.provider == "cod"


def test_api_refuses_online_orders_with_a_clear_message(settings, auth_client, cart):
    settings.PAYMENT_PROVIDER = "none"
    res = auth_client.post("/api/orders/", {"address_id": cart.id, "payment_method": "online"}, format="json")
    assert res.status_code == 400 and res.json()["error"]["code"] == "online_payment_unavailable"


def test_a_pending_online_order_cannot_retry_once_the_gateway_is_off(settings, auth_client, user, cart):
    order, _ = place_order(user=user, address_id=cart.id, payment_method="online")  # mock gateway in tests
    settings.PAYMENT_PROVIDER = "none"
    res = auth_client.post(f"/api/orders/{order.order_number}/retry-payment/", {}, format="json")
    assert res.status_code == 409 and res.json()["error"]["code"] == "online_payment_unavailable"
