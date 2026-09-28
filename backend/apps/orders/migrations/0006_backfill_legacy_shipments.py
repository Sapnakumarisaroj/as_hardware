"""Orders placed before Phase 9 had one store and no shipment rows. Give each of them a single
"legacy" shipment for that store and attach its items, so stock movements (pickup, cancel,
return restock) keep using the right store. No delivery estimate is invented for them."""

from django.db import migrations


def forwards(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    OrderShipment = apps.get_model("orders", "OrderShipment")
    OrderItem = apps.get_model("orders", "OrderItem")
    for order in Order.objects.filter(store__isnull=False, shipments__isnull=True).iterator():
        shipment = OrderShipment.objects.create(
            order=order, sequence=1, store_id=order.store_id, delivery_type="standard", eta_source="legacy"
        )
        OrderItem.objects.filter(order=order, shipment__isnull=True).update(shipment=shipment)


class Migration(migrations.Migration):
    dependencies = [("orders", "0005_order_delivery_type_order_delivery_window_end_and_more")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
