"""Regression: on PostgreSQL, placing an order failed with "FOR UPDATE cannot be applied to the nullable side of an
outer join". The checkout locks the cart lines while loading each product's brand, which is optional (a LEFT OUTER
JOIN); the lock must cover the cart_item rows only.

The test database here is SQLite, which has no row locks, so the SQL PostgreSQL would receive is checked by
compiling the real checkout query with Django's PostgreSQL backend (no server needed). The live check on a
PostgreSQL server is the deployment smoke test (placing an order).
"""

import pytest
from django.db import connection
from django.db.backends.postgresql.base import DatabaseWrapper

from apps.carts.services import add_item
from apps.core.testing import create_address, create_product
from apps.orders.services import _cart_items_for_update, place_order

pytestmark = pytest.mark.django_db


def _postgresql_sql(queryset) -> str:
    pg = DatabaseWrapper({**connection.settings_dict, "ENGINE": "django.db.backends.postgresql"}, alias="pg-sql-check")
    pg.get_autocommit = lambda: False  # compile only (select_for_update needs a transaction); never connects
    sql, _params = queryset.query.get_compiler(connection=pg).as_sql()
    return sql


def test_checkout_locks_only_the_cart_lines_on_postgresql(user):
    sql = _postgresql_sql(_cart_items_for_update(user))
    assert 'LEFT OUTER JOIN "catalog_brand"' in sql  # the optional brand is still loaded with the lines
    assert sql.rstrip().endswith('FOR UPDATE OF "carts_cartitem"')  # …but only the cart lines are locked


def test_a_product_without_a_brand_can_be_ordered(user):
    product, variant = create_product(name="Unbranded hinge", stock=5)
    type(product).objects.filter(pk=product.pk).update(brand=None)  # the helper always sets a test brand
    variant.refresh_from_db()
    assert variant.product.brand_id is None
    add_item(user, variant.id, 2)
    order, _payment = place_order(user=user, address_id=create_address(user).id, payment_method="cod")
    assert order.items.get().quantity == 2 and order.items.get().brand_name == ""
