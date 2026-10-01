"""Background jobs that keep the semantic search index current (Phase 13)."""

import logging

from apps.core.jobs import job

logger = logging.getLogger(__name__)


@job("catalog.sync_embedding")
def sync_embedding(product_id: int) -> None:
    from .semantic import index

    index.sync_product(product_id)


@job("catalog.rebuild_search_index")
def rebuild_search_index(force: bool = False) -> None:
    from .semantic import index

    result = index.sync_products(force=force)
    logger.info("Search index rebuilt: %s", result.as_dict())
