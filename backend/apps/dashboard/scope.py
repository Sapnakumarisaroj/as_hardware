"""Which stores a dashboard user may see.

Admins see everything and may narrow to one store with `?store=<id>`. Store managers see only
the stores assigned to them; asking for another store is "not found", never someone else's data.
"""

from datetime import date, datetime, time, timedelta

from django.utils import timezone

from apps.core.exceptions import NotFoundError, ServiceError
from apps.core.permissions import is_admin, managed_store_ids

MAX_RANGE_DAYS = 366


def store_ids_for(request) -> list[int] | None:
    """Store ids to filter by, or None for "all stores" (admins without a store filter)."""
    allowed = managed_store_ids(request.user)  # None = all
    wanted = (request.query_params.get("store") or "").strip()
    if not wanted:
        return allowed
    if not wanted.isdigit():
        raise NotFoundError("Store not found.")
    store_id = int(wanted)
    if allowed is not None and store_id not in allowed:
        raise NotFoundError("Store not found.")
    return [store_id]


def scope_orders(queryset, store_ids, field: str = "store_id"):
    return queryset if store_ids is None else queryset.filter(**{f"{field}__in": store_ids})


def may_manage_store(user, store_id) -> bool:
    allowed = managed_store_ids(user)
    return is_admin(user) or (allowed is not None and store_id in allowed)


def local_day_start(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())


def parse_day(value: str | None, *, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ServiceError(f"'{name}' must be a date like 2026-09-28.", code="invalid_date") from None


def date_range(request, *, default_days: int = 30) -> tuple[date, date, datetime, datetime]:
    """(first day, last day, start, end) from `?from=&to=` in local time; `end` is exclusive."""
    today = timezone.localdate()
    last = parse_day(request.query_params.get("to"), name="to") or today
    first = parse_day(request.query_params.get("from"), name="from") or last - timedelta(days=default_days - 1)
    if first > last:
        raise ServiceError("'from' must not be after 'to'.", code="invalid_date")
    if (last - first).days >= MAX_RANGE_DAYS:
        raise ServiceError(f"Choose a period of at most {MAX_RANGE_DAYS} days.", code="range_too_long")
    return first, last, local_day_start(first), local_day_start(last + timedelta(days=1))
