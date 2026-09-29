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


@pytest.mark.django_db(transaction=True)
def test_existing_shipments_take_their_status_from_the_order():
    """Phase 10: shipments get a status and a stock state; older ones follow their order."""
    before = [
        ("orders", "0007_phase10_delivery_workflow"),
        ("stores", "0003_store_own_riders_store_prep_minutes_per_item_and_more"),
    ]
    after = [("orders", "0008_backfill_shipment_status")]
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    old_apps = executor.loader.project_state(before).apps
    user = old_apps.get_model("accounts", "User").objects.create(email="old@example.com", role="customer")
    store = old_apps.get_model("stores", "Store").objects.create(
        name="Old store", code="OLD-1", address_line1="1 Road", city="Pune", state="MH", postal_code="411001"
    )
    Order = old_apps.get_model("orders", "Order")
    Shipment = old_apps.get_model("orders", "OrderShipment")
    History = old_apps.get_model("orders", "OrderStatusHistory")
    common = dict(user_id=user.pk, store_id=store.pk, address_snapshot={}, payment_method="cod",
                  subtotal=Decimal("500"), mrp_total=Decimal("600"), discount_total=Decimal("0"),
                  delivery_fee=Decimal("0"), tax_total=Decimal("0"), grand_total=Decimal("500"))  # fmt: skip
    delivered_at = "2026-09-20T10:00:00+05:30"
    statuses = ["confirmed", "packed", "assigned", "picked_up", "out_for_delivery", "delivered", "returned",
                "cancelled"]  # fmt: skip
    for status in statuses:
        order = Order.objects.create(
            order_number=f"OD-{status}"[:20],
            status=status,
            delivered_at=delivered_at if status in ("delivered", "returned") else None,
            **common,
        )
        Shipment.objects.create(order=order, sequence=1, store_id=store.pk, delivery_type="standard")
    late = Order.objects.create(order_number="OD-cancelled-late", status="cancelled", **common)
    Shipment.objects.create(order=late, sequence=1, store_id=store.pk, delivery_type="standard")
    History.objects.create(order=late, from_status="assigned", to_status="picked_up")

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(after)
    new_apps = executor.loader.project_state(after).apps
    rows = {
        s.order.order_number: (s.status, s.stock_state, s.delivered_at is not None)
        for s in new_apps.get_model("orders", "OrderShipment").objects.select_related("order")
    }
    assert rows == {
        "OD-confirmed": ("pending", "reserved", False),
        "OD-packed": ("pending", "reserved", False),
        "OD-assigned": ("assigned", "reserved", False),
        "OD-picked_up": ("picked_up", "sold", False),
        "OD-out_for_delivery": ("out_for_delivery", "sold", False),
        "OD-delivered": ("delivered", "sold", True),
        "OD-returned": ("delivered", "sold", True),
        "OD-cancelled": ("cancelled", "released", False),
        "OD-cancelled-late": ("cancelled", "sold", False),
    }

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())
