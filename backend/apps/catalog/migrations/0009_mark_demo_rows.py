"""Mark rows created by the demo seed: products whose SKU starts with "DEMO-" and the fictional
"(Demo)" brands. Real brands (e.g. Fevicol, used by demo products too) are never marked."""

from django.db import migrations


def mark(apps, schema_editor):
    apps.get_model("catalog", "Product")._base_manager.filter(sku__startswith="DEMO-").update(is_demo=True)
    apps.get_model("catalog", "Brand")._base_manager.filter(name__endswith="(Demo)").update(is_demo=True)


class Migration(migrations.Migration):
    dependencies = [("catalog", "0008_demo_flag_cost_price")]

    operations = [migrations.RunPython(mark, migrations.RunPython.noop)]
