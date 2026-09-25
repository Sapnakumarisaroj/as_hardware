"""Data for Phase 8 on existing rows.

1. Refunds recorded before Phase 8 get their gateway reference (`<public_id hex>-1`) so they can be
   submitted like new ones.
2. Cash-on-delivery orders already delivered before Phase 8 never recorded the cash as collected;
   from Phase 8 delivery does. Their COD payment becomes captured (at the delivery time) and the
   order `paid`, so returns of those orders can be refunded and the consistency check agrees.
"""

from django.db import migrations

DELIVERED_OR_LATER = ("delivered", "return_requested", "returned")


def forwards(apps, schema_editor):
    Refund = apps.get_model("payments", "Refund")
    Payment = apps.get_model("payments", "Payment")
    for refund in Refund.objects.filter(provider_reference=""):
        refund.provider_reference = f"{refund.public_id.hex}-1"
        refund.save(update_fields=["provider_reference"])
    for payment in Payment.objects.filter(provider="cod", status="pending", order__status__in=DELIVERED_OR_LATER):
        order = payment.order
        payment.status, payment.method = "captured", "cod"
        payment.captured_at = order.delivered_at or order.updated_at
        payment.save(update_fields=["status", "method", "captured_at"])
        if order.payment_status == "pending":
            order.payment_status = "paid"
            order.save(update_fields=["payment_status"])


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_refund_gateway_and_webhooks"),
        ("orders", "0004_return_requests"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
