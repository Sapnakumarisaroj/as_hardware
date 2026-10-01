"""Keep the search index in step with the catalogue (Phase 13).

A product, variant or specification that changes queues one refresh job for its product
(deduplicated); a brand or category rename queues an incremental rebuild (unchanged products are
skipped by their text fingerprint). Nothing is queued while semantic search is off, and a failure
to queue never blocks saving a product.
"""

import logging

from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.core.jobs import enqueue

from .models import Brand, Category, Product, ProductSpecification, ProductVariant

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return settings.SEMANTIC_EMBEDDER in ("hashing", "sentence_transformers")


def _queue_product(product_id) -> None:
    if not _enabled() or not product_id:
        return
    try:
        enqueue("catalog.sync_embedding", {"product_id": product_id}, dedupe_key=f"embed:{product_id}")
    except Exception:  # noqa: BLE001 — search freshness must never block a catalogue edit
        logger.warning("Could not queue the search index refresh for product %s", product_id, exc_info=True)


def _queue_rebuild() -> None:
    if not _enabled():
        return
    try:
        enqueue("catalog.rebuild_search_index", {"force": False}, dedupe_key="embed:all")
    except Exception:  # noqa: BLE001
        logger.warning("Could not queue the search index rebuild", exc_info=True)


@receiver([post_save, post_delete], sender=Product)
def product_changed(sender, instance, raw=False, **kwargs):
    if not raw:
        _queue_product(instance.pk)


@receiver([post_save, post_delete], sender=ProductVariant)
@receiver([post_save, post_delete], sender=ProductSpecification)
def child_changed(sender, instance, raw=False, **kwargs):
    if not raw:
        _queue_product(instance.product_id)


@receiver(post_save, sender=Brand)
@receiver(post_save, sender=Category)
def naming_changed(sender, instance, created=False, raw=False, **kwargs):
    if not raw and not created:
        _queue_rebuild()
