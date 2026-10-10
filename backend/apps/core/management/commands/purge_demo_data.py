"""Remove the demo catalogue, brands and stores (rows marked `is_demo` by `seed_demo_data`).

    python manage.py purge_demo_data            # dry run: list what would happen, change nothing
    python manage.py purge_demo_data --commit

Only rows with is_demo=True are touched. A demo row that history still points at is archived
(soft-deleted and switched off) instead of deleted, so orders, shipments, reviews and quotes keep
working:
- products: archived when ordered, reviewed or quoted (or anything else refuses the delete);
  otherwise deleted with their variants, pictures and their demo stock records.
- stores: archived when orders/shipments used them or they hold stock of real products;
  otherwise deleted with their delivery zones.
- brands: deleted when no product uses them, archived when only demo products do, and left alone
  (reported) while a real product still uses them.
Safe to run again: archived rows are skipped.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils import timezone

from apps.catalog.models import Brand, Product
from apps.inventory.models import Inventory, StockMovement
from apps.orders.models import Order, OrderItem, OrderShipment
from apps.stores.models import Store


class Command(BaseCommand):
    help = "Delete or archive demo products, brands and stores (dry run unless --commit). Real rows are never touched."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Apply the changes (default: dry run).")

    def handle(self, *args, commit=False, **options):
        report = {key: [] for key in ("deleted", "archived", "kept")}
        with transaction.atomic():
            for product in Product.all_objects.filter(is_demo=True).order_by("sku"):
                self._product(product, report)
            for store in Store.all_objects.filter(is_demo=True).order_by("code"):
                self._store(store, report)
            for brand in Brand.all_objects.filter(is_demo=True).order_by("name"):
                self._brand(brand, report)
            if not commit:
                transaction.set_rollback(True)
        for label, key in (("Deleted", "deleted"), ("Archived (still referenced)", "archived"), ("Kept", "kept")):
            if report[key]:
                self.stdout.write(f"{label} ({len(report[key])}):")
                for line in report[key]:
                    self.stdout.write(f"  {line}")
        summary = ", ".join(f"{len(rows)} {key}" for key, rows in report.items())
        if not any(report.values()):
            summary = "nothing to do (demo rows are already removed or archived)"
        prefix = "" if commit else "Dry run, nothing changed (add --commit to apply): "
        self.stdout.write(self.style.SUCCESS(prefix + summary + "."))

    # --- one row each ---------------------------------------------------------------------------

    def _product(self, product: Product, report: dict) -> None:
        assert product.is_demo
        label = f"product {product.sku} ({product.name})"
        variant_ids = list(product.variants.values_list("pk", flat=True))
        referenced = (
            OrderItem.objects.filter(product=product).exists()
            or OrderItem.objects.filter(variant_id__in=variant_ids).exists()
            or product.reviews.exists()
        )
        if not referenced and self._try_delete(lambda: self._delete_product(product, variant_ids)):
            report["deleted"].append(label)
            return
        if product.is_deleted and not product.is_active and not product.is_published:
            return  # archived by an earlier run
        Product.all_objects.filter(pk=product.pk).update(
            is_deleted=True,
            deleted_at=product.deleted_at or timezone.now(),
            is_active=False,
            is_published=False,
            is_featured=False,
        )
        product.variants.update(is_active=False)
        Inventory.objects.filter(variant_id__in=variant_ids).update(is_active=False)
        report["archived"].append(label + (": has orders or reviews" if referenced else ": still referenced"))

    def _delete_product(self, product: Product, variant_ids: list[int]) -> None:
        inventory = Inventory.objects.filter(variant_id__in=variant_ids)
        StockMovement.objects.filter(inventory__in=inventory).delete()
        inventory.delete()
        product.hard_delete()

    def _store(self, store: Store, report: dict) -> None:
        assert store.is_demo
        label = f"store {store.code} ({store.name})"
        real_stock = Inventory.objects.filter(store=store, variant__product__is_demo=False).exists()
        referenced = Order.objects.filter(store=store).exists() or OrderShipment.objects.filter(store=store).exists()
        if not (referenced or real_stock) and self._try_delete(lambda: self._delete_store(store)):
            report["deleted"].append(label)
            return
        if store.is_deleted and not store.is_active and not store.accepts_orders:
            return
        Store.all_objects.filter(pk=store.pk).update(
            is_deleted=True, deleted_at=store.deleted_at or timezone.now(), is_active=False, accepts_orders=False
        )
        reason = "holds stock of real products" if real_stock else ("has orders" if referenced else "still referenced")
        report["archived"].append(f"{label}: {reason}")

    def _delete_store(self, store: Store) -> None:
        inventory = Inventory.objects.filter(store=store)
        StockMovement.objects.filter(inventory__in=inventory).delete()
        inventory.delete()
        store.hard_delete()

    def _brand(self, brand: Brand, report: dict) -> None:
        assert brand.is_demo
        label = f"brand {brand.name}"
        products = Product.all_objects.filter(brand=brand)
        if real := list(products.filter(is_demo=False).values_list("sku", flat=True)[:5]):
            report["kept"].append(f"{label}: used by real product(s) {', '.join(real)}")
            return
        if not products.exists() and self._try_delete(brand.hard_delete):
            report["deleted"].append(label)
            return
        if brand.is_deleted and not brand.is_active:
            return
        Brand.all_objects.filter(pk=brand.pk).update(
            is_deleted=True, deleted_at=brand.deleted_at or timezone.now(), is_active=False
        )
        report["archived"].append(f"{label}: archived demo products still use it")

    @staticmethod
    def _try_delete(delete) -> bool:
        """Run a hard delete in a savepoint; False (and nothing deleted) when something still protects the row."""
        try:
            with transaction.atomic():
                delete()
        except (ProtectedError, RestrictedError):
            return False
        return True
