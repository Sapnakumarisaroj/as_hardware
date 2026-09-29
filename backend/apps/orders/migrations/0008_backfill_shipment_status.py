"""Shipments get their own status and stock state in Phase 10. Existing shipments take them from
their order, which until now was the only place the delivery progress was recorded."""

from django.db import migrations

# order status → (shipment status, stock state)
FROM_ORDER = {
    "pending": ("pending", "reserved"),
    "confirmed": ("pending", "reserved"),
    "processing": ("pending", "reserved"),
    "packed": ("pending", "reserved"),
    "assigned": ("assigned", "reserved"),
    "picked_up": ("picked_up", "sold"),
    "out_for_delivery": ("out_for_delivery", "sold"),
    "delivered": ("delivered", "sold"),
    "return_requested": ("delivered", "sold"),
    "returned": ("delivered", "sold"),
}


def forwards(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    OrderShipment = apps.get_model("orders", "OrderShipment")
    OrderStatusHistory = apps.get_model("orders", "OrderStatusHistory")
    for order in Order.objects.filter(shipments__isnull=False).distinct().iterator():
        shipments = OrderShipment.objects.filter(order=order)
        if order.status == "cancelled":
            # Stock had been released only if the order was cancelled before pickup (always the
            # case so far: cancelling was not possible later).
            left_store = OrderStatusHistory.objects.filter(order=order, to_status="picked_up").exists()
            shipments.update(status="cancelled", stock_state="sold" if left_store else "released")
            continue
        status, stock_state = FROM_ORDER.get(order.status, ("pending", "reserved"))
        fields = {"status": status, "stock_state": stock_state}
        if status == "delivered":
            fields["delivered_at"] = order.delivered_at
        shipments.update(**fields)


class Migration(migrations.Migration):
    dependencies = [("orders", "0007_phase10_delivery_workflow")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
