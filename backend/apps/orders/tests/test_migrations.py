"""Data migration check: orders placed before Phase 6 keep their discount as the coupon portion."""

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("orders", "0002_order_idempotency_key")]
AFTER = [("orders", "0003_order_discount_breakdown")]


@pytest.mark.django_db(transaction=True)
def test_existing_orders_get_coupon_discount_backfilled():
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)
    old_apps = executor.loader.project_state(BEFORE).apps
    user = old_apps.get_model("accounts", "User").objects.create(email="old@example.com", role="customer")
    Order = old_apps.get_model("orders", "Order")
    common = dict(user_id=user.pk, address_snapshot={}, payment_method="cod", subtotal=Decimal("500"),
                  mrp_total=Decimal("600"), delivery_fee=Decimal("0"), tax_total=Decimal("0"))  # fmt: skip
    Order.objects.create(order_number="ODOLD1", discount_total=Decimal("50.00"), grand_total=Decimal("450"), **common)
    Order.objects.create(order_number="ODOLD2", discount_total=Decimal("0.00"), grand_total=Decimal("500"), **common)

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(AFTER)
    new_apps = executor.loader.project_state(AFTER).apps
    rows = {
        o.order_number: (o.coupon_discount, o.offer_discount, o.applied_offers)
        for o in new_apps.get_model("orders", "Order").objects.all()
    }
    assert rows["ODOLD1"] == (Decimal("50.00"), Decimal("0.00"), [])
    assert rows["ODOLD2"] == (Decimal("0.00"), Decimal("0.00"), [])

    # Leave the database fully migrated for the rest of the suite.
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())
