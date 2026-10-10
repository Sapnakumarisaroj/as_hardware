"""Mark the demo seed's stores (codes starting with "DEMO-")."""

from django.db import migrations


def mark(apps, schema_editor):
    apps.get_model("stores", "Store")._base_manager.filter(code__startswith="DEMO-").update(is_demo=True)


class Migration(migrations.Migration):
    dependencies = [("stores", "0005_store_is_demo")]

    operations = [migrations.RunPython(mark, migrations.RunPython.noop)]
