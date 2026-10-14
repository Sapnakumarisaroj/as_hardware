"""Regression: on PostgreSQL, sending an email/WhatsApp notification failed with "FOR UPDATE cannot be applied to the
nullable side of an outer join". The notification is locked while loading the user's profile, a reverse one-to-one
(always a LEFT OUTER JOIN); the lock must cover the notification row only.

The test database is SQLite (no row locks), so the SQL PostgreSQL would receive is checked by compiling the real
query with Django's PostgreSQL backend (no server needed); sending runs here too.
"""

import pytest
from django.db import connection, transaction
from django.db.backends.postgresql.base import DatabaseWrapper

from apps.accounts.models import CustomerProfile
from apps.notifications import services
from apps.notifications.models import Channel, Notification
from apps.notifications.services import _notification_for_update

pytestmark = pytest.mark.django_db


def _postgresql_sql(queryset) -> str:
    pg = DatabaseWrapper({**connection.settings_dict, "ENGINE": "django.db.backends.postgresql"}, alias="pg-sql-check")
    pg.get_autocommit = lambda: False  # compile only (select_for_update needs a transaction); never connects
    sql, _params = queryset.query.get_compiler(connection=pg).as_sql()
    return sql


def test_a_notification_lock_covers_only_its_own_row_on_postgresql():
    sql = _postgresql_sql(_notification_for_update(1))
    assert 'LEFT OUTER JOIN "accounts_customerprofile"' in sql  # the profile is still loaded
    assert sql.rstrip().endswith('FOR UPDATE OF "notifications_notification"')


def test_a_notification_for_a_user_without_a_profile_is_still_sent(user):
    CustomerProfile.objects.filter(user=user).delete()  # the nullable side of the join is empty
    note = Notification.objects.create(
        user=user, channel=Channel.EMAIL, event="order.confirmed",
        title="Order confirmed", body="Your order is confirmed.", data={"order_number": "OD1"},
    )  # fmt: skip
    with transaction.atomic():
        assert _notification_for_update(note.pk).first().pk == note.pk
    assert services.deliver(note.pk) != "skipped"
    note.refresh_from_db()
    assert note.attempts == 1
