"""Regression: on PostgreSQL, a rider's job steps failed with "FOR UPDATE cannot be applied to the nullable side of
an outer join". The job is locked while loading its optional shipment (empty on a return pickup) and return request
(empty on a delivery); the lock must cover the assignment row only (the order row is locked first).

The test database is SQLite (no row locks), so the SQL PostgreSQL would receive is checked by compiling the real
query with Django's PostgreSQL backend (no server needed); the job step itself runs here too.
"""

import pytest
from django.db import connection, transaction
from django.db.backends.postgresql.base import DatabaseWrapper

from apps.core.testing import create_product
from apps.delivery.tests.helpers import assign, create_partner, packed_order, store_at
from apps.delivery.workflow import _assignment_for_update, _lock

pytestmark = pytest.mark.django_db


def _postgresql_sql(queryset) -> str:
    pg = DatabaseWrapper({**connection.settings_dict, "ENGINE": "django.db.backends.postgresql"}, alias="pg-sql-check")
    pg.get_autocommit = lambda: False  # compile only (select_for_update needs a transaction); never connects
    sql, _params = queryset.query.get_compiler(connection=pg).as_sql()
    return sql


def test_a_job_lock_covers_only_the_assignment_row_on_postgresql():
    sql = _postgresql_sql(_assignment_for_update(1))
    assert 'LEFT OUTER JOIN "orders_ordershipment"' in sql  # optional shipment / return request still loaded
    assert sql.rstrip().endswith('FOR UPDATE OF "delivery_deliveryassignment"')


def test_a_delivery_job_without_a_return_request_can_be_locked(user):
    store = store_at(0, zone=True)
    _, variant = create_product(stock=5, store=store)
    order = packed_order(user, (variant, 1))
    job = assign(order.shipments.get(), create_partner(store))
    with transaction.atomic():
        locked_order, assignment = _lock(job.pk)
    assert locked_order.pk == order.pk and assignment.pk == job.pk
    assert assignment.shipment_id is not None and assignment.return_request is None
