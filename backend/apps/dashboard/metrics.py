"""Numbers for the dashboard and the analytics page. Everything is read from the database at
request time; nothing is estimated, sampled or made up.

Definitions (also shown in the UI and docs/API.md):
- **Orders** are counted by the day they were placed (local time, Asia/Kolkata by default).
- **Revenue** is the total of orders that were paid (online payment captured, or cash collected
  at delivery), whatever happened later. **Refunded** is money paid back (processed refunds),
  counted on the day the refund was processed. **Net revenue** = revenue − refunded.
- **Sales by category / product** use order lines after automatic offers (coupons are not split
  per line there), for orders that were not cancelled and not still waiting for payment.
- **On time** = delivered no later than the end of the delivery window promised at checkout.

Portability: days, weeks and months are grouped in Python from a narrow `values_list`, not with
database date functions, because time-zone aware truncation needs time-zone tables on MySQL
(often missing on shared hosting). Periods are limited to 366 days.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, F, Max, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.money import ZERO, q
from apps.delivery.models import DeliveryAssignment, DeliveryPartner
from apps.inventory.models import Inventory
from apps.orders.models import Order, OrderItem, OrderShipment, OrderStatus, PaymentStatus, ReturnRequest
from apps.payments.models import Refund
from apps.stores.models import Store

from .scope import local_day_start, scope_orders

S = OrderStatus
PAID = (PaymentStatus.PAID, PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.REFUNDED)
# Not a sale (yet): cancelled orders, and online orders still waiting for payment.
NOT_A_SALE = (S.CANCELLED, S.PENDING)
IN_PREPARATION = (S.CONFIRMED, S.PROCESSING, S.PACKED)
ON_THE_WAY = (S.ASSIGNED, S.PICKED_UP, S.OUT_FOR_DELIVERY)
OPEN_RETURNS = ReturnRequest.OPEN_STATUSES
ONLINE = (DeliveryPartner.Status.AVAILABLE, DeliveryPartner.Status.BUSY)


def _money(value) -> str:
    return str(q(value or ZERO))


def _local_date(moment: datetime) -> date:
    return timezone.localtime(moment).date()


def _rate(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


# --- Periods -------------------------------------------------------------------------------------


def bucket_start(day: date, period: str) -> date:
    if period == "week":
        return day - timedelta(days=day.weekday())  # Monday
    if period == "month":
        return day.replace(day=1)
    return day


def bucket_label(start: date, period: str) -> str:
    if period == "month":
        return start.strftime("%b %Y")
    if period == "week":
        return f"Week of {start.day} {start.strftime('%b')}"
    return f"{start.day} {start.strftime('%b')}"


def buckets(first: date, last: date, period: str) -> list[date]:
    """Every period that overlaps [first, last], including those with no orders."""
    result, current = [], bucket_start(first, period)
    while current <= last:
        result.append(current)
        if period == "month":
            current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            current += timedelta(days=7 if period == "week" else 1)
    return result


def order_series(orders, first: date, last: date, period: str, refunds=None) -> list[dict]:
    rows = {
        start: {"orders": 0, "paid_orders": 0, "revenue": ZERO, "cancelled": 0, "delivered": 0, "refunded": ZERO}
        for start in buckets(first, last, period)
    }
    for created_at, total, status, payment_status in orders.values_list(
        "created_at", "grand_total", "status", "payment_status"
    ).iterator():
        row = rows.get(bucket_start(_local_date(created_at), period))
        if row is None:
            continue
        row["orders"] += 1
        if payment_status in PAID:
            row["paid_orders"] += 1
            row["revenue"] += total
        if status == S.CANCELLED:
            row["cancelled"] += 1
        elif status in (S.DELIVERED, S.RETURN_REQUESTED, S.RETURNED):
            row["delivered"] += 1
    if refunds is not None:
        for processed_at, amount in refunds.values_list("processed_at", "amount").iterator():
            row = rows.get(bucket_start(_local_date(processed_at), period))
            if row is not None:
                row["refunded"] += amount
    return [
        {
            "start": start.isoformat(),
            "label": bucket_label(start, period),
            "orders": row["orders"],
            "paid_orders": row["paid_orders"],
            "revenue": _money(row["revenue"]),
            "refunded": _money(row["refunded"]),
            "net_revenue": _money(row["revenue"] - row["refunded"]),
            "average_order_value": _money(row["revenue"] / row["paid_orders"]) if row["paid_orders"] else None,
            "cancelled": row["cancelled"],
            "delivered": row["delivered"],
        }
        for start, row in rows.items()
    ]


# --- Shared pieces ---------------------------------------------------------------------------------


def _refunds(store_ids):
    return scope_orders(Refund.objects.all(), store_ids, "payment__order__store_id")


def _returns(store_ids):
    return scope_orders(ReturnRequest.objects.all(), store_ids, "order__store_id")


def _low_stock(store_ids):
    rows = Inventory.objects.filter(is_active=True, store__is_deleted=False, variant__is_active=True)
    rows = scope_orders(rows, store_ids)
    return rows.filter(available_quantity__lte=F("low_stock_threshold"))


def _revenue(orders) -> Decimal:
    return orders.filter(payment_status__in=PAID).aggregate(total=Sum("grand_total"))["total"] or ZERO


# --- Dashboard -------------------------------------------------------------------------------------


def dashboard_summary(store_ids, *, is_admin: bool) -> dict:
    now = timezone.now()
    today = timezone.localdate()
    today_start = local_day_start(today)
    month_start = local_day_start(today.replace(day=1))
    trend_first = today - timedelta(days=13)

    orders = scope_orders(Order.objects.all(), store_ids)
    by_status = dict(orders.values_list("status").annotate(n=Count("id")))
    count = lambda *statuses: sum(by_status.get(s, 0) for s in statuses)  # noqa: E731
    todays = orders.filter(created_at__gte=today_start)
    refunds, returns = _refunds(store_ids), _returns(store_ids)
    processed = refunds.filter(status=Refund.Status.PROCESSED)
    pending_refunds = refunds.filter(status=Refund.Status.PENDING)

    partners = DeliveryPartner.objects.filter(is_active=True, is_verified=True)
    stores = Store.objects.all()
    if store_ids is not None:
        partners = partners.filter(home_store_id__in=store_ids)
        stores = stores.filter(pk__in=store_ids)
    low_stock = _low_stock(store_ids)
    failed_deliveries = by_status.get(S.DELIVERY_FAILED, 0)
    waiting_for_rider = (
        scope_orders(OrderShipment.objects.all(), store_ids)
        .filter(order__status__in=(S.PACKED, S.DELIVERY_FAILED), status__in=("pending", "failed"))
        .count()
    )
    open_returns = returns.filter(status__in=OPEN_RETURNS).count()
    failed_refunds = refunds.filter(status=Refund.Status.FAILED).count()
    cash_with_riders = scope_orders(
        DeliveryAssignment.objects.filter(
            cod_method=DeliveryAssignment.CodMethod.CASH,
            cod_collected_at__isnull=False,
            cod_handed_over_at__isnull=True,
        ),
        store_ids,
        "shipment__store_id",
    ).aggregate(total=Sum("cod_collected_amount"), n=Count("id"))

    attention = [
        ("orders_to_prepare", "Orders to prepare", count(*IN_PREPARATION), "/admin/orders?status=confirmed,processing"),
        ("waiting_for_rider", "Packed shipments without a rider", waiting_for_rider, "/admin/delivery?tab=shipments"),
        ("failed_deliveries", "Failed deliveries to send out again", failed_deliveries,
         "/admin/orders?status=delivery_failed"),
        ("open_returns", "Returns to decide or receive", open_returns, "/admin/returns?status=open"),
        ("pending_refunds", "Refunds waiting", pending_refunds.count(), "/admin/refunds?status=pending"),
        ("failed_refunds", "Refunds that failed", failed_refunds, "/admin/refunds?status=failed"),
        ("low_stock", "Items low on stock", low_stock.count(), "/admin/inventory?stock=low"),
        ("cash_with_riders", "Cash deliveries to collect from riders", cash_with_riders["n"],
         "/admin/delivery?tab=cod"),
    ]  # fmt: skip

    data = {
        "generated_at": now,
        "orders": {
            "total": sum(by_status.values()),
            "today": todays.count(),
            "pending": by_status.get(S.PENDING, 0),
            "processing": count(*IN_PREPARATION),
            "on_the_way": count(*ON_THE_WAY),
            "delivered": count(S.DELIVERED, S.RETURN_REQUESTED, S.RETURNED),
            "cancelled": by_status.get(S.CANCELLED, 0),
            "delivery_failed": failed_deliveries,
            "by_status": {status: by_status.get(status, 0) for status in S.values},
        },
        "revenue": {
            "total": _money(_revenue(orders)),
            "today": _money(_revenue(todays)),
            "this_month": _money(_revenue(orders.filter(created_at__gte=month_start))),
            "refunded_total": _money(processed.aggregate(t=Sum("amount"))["t"]),
        },
        "returns": {"total": returns.count(), "open": open_returns},
        "refunds": {
            "pending": pending_refunds.count(),
            "pending_amount": _money(pending_refunds.aggregate(t=Sum("amount"))["t"]),
            "failed": failed_refunds,
            "processed": processed.count(),
            "processed_amount": _money(processed.aggregate(t=Sum("amount"))["t"]),
        },
        "inventory": {
            "low_stock": low_stock.count(),
            "out_of_stock": low_stock.filter(available_quantity=0).count(),
        },
        "delivery": {
            "partners": partners.count(),
            "partners_online": partners.filter(status__in=ONLINE).count(),
            "partners_available": partners.filter(status=DeliveryPartner.Status.AVAILABLE).count(),
            "waiting_for_rider": waiting_for_rider,
            "cash_with_riders": _money(cash_with_riders["total"]),
        },
        "stores": {
            "active": stores.filter(is_active=True, kind__in=Store.FULFILLMENT_KINDS).count(),
            "accepting_orders": stores.filter(
                is_active=True, accepts_orders=True, kind__in=Store.FULFILLMENT_KINDS
            ).count(),
            "warehouses": stores.filter(is_active=True, kind=Store.Kind.WAREHOUSE).count(),
        },
        # Shop-wide figures, not tied to a store: shown to administrators only.
        "customers": None,
        "products": None,
        "trend": order_series(
            orders.filter(created_at__gte=local_day_start(trend_first)),
            trend_first,
            today,
            "day",
            processed.filter(processed_at__gte=local_day_start(trend_first)),
        ),
        "attention": [
            {"code": code, "label": label, "count": n, "link": link} for code, label, n, link in attention if n
        ],
    }
    if is_admin:
        User = get_user_model()
        customers = User.objects.filter(role=User.Role.CUSTOMER)
        products = Product.objects.all()
        data["customers"] = {
            "total": customers.count(),
            "active": customers.filter(is_active=True).count(),
            "new_this_month": customers.filter(date_joined__gte=month_start).count(),
        }
        data["products"] = {
            "total": products.count(),
            "published": products.filter(is_active=True, is_published=True).count(),
            "unpublished": products.filter(is_published=False).count(),
        }
    return data


# --- Analytics -------------------------------------------------------------------------------------


def _line_sales(store_ids, start, end):
    items = OrderItem.objects.filter(order__created_at__gte=start, order__created_at__lt=end).exclude(
        order__status__in=NOT_A_SALE
    )
    return scope_orders(items, store_ids, "order__store_id")


def _product_sales(store_ids, start, end) -> tuple[list[dict], list[dict]]:
    rows = (
        _line_sales(store_ids, start, end)
        .values("product_id")
        .annotate(
            name=Max("product_name"),
            units=Sum("quantity"),
            sales=Sum(F("line_total") - F("offer_discount")),
            orders=Count("order_id", distinct=True),
        )
        .order_by("-sales", "name")[:10]
    )
    top = [
        {"product_id": r["product_id"], "name": r["name"], "units": r["units"], "orders": r["orders"],
         "sales": _money(r["sales"])}
        for r in rows
    ]  # fmt: skip

    sold = Q(order_items__order__created_at__gte=start, order_items__order__created_at__lt=end) & ~Q(
        order_items__order__status__in=NOT_A_SALE
    )
    if store_ids is not None:
        sold &= Q(order_items__order__store_id__in=store_ids)
    slow = (
        Product.objects.filter(is_active=True, is_published=True)
        .annotate(units=Coalesce(Sum("order_items__quantity", filter=sold), 0))
        .order_by("units", "name")[:10]
    )
    low = [{"product_id": p.pk, "name": p.name, "slug": p.slug, "units": p.units} for p in slow]
    return top, low


def _category_sales(store_ids, start, end) -> list[dict]:
    rows = (
        _line_sales(store_ids, start, end)
        .values("product__category__name")
        .annotate(units=Sum("quantity"), sales=Sum(F("line_total") - F("offer_discount")))
        .order_by("-sales")
    )
    total = sum((r["sales"] or ZERO for r in rows), ZERO)
    return [
        {
            "category": r["product__category__name"] or "Products no longer in the catalogue",
            "units": r["units"],
            "sales": _money(r["sales"]),
            "share": _rate(int((r["sales"] or ZERO) * 100), int(total * 100)),
        }
        for r in rows
    ]


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _delivery_performance(store_ids, start, end) -> dict:
    shipments = scope_orders(
        OrderShipment.objects.filter(delivered_at__gte=start, delivered_at__lt=end), store_ids
    ).values_list(
        "delivery_type", "delivered_at", "window_end", "estimated_delivery_at", "eta_minutes", "delivery_attempts"
    )
    groups: dict[str, dict] = defaultdict(
        lambda: {"delivered": 0, "measured": 0, "on_time": 0, "promised": [], "actual": []}
    )
    first_attempt = 0
    for kind, delivered_at, window_end, promised_at, eta, attempts in shipments.iterator():
        first_attempt += attempts <= 1
        for key in ("all", kind):
            group = groups[key]
            group["delivered"] += 1
            if window_end is None or promised_at is None:
                continue  # placed before delivery estimates existed
            group["measured"] += 1
            group["on_time"] += delivered_at <= window_end
            if kind == "fast" and eta:
                promise_made_at = promised_at - timedelta(minutes=eta)
                group["promised"].append(eta)
                group["actual"].append(max((delivered_at - promise_made_at).total_seconds() / 60, 0))

    def summary(key: str) -> dict:
        group = groups[key]
        return {
            "delivered": group["delivered"],
            "with_estimate": group["measured"],
            "on_time": group["on_time"],
            "on_time_rate": _rate(group["on_time"], group["measured"]),
            "average_promised_minutes": _average(group["promised"]),
            "average_actual_minutes": _average(group["actual"]),
        }

    jobs = scope_orders(
        DeliveryAssignment.objects.filter(kind=DeliveryAssignment.Kind.DELIVERY), store_ids, "shipment__store_id"
    )
    failed = jobs.filter(status=DeliveryAssignment.Status.FAILED, failed_at__gte=start, failed_at__lt=end)
    reasons = Counter(failed.values_list("failure_code", flat=True))
    labels = dict(DeliveryAssignment.FailureCode.choices)
    total = groups["all"]["delivered"]
    return {
        "all": summary("all"),
        "fast": summary("fast"),
        "standard": summary("standard"),
        "first_attempt_rate": _rate(first_attempt, total),
        "failed_attempts": failed.count(),
        "failure_reasons": [
            {"code": code, "label": labels.get(code, "Other"), "count": n} for code, n in reasons.most_common()
        ],
        "delivered_by_partners": jobs.filter(
            status=DeliveryAssignment.Status.DELIVERED, delivered_at__gte=start, delivered_at__lt=end
        ).count(),
        "fast_window_minutes": settings.FAST_WINDOW_MINUTES,
    }


def analytics(store_ids, first: date, last: date, start: datetime, end: datetime, period: str) -> dict:
    orders = scope_orders(Order.objects.filter(created_at__gte=start, created_at__lt=end), store_ids)
    refunds = _refunds(store_ids)
    processed = refunds.filter(status=Refund.Status.PROCESSED, processed_at__gte=start, processed_at__lt=end)
    series = order_series(orders, first, last, period, processed)

    total = orders.count()
    paid = orders.filter(payment_status__in=PAID)
    paid_count = paid.count()
    revenue = _revenue(orders)
    refunded = processed.aggregate(t=Sum("amount"))["t"] or ZERO
    cancelled = orders.filter(status=S.CANCELLED)
    cancelled_count = cancelled.count()
    reasons = (
        cancelled.exclude(cancellation_reason="")
        .values("cancellation_reason")
        .annotate(n=Count("id"))
        .order_by("-n", "cancellation_reason")[:5]
    )

    returns = _returns(store_ids).filter(created_at__gte=start, created_at__lt=end)
    return_reasons = returns.values("reason").annotate(n=Count("id")).order_by("-n")
    reason_labels = dict(ReturnRequest.Reason.choices)
    created_refunds = refunds.filter(created_at__gte=start, created_at__lt=end)
    delivered_in_period = orders.filter(status__in=(S.DELIVERED, S.RETURN_REQUESTED, S.RETURNED)).count()
    top, low = _product_sales(store_ids, start, end)

    return {
        "period": {
            "from": first.isoformat(),
            "to": last.isoformat(),
            "group_by": period,
            "days": (last - first).days + 1,
        },
        "totals": {
            "orders": total,
            "paid_orders": paid_count,
            "revenue": _money(revenue),
            "refunded": _money(refunded),
            "net_revenue": _money(revenue - refunded),
            "average_order_value": _money(revenue / paid_count) if paid_count else None,
            "delivered": delivered_in_period,
            "cancelled": cancelled_count,
            "cancellation_rate": _rate(cancelled_count, total),
            "payment_methods": dict(orders.values_list("payment_method").annotate(n=Count("id"))),
        },
        "series": series,
        "category_sales": _category_sales(store_ids, start, end),
        "top_products": top,
        "low_performing_products": low,
        "cancellations": {
            "count": cancelled_count,
            "rate": _rate(cancelled_count, total),
            "value": _money(cancelled.aggregate(t=Sum("grand_total"))["t"]),
            "reasons": [{"reason": r["cancellation_reason"], "count": r["n"]} for r in reasons],
        },
        "returns": {
            "count": returns.count(),
            "rate": _rate(returns.count(), delivered_in_period),
            "open": returns.filter(status__in=OPEN_RETURNS).count(),
            "received": returns.filter(status=ReturnRequest.Status.RECEIVED).count(),
            "rejected": returns.filter(status=ReturnRequest.Status.REJECTED).count(),
            "refund_value": _money(
                returns.filter(status=ReturnRequest.Status.RECEIVED).aggregate(t=Sum("refund_amount"))["t"]
            ),
            "reasons": [
                {"code": r["reason"], "label": reason_labels.get(r["reason"], r["reason"]), "count": r["n"]}
                for r in return_reasons
            ],
        },
        "refunds": {
            "requested": created_refunds.count(),
            "requested_amount": _money(created_refunds.aggregate(t=Sum("amount"))["t"]),
            "processed": processed.count(),
            "processed_amount": _money(refunded),
            "pending": created_refunds.filter(status=Refund.Status.PENDING).count(),
            "failed": created_refunds.filter(status=Refund.Status.FAILED).count(),
        },
        "delivery": _delivery_performance(store_ids, start, end),
    }
