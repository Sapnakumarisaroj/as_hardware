"""Consistency checks between orders, payments and refunds; the Phase 8 data migration."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.carts.services import add_item
from apps.orders.models import Order
from apps.orders.services import cancel_order_by_customer, place_order
from apps.payments import services
from apps.payments.consistency import find_issues
from apps.payments.models import Payment, Refund
from apps.payments.refunds import process_refund


@pytest.mark.django_db
def test_normal_flows_are_consistent_and_broken_records_are_reported(user, shop, gateway):
    add_item(user, shop["tape"].id, 1)
    order, payment = place_order(user=user, address_id=shop["address"].id, payment_method="online")
    services.verify_payment(payment.public_id, user=user, payload={})
    cancel_order_by_customer(order, user=user, reason="Changed my mind")
    process_refund(Refund.objects.get().pk)
    assert find_issues() == []

    add_item(user, shop["tape"].id, 1)
    other, other_payment = place_order(user=user, address_id=shop["address"].id, payment_method="online")
    Order.objects.filter(pk=other.pk).update(payment_status="paid")  # paid without money
    Payment.objects.filter(pk=payment.pk).update(status="captured")  # refunded money marked captured
    Refund.objects.create(payment=payment, amount=Decimal("500.00"), reason="bogus")  # beyond the payment
    codes = {issue["code"] for issue in find_issues()}
    assert {"paid_without_capture", "over_refunded", "refund_status_mismatch"} <= codes

    out, err = StringIO(), StringIO()
    with pytest.raises(SystemExit) as exc:
        call_command("payments_check", stdout=out, stderr=err)
    assert exc.value.code == 1 and "paid_without_capture" in out.getvalue()


@pytest.mark.django_db
def test_payments_check_passes_on_a_clean_database():
    out = StringIO()
    call_command("payments_check", stdout=out)
    assert "no issues" in out.getvalue()


BEFORE = [("payments", "0002_refund_gateway_and_webhooks"), ("orders", "0004_return_requests")]
AFTER = [("payments", "0003_backfill_refund_reference_and_cod_collection"), ("orders", "0004_return_requests")]


@pytest.mark.django_db(transaction=True)
def test_backfill_collects_cod_for_delivered_orders_and_sets_refund_references():
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)
    old = executor.loader.project_state(BEFORE).apps
    user = old.get_model("accounts", "User").objects.create(email="old@example.com", role="customer")
    Order, Payment, Refund = (
        old.get_model(*m) for m in (("orders", "Order"), ("payments", "Payment"), ("payments", "Refund"))
    )
    zero, hundred = Decimal("0"), Decimal("100")
    money = dict(address_snapshot={}, payment_method="cod", subtotal=hundred, mrp_total=hundred,
                 discount_total=zero, delivery_fee=zero, tax_total=zero, grand_total=hundred)  # fmt: skip
    delivered = Order.objects.create(order_number="ODOLD1", user_id=user.pk, status="returned", **money)
    open_order = Order.objects.create(order_number="ODOLD2", user_id=user.pk, status="confirmed", **money)
    paid = Payment.objects.create(
        order=delivered, provider="cod", method="cod", amount=Decimal("100"), status="pending"
    )
    Payment.objects.create(order=open_order, provider="cod", method="cod", amount=Decimal("100"), status="pending")
    old_refund = Refund.objects.create(payment=paid, amount=Decimal("100"), reason="Return RT1")

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(AFTER)
    new = executor.loader.project_state(AFTER).apps
    NewPayment, NewOrder = new.get_model("payments", "Payment"), new.get_model("orders", "Order")
    assert NewPayment.objects.get(order__order_number="ODOLD1").status == "captured"
    assert NewOrder.objects.get(order_number="ODOLD1").payment_status == "paid"
    assert NewPayment.objects.get(order__order_number="ODOLD2").status == "pending"  # not delivered yet
    refund = new.get_model("payments", "Refund").objects.get(pk=old_refund.pk)
    assert refund.provider_reference == f"{refund.public_id.hex}-1"

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())
