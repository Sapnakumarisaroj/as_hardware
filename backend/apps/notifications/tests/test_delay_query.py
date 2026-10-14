"""Regression: on PostgreSQL the "running late" job failed with `operator does not exist: jsonb = character varying`.
It skips orders already told by matching Notification.data["order_number"] against Order.order_number; the JSON key
must be read as text (->>), not as jsonb (->).

The test database is SQLite (lenient about types), so the SQL PostgreSQL would receive is checked by compiling the
real query with Django's PostgreSQL backend (no server needed); the behaviour runs here.
"""

from datetime import timedelta

import pytest
from django.db import connection
from django.db.backends.postgresql.base import DatabaseWrapper
from django.utils import timezone

from apps.carts.services import add_item
from apps.core.testing import create_address, create_product, create_store
from apps.notifications import services
from apps.notifications.models import Notification
from apps.orders.models import Order
from apps.orders.services import place_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def late_orders(user, other_user, settings):
    """Two confirmed COD orders (two customers), both past their delivery estimate."""
    store = create_store()
    _, variant = create_product(name="Hinge", stock=20, store=store)
    orders = []
    for customer in (user, other_user):
        add_item(customer, variant.id, 1)
        order, _ = place_order(user=customer, address_id=create_address(customer).id, payment_method="cod")
        orders.append(order)
    late = timezone.now() - timedelta(minutes=settings.DELIVERY_DELAY_NOTICE_MINUTES + 5)
    Order.objects.filter(pk__in=[o.pk for o in orders]).update(estimated_delivery_at=late)
    return orders


def _told(order) -> int:
    return Notification.objects.filter(
        user=order.user, event="delivery.delayed", data__order_number=order.order_number
    ).count()


def test_already_told_check_compares_text_on_postgresql():
    """The real query of the job, compiled for PostgreSQL."""
    from django.db.models import Exists

    pg = DatabaseWrapper({**connection.settings_dict, "ENGINE": "django.db.backends.postgresql"}, alias="pg-sql-check")
    pg.get_autocommit = lambda: False  # compile only; never connects
    late = Order.objects.exclude(Exists(services._delay_notices()))
    sql, _params = late.query.get_compiler(connection=pg).as_sql()
    assert '(U0."data" ->> %s) = ("orders_order"."order_number")' in sql  # text = text
    assert '(U0."data" -> %s) = ("orders_order"."order_number")' not in sql  # never jsonb = varchar


def test_late_orders_are_told_once_and_repeat_runs_tell_nobody(
    late_orders, admin_user, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        assert services.tell_about_delays() == 2
    assert all(_told(order) >= 1 for order in late_orders)
    before = Notification.objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        assert services.tell_about_delays() == 0  # already told: nothing new
    assert Notification.objects.count() == before
    assert Notification.objects.filter(user=admin_user, event="staff.delivery_delayed").exists()  # staff told too


def test_only_a_notice_for_the_same_order_counts(late_orders, django_capture_on_commit_callbacks):
    first, second = late_orders
    # Already told about the first order.
    Notification.objects.create(
        user=first.user, event="delivery.delayed", title="Late", body="Late", data={"order_number": first.order_number}
    )
    # Unrelated: a "late" notice about another order number, and another event about the second order.
    Notification.objects.create(
        user=second.user,
        event="delivery.delayed",
        title="Late",
        body="Late",
        data={"order_number": "OD-SOMETHING-ELSE"},
    )
    Notification.objects.create(
        user=second.user, event="order.confirmed", title="Ok", body="Ok", data={"order_number": second.order_number}
    )
    with django_capture_on_commit_callbacks(execute=True):
        assert services.tell_about_delays() == 1  # only the second order
    assert _told(first) == 1  # not told again
    assert _told(second) >= 1


def test_a_notice_for_another_customer_does_not_count(late_orders, other_user, django_capture_on_commit_callbacks):
    first, _second = late_orders
    # Same order number, but sent to someone else: the first order's customer was not told.
    Notification.objects.create(
        user=other_user, event="delivery.delayed", title="Late", body="Late", data={"order_number": first.order_number}
    )
    with django_capture_on_commit_callbacks(execute=True):
        assert services.tell_about_delays() == 2
    assert Notification.objects.filter(
        user=first.user, event="delivery.delayed", data__order_number=first.order_number
    ).exists()
