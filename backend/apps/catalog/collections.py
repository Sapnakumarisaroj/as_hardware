"""Curated product lists (Phase 15): which products a `Collection` shows right now.

Every list is built from the same annotated queryset as the shop's listing
(`selectors.product_queryset`), so only published, active products appear, with live prices,
stock and delivery flags. Automatic lists use real data only: best sellers come from orders,
new launches from launch dates, bulk buying from products that have price tiers. A list with
nothing in it is left out by the API (the shop front never shows an empty section).
"""

from datetime import datetime, time, timedelta

from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from . import selectors
from .models import Collection, Product
from .tree import descendant_ids, parent_map


def live_collections(now: datetime | None = None) -> QuerySet[Collection]:
    now = now or timezone.now()
    return (
        Collection.objects.filter(is_active=True)
        .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .prefetch_related("categories")
        .order_by("sort_order", "name")
    )


def _in_categories(qs: QuerySet[Product], collection: Collection) -> QuerySet[Product]:
    category_ids = [c.id for c in collection.categories.all()]
    if not category_ids:
        return qs
    parents = parent_map()
    scope = set().union(*(descendant_ids(cid, parents) for cid in category_ids))
    return qs.filter(Q(category_id__in=scope) | Q(subcategory_id__in=scope))


def collection_products(collection: Collection, *, now: datetime | None = None) -> list[Product]:
    """The products of a collection, best first, at most `max_items`."""
    now = now or timezone.now()
    qs = _in_categories(selectors.product_queryset(), collection)
    limit = collection.max_items
    rule = collection.rule
    if rule == Collection.Rule.MANUAL:
        chosen = collection.items.order_by("sort_order", "id").values_list("product_id", flat=True)
        order = {pid: pos for pos, pid in enumerate(chosen)}
        rows = list(qs.filter(pk__in=list(order)))
        rows.sort(key=lambda p: order[p.pk])
        return rows[:limit]
    if rule == Collection.Rule.BEST_SELLERS:
        from apps.orders.models import OrderItem

        since = now - timedelta(days=collection.window_days)
        sold = dict(
            OrderItem.objects.filter(
                order__created_at__gte=since, order__status__in=selectors.SOLD_STATUSES, product__isnull=False
            )
            .values_list("product_id")
            .annotate(units=Sum("quantity"))
        )
        rows = [p for p in qs.filter(pk__in=[pid for pid, units in sold.items() if units])]
        rows.sort(key=lambda p: (-sold[p.pk], p.name, p.pk))
        return rows[:limit]
    if rule == Collection.Rule.NEW_LAUNCHES:
        today = timezone.localdate(now)
        cutoff = today - timedelta(days=collection.window_days)
        cutoff_at = timezone.make_aware(datetime.combine(cutoff, time.min), timezone.get_current_timezone())
        launched = Q(launch_date__gte=cutoff, launch_date__lte=today)
        added = Q(launch_date__isnull=True, created_at__gte=cutoff_at)  # no launch date: when it was added
        rows = list(qs.filter(launched | added))
        rows.sort(key=lambda p: (p.launch_date or timezone.localdate(p.created_at), p.created_at, p.pk), reverse=True)
        return rows[:limit]
    if rule == Collection.Rule.BULK_PRICING:
        with_tiers = qs.filter(variants__is_active=True, variants__price_tiers__isnull=False).distinct()
        return list(with_tiers.order_by("-sold_count", "name", "id")[:limit])
    return []
