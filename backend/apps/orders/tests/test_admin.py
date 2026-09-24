"""Django admin can inspect orders, items, history, payments, refunds, notifications and customers;
money records stay read-only."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.carts.services import add_item
from apps.core.testing import create_address, create_product, create_store
from apps.notifications.models import Notification
from apps.orders.services import cancel_order_by_customer, place_order
from apps.payments.models import Payment, Refund

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_site():
    client = Client()
    client.force_login(get_user_model().objects.create_superuser(email="root@example.com", password="Passw0rd!x"))
    return client


def test_order_payment_refund_pages_load_and_money_is_read_only(admin_site, user):
    store = create_store()
    _, variant = create_product(stock=5, store=store)
    add_item(user, variant.id, 1)
    order, payment = place_order(user=user, address_id=create_address(user).id, payment_method="online")
    Payment.objects.filter(pk=payment.pk).update(status=Payment.Status.CAPTURED)
    cancel_order_by_customer(order, user=user, reason="Test")
    refund = Refund.objects.get()
    Notification.objects.create(user=user, event="order.cancelled", title="t", body="b")

    pages = [
        reverse("admin:orders_order_changelist"),
        reverse("admin:orders_order_change", args=[order.pk]),
        reverse("admin:payments_payment_changelist"),
        reverse("admin:payments_payment_change", args=[payment.pk]),
        reverse("admin:payments_refund_changelist"),
        reverse("admin:payments_refund_change", args=[refund.pk]),
        reverse("admin:notifications_notification_changelist"),
        reverse("admin:accounts_user_changelist"),
    ]
    for url in pages:
        assert admin_site.get(url).status_code == 200, url

    body = admin_site.get(reverse("admin:orders_order_change", args=[order.pk])).content.decode()
    assert order.items.get().sku in body and "cancelled" in body  # item + status history inlines

    # No add/delete for money records, and a POST cannot change a payment.
    assert admin_site.get(reverse("admin:payments_payment_add")).status_code == 403
    assert admin_site.get(reverse("admin:orders_order_add")).status_code == 403
    admin_site.post(reverse("admin:payments_payment_change", args=[payment.pk]), {"status": "refunded"})
    payment.refresh_from_db()
    assert payment.status == Payment.Status.CAPTURED
