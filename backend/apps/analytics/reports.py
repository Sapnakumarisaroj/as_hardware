"""Business reports (Phase 24): a fixed list of read-only reports over the shop's own data.

Each report is a function of a `Scope` (which stores, which days) and returns the same shape:

    {"key", "title", "description", "period", "kpis": [...], "series": [...] | None,
     "tables": [{"key", "title", "columns": [...], "rows": [...], "chart": {...} | None}], "notes": [...]}

so the dashboard, the CSV download and the business assistant all read one structure. Every number
comes from rows in the database at request time; nothing is estimated or sampled. Definitions are
those of the Phase 11 analytics (`apps.dashboard.metrics`):

- Revenue = grand total of paid orders placed in the period (online captured or cash collected).
- Sales (products, categories, brands) = order lines after automatic offers, for orders that are not
  cancelled and not waiting for payment.
- Store managers only ever see their own stores (`store_ids`); administrators see all or one store.

Profit: each order line keeps the variant's purchase cost when it was placed (`OrderItem.unit_cost`,
null when unknown). The margin report computes gross profit only from lines with a cost and always
says how much of the revenue that covers; lines without a cost are left out, never estimated. It also
shows MRP vs selling value and promotions.

Portability: grouping by day/hour/weekday is done in Python from narrow `values_list` queries, as
in the Phase 11 metrics (no database date functions, which MySQL on shared hosting may lack).
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from django.db.models import Count, F, Max, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.catalog.models import Category, Product
from apps.core.money import ZERO
from apps.dashboard.metrics import NOT_A_SALE, PAID, _delivery_performance, order_series
from apps.dashboard.scope import scope_orders
from apps.delivery.models import DeliveryAssignment
from apps.inventory.models import Inventory, StockMovement
from apps.offers.models import CouponRedemption, OfferRedemption
from apps.orders.models import Order, OrderItem, OrderShipment, OrderStatus, ReturnItem, ReturnRequest
from apps.payments.models import Refund
from apps.stores.models import Store

S = OrderStatus
MONEY, COUNT, PERCENT, MINUTES, TEXT, NUMBER = "money", "count", "percent", "minutes", "text", "number"
TABLE_LIMIT = 100
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class Scope:
    store_ids: list[int] | None  # None = every store (administrators only)
    first: date
    last: date
    start: datetime  # local midnight of `first`
    end: datetime  # exclusive
    period: str = "day"  # day | week | month (series grouping)

    @property
    def days(self) -> int:
        return (self.last - self.first).days + 1


# --- Small helpers -----------------------------------------------------------------------------------


def money(value) -> str:
    return str((value or ZERO).quantize(Decimal("0.01")))


def rate(part, whole) -> float | None:
    return round(float(part) * 100 / float(whole), 1) if whole else None


def kpi(key: str, label: str, value, fmt: str = COUNT, hint: str = "") -> dict:
    row = {"key": key, "label": label, "value": value, "format": fmt}
    if hint:
        row["hint"] = hint
    return row


def col(key: str, label: str, fmt: str = TEXT) -> dict:
    return {"key": key, "label": label, "format": fmt}


def table(key: str, title: str, columns: list[dict], rows: list[dict], chart: dict | None = None) -> dict:
    return {"key": key, "title": title, "columns": columns, "rows": rows[:TABLE_LIMIT], "chart": chart}


def bar(label: str, value: str) -> dict:
    return {"type": "bar", "label": label, "value": value}


def share(label: str, value: str) -> dict:
    return {"type": "share", "label": label, "value": value}


def mask_email(email: str) -> str:
    name, _, domain = (email or "").partition("@")
    return f"{name[:2]}•••@{domain}" if domain else ""


def orders_in(scope: Scope):
    return scope_orders(Order.objects.filter(created_at__gte=scope.start, created_at__lt=scope.end), scope.store_ids)


def sales_lines(scope: Scope):
    lines = OrderItem.objects.filter(order__created_at__gte=scope.start, order__created_at__lt=scope.end).exclude(
        order__status__in=NOT_A_SALE
    )
    return scope_orders(lines, scope.store_ids, "order__store_id")


def paid(orders):
    return orders.filter(payment_status__in=PAID)


def total(queryset, field: str) -> Decimal:
    return queryset.aggregate(t=Sum(field))["t"] or ZERO


LINE_SALES = F("line_total") - F("offer_discount")


def _top_categories() -> dict[int, tuple[str, str]]:
    """Category id → (top-level name, own name), archived ones included (history keeps them)."""
    rows = {c.pk: c for c in Category.all_objects.only("id", "name", "parent_id")}

    def top(category):
        seen = set()
        while category.parent_id and category.parent_id in rows and category.pk not in seen:
            seen.add(category.pk)
            category = rows[category.parent_id]
        return category.name

    return {pk: (top(c), c.name) for pk, c in rows.items()}


def report_frame(key: str, scope: Scope) -> dict:
    spec = REPORTS[key]
    return {
        "key": key,
        "title": spec.title,
        "description": spec.description,
        "period": {
            "from": scope.first.isoformat(),
            "to": scope.last.isoformat(),
            "days": scope.days,
            "group_by": scope.period,
        },
        "kpis": [],
        "series": None,
        "tables": [],
        "notes": [],
    }


# --- Reports -------------------------------------------------------------------------------------------


def sales_report(scope: Scope) -> dict:
    out = report_frame("sales", scope)
    orders = orders_in(scope)
    paid_orders = paid(orders)
    paid_count = paid_orders.count()
    revenue = total(paid_orders, "grand_total")
    processed = scope_orders(
        Refund.objects.filter(
            status=Refund.Status.PROCESSED, processed_at__gte=scope.start, processed_at__lt=scope.end
        ),
        scope.store_ids,
        "payment__order__store_id",
    )
    refunded = total(processed, "amount")
    out["kpis"] = [
        kpi("revenue", "Revenue", money(revenue), MONEY, "Paid orders placed in the period"),
        kpi("net_revenue", "Net revenue", money(revenue - refunded), MONEY, "Revenue minus refunds paid out"),
        kpi("refunded", "Refunded", money(refunded), MONEY),
        kpi("paid_orders", "Paid orders", paid_count),
        kpi("average_order_value", "Average order value", money(revenue / paid_count) if paid_count else None, MONEY),
        kpi(
            "discounts",
            "Discounts given",
            money(total(paid_orders, "discount_total") + total(paid_orders, "credit_discount")),
            MONEY,
            "Offers, coupons and credits on paid orders",
        ),
        kpi("delivery_fees", "Delivery fees", money(total(paid_orders, "delivery_fee")), MONEY),
        kpi("gst", "GST collected", money(total(paid_orders, "tax_total")), MONEY, "Contained in the amounts paid"),
    ]
    out["series"] = order_series(orders, scope.first, scope.last, scope.period, processed)

    methods = (
        paid_orders.values("payment_method").annotate(n=Count("id"), revenue=Sum("grand_total")).order_by("-revenue")
    )
    out["tables"].append(
        table(
            "payment_methods",
            "Revenue by payment method",
            [
                col("method", "Payment method"),
                col("orders", "Paid orders", COUNT),
                col("revenue", "Revenue", MONEY),
                col("share", "Share", PERCENT),
            ],
            [
                {
                    "method": "Cash on delivery" if m["payment_method"] == "cod" else "Online",
                    "orders": m["n"],
                    "revenue": money(m["revenue"]),
                    "share": rate(m["revenue"], revenue),
                }
                for m in methods
            ],
            share("method", "revenue"),
        )
    )
    weekday, hours = defaultdict(lambda: [0, ZERO]), Counter()
    for created, amount in paid_orders.values_list("created_at", "grand_total").iterator():
        local = timezone.localtime(created)
        weekday[local.weekday()][0] += 1
        weekday[local.weekday()][1] += amount
        hours[local.hour] += 1
    out["tables"].append(
        table(
            "weekdays",
            "Paid orders by day of the week",
            [col("day", "Day"), col("orders", "Paid orders", COUNT), col("revenue", "Revenue", MONEY)],
            [{"day": WEEKDAYS[d], "orders": weekday[d][0], "revenue": money(weekday[d][1])} for d in range(7)],
            bar("day", "revenue"),
        )
    )
    out["tables"].append(
        table(
            "hours",
            "Paid orders by hour of the day",
            [col("hour", "Hour"), col("orders", "Paid orders", COUNT)],
            [{"hour": f"{h:02d}:00", "orders": hours[h]} for h in range(24) if hours[h]],
            bar("hour", "orders"),
        )
    )
    return out


def orders_report(scope: Scope) -> dict:
    out = report_frame("orders", scope)
    orders = orders_in(scope)
    count = orders.count()
    cancelled = orders.filter(status=S.CANCELLED).count()
    delivered = orders.filter(status__in=(S.DELIVERED, S.RETURN_REQUESTED, S.RETURNED)).count()
    in_progress = orders.exclude(
        status__in=(S.CANCELLED, S.PENDING, S.DELIVERED, S.RETURN_REQUESTED, S.RETURNED)
    ).count()
    units = (
        scope_orders(
            OrderItem.objects.filter(order__created_at__gte=scope.start, order__created_at__lt=scope.end),
            scope.store_ids,
            "order__store_id",
        ).aggregate(u=Sum("quantity"))["u"]
        or 0
    )
    out["kpis"] = [
        kpi("orders", "Orders placed", count),
        kpi("delivered", "Delivered", delivered),
        kpi("in_progress", "In progress", in_progress),
        kpi("waiting_payment", "Waiting for payment", orders.filter(status=S.PENDING).count()),
        kpi("cancelled", "Cancelled", cancelled),
        kpi("cancellation_rate", "Cancellation rate", rate(cancelled, count), PERCENT),
        kpi("units_per_order", "Units per order", round(units / count, 1) if count else None, NUMBER),
    ]
    out["series"] = order_series(orders, scope.first, scope.last, scope.period)
    labels = dict(S.choices)
    statuses = orders.values("status").annotate(n=Count("id"), value=Sum("grand_total")).order_by("-n")
    out["tables"].append(
        table(
            "statuses",
            "Orders by status",
            [
                col("status", "Status"),
                col("orders", "Orders", COUNT),
                col("value", "Order value", MONEY),
                col("share", "Share", PERCENT),
            ],
            [
                {
                    "status": labels.get(r["status"], r["status"]),
                    "orders": r["n"],
                    "value": money(r["value"]),
                    "share": rate(r["n"], count),
                }
                for r in statuses
            ],
            share("status", "orders"),
        )
    )
    types = (
        orders.exclude(status__in=NOT_A_SALE).values("delivery_type").annotate(n=Count("id"), value=Sum("grand_total"))
    )
    out["tables"].append(
        table(
            "delivery_types",
            "Orders by delivery type",
            [col("type", "Delivery"), col("orders", "Orders", COUNT), col("value", "Order value", MONEY)],
            [
                {
                    "type": {"fast": "Fast", "standard": "Standard"}.get(r["delivery_type"], "Not recorded"),
                    "orders": r["n"],
                    "value": money(r["value"]),
                }
                for r in types
            ],
            share("type", "orders"),
        )
    )
    payments = orders.values("payment_method", "payment_status").annotate(n=Count("id")).order_by("-n")
    out["tables"].append(
        table(
            "payments",
            "Orders by payment",
            [col("method", "Method"), col("status", "Payment status"), col("orders", "Orders", COUNT)],
            [
                {
                    "method": "Cash on delivery" if r["payment_method"] == "cod" else "Online",
                    "status": r["payment_status"].replace("_", " "),
                    "orders": r["n"],
                }
                for r in payments
            ],
        )
    )
    return out


def products_report(scope: Scope) -> dict:
    out = report_frame("products", scope)
    lines = sales_lines(scope)
    rows = list(
        lines.values("product_id")
        .annotate(
            name=Max("product_name"),
            brand=Max("brand_name"),
            units=Sum("quantity"),
            sales=Sum(LINE_SALES),
            orders=Count("order_id", distinct=True),
            offer=Sum("offer_discount"),
        )
        .order_by("-sales", "name")
    )
    returned = Counter(
        dict(
            scope_orders(
                ReturnRequest.objects.filter(created_at__gte=scope.start, created_at__lt=scope.end),
                scope.store_ids,
                "order__store_id",
            )
            .values_list("items__order_item__product_id")
            .annotate(u=Sum("items__quantity"))
        )
    )
    units = sum(r["units"] for r in rows)
    out["kpis"] = [
        kpi("products_sold", "Products sold", len(rows), COUNT, "Different products with at least one sale"),
        kpi("units", "Units sold", units),
        kpi("sales", "Sales", money(sum((r["sales"] for r in rows), ZERO)), MONEY),
        kpi("top_product", "Best seller", rows[0]["name"] if rows else None, TEXT),
    ]
    out["tables"].append(
        table(
            "top",
            "Products by sales",
            [
                col("name", "Product"),
                col("brand", "Brand"),
                col("units", "Units", COUNT),
                col("orders", "Orders", COUNT),
                col("sales", "Sales", MONEY),
                col("average_price", "Average price", MONEY),
                col("offer_discount", "Offer discount", MONEY),
                col("returned", "Units returned", COUNT),
            ],
            [
                {
                    "product_id": r["product_id"],
                    "name": r["name"],
                    "brand": r["brand"] or "",
                    "units": r["units"],
                    "orders": r["orders"],
                    "sales": money(r["sales"]),
                    "average_price": money(r["sales"] / r["units"]) if r["units"] else None,
                    "offer_discount": money(r["offer"]),
                    "returned": returned.get(r["product_id"], 0),
                }
                for r in rows
            ],
            bar("name", "sales"),
        )
    )
    sold = Q(order_items__order__created_at__gte=scope.start, order_items__order__created_at__lt=scope.end) & ~Q(
        order_items__order__status__in=NOT_A_SALE
    )
    stock_filter = Q()
    if scope.store_ids is not None:
        sold &= Q(order_items__order__store_id__in=scope.store_ids)
        stock_filter = Q(variants__inventory__store_id__in=scope.store_ids)
    slow = (
        Product.objects.filter(is_active=True, is_published=True)
        .annotate(units=Coalesce(Sum("order_items__quantity", filter=sold), 0))
        .order_by("units", "name")[:25]
    )
    stock = dict(
        Product.objects.filter(pk__in=[p.pk for p in slow])
        .annotate(s=Coalesce(Sum("variants__inventory__available_quantity", filter=stock_filter), 0))
        .values_list("pk", "s")
    )
    out["tables"].append(
        table(
            "slow",
            "Slowest products (published)",
            [col("name", "Product"), col("units", "Units sold", COUNT), col("stock", "In stock", COUNT)],
            [{"product_id": p.pk, "name": p.name, "units": p.units, "stock": stock.get(p.pk, 0)} for p in slow],
        )
    )
    return out


def categories_report(scope: Scope) -> dict:
    out = report_frame("categories", scope)
    names = _top_categories()
    by_top, by_sub = defaultdict(lambda: [0, ZERO, set()]), defaultdict(lambda: [0, ZERO, ""])
    lines = sales_lines(scope).values_list(
        "product__category_id", "product__subcategory_id", "quantity", "line_total", "offer_discount", "order_id"
    )
    for cat_id, sub_id, qty, line_total, offer, order_id in lines.iterator():
        top, own = names.get(cat_id, ("Products no longer in the catalogue", ""))
        value = line_total - offer
        by_top[top][0] += qty
        by_top[top][1] += value
        by_top[top][2].add(order_id)
        sub_name = names.get(sub_id, (top, "Other"))[1] if sub_id else own or "Other"
        by_sub[(top, sub_name)][0] += qty
        by_sub[(top, sub_name)][1] += value
    grand = sum((v[1] for v in by_top.values()), ZERO)
    tops = sorted(by_top.items(), key=lambda kv: (-kv[1][1], kv[0]))
    out["kpis"] = [
        kpi("categories_sold", "Categories with sales", len(tops)),
        kpi("sales", "Sales", money(grand), MONEY),
        kpi("top_category", "Top category", tops[0][0] if tops else None, TEXT),
        kpi("top_share", "Top category's share", rate(tops[0][1][1], grand) if tops else None, PERCENT),
    ]
    out["tables"].append(
        table(
            "categories",
            "Sales by category",
            [
                col("category", "Category"),
                col("units", "Units", COUNT),
                col("orders", "Orders", COUNT),
                col("sales", "Sales", MONEY),
                col("share", "Share", PERCENT),
            ],
            [
                {"category": name, "units": v[0], "orders": len(v[2]), "sales": money(v[1]), "share": rate(v[1], grand)}
                for name, v in tops
            ],
            share("category", "sales"),
        )
    )
    subs = sorted(by_sub.items(), key=lambda kv: (-kv[1][1], kv[0]))
    out["tables"].append(
        table(
            "subcategories",
            "Sales by subcategory",
            [
                col("category", "Category"),
                col("subcategory", "Subcategory"),
                col("units", "Units", COUNT),
                col("sales", "Sales", MONEY),
                col("share", "Share", PERCENT),
            ],
            [
                {"category": top, "subcategory": sub, "units": v[0], "sales": money(v[1]), "share": rate(v[1], grand)}
                for (top, sub), v in subs
            ],
            bar("subcategory", "sales"),
        )
    )
    return out


def brands_report(scope: Scope) -> dict:
    out = report_frame("brands", scope)
    rows = list(
        sales_lines(scope)
        .values("brand_name")
        .annotate(
            units=Sum("quantity"),
            sales=Sum(LINE_SALES),
            products=Count("product_id", distinct=True),
            orders=Count("order_id", distinct=True),
        )
        .order_by("-sales", "brand_name")
    )
    grand = sum((r["sales"] for r in rows), ZERO)
    out["kpis"] = [
        kpi("brands_sold", "Brands with sales", len(rows)),
        kpi("sales", "Sales", money(grand), MONEY),
        kpi("top_brand", "Top brand", (rows[0]["brand_name"] or "No brand") if rows else None, TEXT),
    ]
    out["tables"].append(
        table(
            "brands",
            "Sales by brand",
            [
                col("brand", "Brand"),
                col("products", "Products", COUNT),
                col("units", "Units", COUNT),
                col("orders", "Orders", COUNT),
                col("sales", "Sales", MONEY),
                col("share", "Share", PERCENT),
            ],
            [
                {
                    "brand": r["brand_name"] or "No brand",
                    "products": r["products"],
                    "units": r["units"],
                    "orders": r["orders"],
                    "sales": money(r["sales"]),
                    "share": rate(r["sales"], grand),
                }
                for r in rows
            ],
            share("brand", "sales"),
        )
    )
    return out


def inventory_report(scope: Scope) -> dict:
    out = report_frame("inventory", scope)
    stock = scope_orders(
        Inventory.objects.filter(variant__is_active=True, variant__product__is_deleted=False), scope.store_ids
    ).select_related("store", "variant__product")
    per_store = defaultdict(lambda: {"units": 0, "value": ZERO, "low": 0, "out": 0, "records": 0})
    sold = Counter(dict(sales_lines(scope).values_list("variant_id").annotate(u=Sum("quantity"))))
    attention = []
    for row in stock.iterator():
        s = per_store[row.store.name]
        s["records"] += 1
        s["units"] += row.available_quantity
        s["value"] += row.available_quantity * row.variant.price
        low = 0 < row.available_quantity <= row.low_stock_threshold
        out_of = row.available_quantity <= 0
        s["low"] += low
        s["out"] += out_of
        if low or out_of:
            per_day = sold.get(row.variant_id, 0) / scope.days
            attention.append(
                {
                    "store": row.store.name,
                    "product": row.variant.product.name,
                    "variant": row.variant.name,
                    "sku": row.variant.sku,
                    "available": row.available_quantity,
                    "threshold": row.low_stock_threshold,
                    "sold": sold.get(row.variant_id, 0),
                    "days_of_cover": round(row.available_quantity / per_day, 1) if per_day else None,
                }
            )
    attention.sort(key=lambda r: (r["available"], r["product"]))
    totals = {k: sum(s[k] for s in per_store.values()) for k in ("units", "low", "out", "records")}
    value = sum((s["value"] for s in per_store.values()), ZERO)
    movements = (
        scope_orders(
            StockMovement.objects.filter(created_at__gte=scope.start, created_at__lt=scope.end),
            scope.store_ids,
            "inventory__store_id",
        )
        .values("movement_type")
        .annotate(n=Count("id"), units=Sum("quantity"))
        .order_by("movement_type")
    )
    labels = dict(StockMovement.Type.choices)
    out["kpis"] = [
        kpi("units", "Units in stock", totals["units"]),
        kpi("value", "Stock value at selling price", money(value), MONEY, "Available units × current price"),
        kpi("low_stock", "Low stock", totals["low"]),
        kpi("out_of_stock", "Out of stock", totals["out"]),
        kpi("stock_records", "Stock records", totals["records"]),
    ]
    out["tables"].append(
        table(
            "stores",
            "Stock by location",
            [
                col("store", "Store / warehouse"),
                col("units", "Units", COUNT),
                col("value", "Value", MONEY),
                col("low", "Low", COUNT),
                col("out", "Out", COUNT),
            ],
            [
                {"store": name, "units": s["units"], "value": money(s["value"]), "low": s["low"], "out": s["out"]}
                for name, s in sorted(per_store.items())
            ],
            bar("store", "value"),
        )
    )
    out["tables"].append(
        table(
            "attention",
            "Low and out-of-stock items",
            [
                col("store", "Store"),
                col("product", "Product"),
                col("variant", "Variant"),
                col("sku", "SKU"),
                col("available", "Available", COUNT),
                col("threshold", "Threshold", COUNT),
                col("sold", "Sold in period", COUNT),
                col("days_of_cover", "Days of cover", NUMBER),
            ],
            attention,
        )
    )
    out["tables"].append(
        table(
            "movements",
            "Stock movements in the period",
            [col("type", "Movement"), col("count", "Entries", COUNT), col("units", "Units", COUNT)],
            [
                {"type": labels.get(m["movement_type"], m["movement_type"]), "count": m["n"], "units": m["units"]}
                for m in movements
            ],
            bar("type", "units"),
        )
    )
    out["notes"].append("Days of cover = units available ÷ average units sold per day in the period.")
    return out


def delivery_report(scope: Scope) -> dict:
    out = report_frame("delivery", scope)
    perf = _delivery_performance(scope.store_ids, scope.start, scope.end)
    out["kpis"] = [
        kpi("delivered", "Shipments delivered", perf["all"]["delivered"]),
        kpi(
            "on_time_rate",
            "On time",
            perf["all"]["on_time_rate"],
            PERCENT,
            "Delivered by the end of the promised window",
        ),
        kpi("fast_delivered", "Fast deliveries", perf["fast"]["delivered"]),
        kpi("fast_on_time_rate", "Fast on time", perf["fast"]["on_time_rate"], PERCENT),
        kpi("fast_promised", "Fast: promised minutes (avg)", perf["fast"]["average_promised_minutes"], MINUTES),
        kpi("fast_actual", "Fast: actual minutes (avg)", perf["fast"]["average_actual_minutes"], MINUTES),
        kpi("first_attempt_rate", "Delivered at first attempt", perf["first_attempt_rate"], PERCENT),
        kpi("failed_attempts", "Failed attempts", perf["failed_attempts"]),
    ]
    out["tables"].append(
        table(
            "types",
            "Fast and standard delivery",
            [
                col("type", "Delivery"),
                col("delivered", "Delivered", COUNT),
                col("on_time", "On time", COUNT),
                col("on_time_rate", "On-time rate", PERCENT),
                col("promised", "Promised min (avg)", MINUTES),
                col("actual", "Actual min (avg)", MINUTES),
            ],
            [
                {
                    "type": label,
                    "delivered": perf[k]["delivered"],
                    "on_time": perf[k]["on_time"],
                    "on_time_rate": perf[k]["on_time_rate"],
                    "promised": perf[k]["average_promised_minutes"],
                    "actual": perf[k]["average_actual_minutes"],
                }
                for k, label in (("fast", "Fast"), ("standard", "Standard"))
            ],
        )
    )
    shipments = scope_orders(
        OrderShipment.objects.filter(delivered_at__gte=scope.start, delivered_at__lt=scope.end), scope.store_ids
    ).values_list("store__name", "delivery_type", "delivered_at", "window_end")
    stores = defaultdict(lambda: {"delivered": 0, "fast": 0, "measured": 0, "on_time": 0})
    for name, kind, delivered_at, window_end in shipments.iterator():
        s = stores[name]
        s["delivered"] += 1
        s["fast"] += kind == "fast"
        if window_end:
            s["measured"] += 1
            s["on_time"] += delivered_at <= window_end
    out["tables"].append(
        table(
            "stores",
            "Delivery by store",
            [
                col("store", "Store"),
                col("delivered", "Delivered", COUNT),
                col("fast_share", "Fast share", PERCENT),
                col("on_time_rate", "On-time rate", PERCENT),
            ],
            [
                {
                    "store": name,
                    "delivered": s["delivered"],
                    "fast_share": rate(s["fast"], s["delivered"]),
                    "on_time_rate": rate(s["on_time"], s["measured"]),
                }
                for name, s in sorted(stores.items())
            ],
            bar("store", "delivered"),
        )
    )
    out["tables"].append(
        table(
            "failures",
            "Why deliveries failed",
            [col("reason", "Reason"), col("count", "Attempts", COUNT)],
            [{"reason": r["label"], "count": r["count"]} for r in perf["failure_reasons"]],
            share("reason", "count"),
        )
    )
    return out


def riders_report(scope: Scope) -> dict:
    out = report_frame("riders", scope)
    jobs = scope_orders(
        DeliveryAssignment.objects.filter(assigned_at__gte=scope.start, assigned_at__lt=scope.end),
        scope.store_ids,
        "shipment__store_id",
    ).select_related("partner__user")
    A = DeliveryAssignment.Status
    riders = defaultdict(
        lambda: {
            "jobs": 0,
            "delivered": 0,
            "failed": 0,
            "rejected": 0,
            "minutes": [],
            "cod": ZERO,
            "earnings": ZERO,
            "km": Decimal("0"),
        }
    )
    for job in jobs.iterator():
        r = riders[(job.partner_id, job.partner.user.full_name or job.partner.user.email)]
        r["jobs"] += 1
        r["delivered"] += job.status == A.DELIVERED
        r["failed"] += job.status == A.FAILED
        r["rejected"] += job.status == A.REJECTED
        if job.status == A.DELIVERED and job.out_for_delivery_at and job.delivered_at:
            r["minutes"].append((job.delivered_at - job.out_for_delivery_at).total_seconds() / 60)
        r["cod"] += job.cod_collected_amount or ZERO
        r["earnings"] += job.earning_amount or ZERO
        r["km"] += job.distance_km or 0
    rows = [
        {
            "rider": name,
            "jobs": r["jobs"],
            "delivered": r["delivered"],
            "failed": r["failed"],
            "rejected": r["rejected"],
            "success_rate": rate(r["delivered"], r["delivered"] + r["failed"]),
            "average_minutes": round(sum(r["minutes"]) / len(r["minutes"]), 1) if r["minutes"] else None,
            "cod": money(r["cod"]),
            "earnings": money(r["earnings"]),
            "km": float(round(r["km"], 1)),
        }
        for (_pk, name), r in riders.items()
    ]
    rows.sort(key=lambda r: (-r["delivered"], r["rider"]))
    delivered = sum(r["delivered"] for r in rows)
    out["kpis"] = [
        kpi("riders", "Riders with jobs", len(rows)),
        kpi("jobs", "Jobs assigned", sum(r["jobs"] for r in rows)),
        kpi("delivered", "Delivered", delivered),
        kpi("failed", "Failed", sum(r["failed"] for r in rows)),
        kpi("cod", "Cash collected", money(sum((riders[k]["cod"] for k in riders), ZERO)), MONEY),
        kpi("earnings", "Rider earnings", money(sum((riders[k]["earnings"] for k in riders), ZERO)), MONEY),
    ]
    out["tables"].append(
        table(
            "riders",
            "Delivery partners",
            [
                col("rider", "Rider"),
                col("jobs", "Jobs", COUNT),
                col("delivered", "Delivered", COUNT),
                col("failed", "Failed", COUNT),
                col("rejected", "Rejected", COUNT),
                col("success_rate", "Success", PERCENT),
                col("average_minutes", "Minutes on the road (avg)", MINUTES),
                col("cod", "Cash collected", MONEY),
                col("earnings", "Earnings", MONEY),
                col("km", "Distance (km)", NUMBER),
            ],
            rows,
            bar("rider", "delivered"),
        )
    )
    out["notes"].append("Jobs assigned in the period. Minutes on the road = out for delivery → delivered.")
    return out


def customers_report(scope: Scope) -> dict:
    out = report_frame("customers", scope)
    orders = orders_in(scope).exclude(status__in=NOT_A_SALE)
    per_customer = list(
        orders.values("user_id", "user__full_name", "user__email")
        .annotate(n=Count("id"), value=Sum("grand_total"), last=Max("created_at"))
        .order_by("-value")
    )
    ids = [r["user_id"] for r in per_customer]
    earlier = set(
        scope_orders(Order.objects.filter(user_id__in=ids, created_at__lt=scope.start), scope.store_ids)
        .exclude(status__in=NOT_A_SALE)
        .values_list("user_id", flat=True)
    )
    new = [r for r in per_customer if r["user_id"] not in earlier]
    returning = [r for r in per_customer if r["user_id"] in earlier]
    repeat_in_period = sum(1 for r in per_customer if r["n"] >= 2)
    value = sum((r["value"] for r in per_customer), ZERO)
    count = len(per_customer)
    out["kpis"] = [
        kpi("customers", "Customers who ordered", count),
        kpi("new_customers", "New customers", len(new), COUNT, "First order with the shop in this period"),
        kpi("returning_customers", "Returning customers", len(returning), COUNT, "Had ordered before the period"),
        kpi("repeat_rate", "Ordered more than once", rate(repeat_in_period, count), PERCENT, "Within the period"),
        kpi(
            "orders_per_customer",
            "Orders per customer",
            round(sum(r["n"] for r in per_customer) / count, 2) if count else None,
            NUMBER,
        ),
        kpi("value_per_customer", "Order value per customer", money(value / count) if count else None, MONEY),
    ]
    out["tables"].append(
        table(
            "segments",
            "New and returning customers",
            [
                col("segment", "Customers"),
                col("customers", "Count", COUNT),
                col("orders", "Orders", COUNT),
                col("value", "Order value", MONEY),
                col("share", "Share of value", PERCENT),
            ],
            [
                {
                    "segment": label,
                    "customers": len(rows),
                    "orders": sum(r["n"] for r in rows),
                    "value": money(sum((r["value"] for r in rows), ZERO)),
                    "share": rate(sum((r["value"] for r in rows), ZERO), value),
                }
                for label, rows in (("New", new), ("Returning", returning))
            ],
            share("segment", "value"),
        )
    )
    out["tables"].append(
        table(
            "top",
            "Top customers",
            [
                col("name", "Customer"),
                col("email", "Email"),
                col("orders", "Orders", COUNT),
                col("value", "Order value", MONEY),
                col("last_order", "Last order", TEXT),
            ],
            [
                {
                    "name": r["user__full_name"] or "—",
                    "email": mask_email(r["user__email"]),
                    "orders": r["n"],
                    "value": money(r["value"]),
                    "last_order": timezone.localtime(r["last"]).date().isoformat(),
                }
                for r in per_customer[:25]
            ],
        )
    )
    out["notes"].append("Cancelled orders and orders still waiting for payment are not counted. Emails are masked.")
    return out


def returns_report(scope: Scope) -> dict:
    out = report_frame("returns", scope)
    orders = orders_in(scope)
    count = orders.count()
    cancelled = orders.filter(status=S.CANCELLED)
    returns = scope_orders(
        ReturnRequest.objects.filter(created_at__gte=scope.start, created_at__lt=scope.end),
        scope.store_ids,
        "order__store_id",
    )
    delivered = orders.filter(status__in=(S.DELIVERED, S.RETURN_REQUESTED, S.RETURNED)).count()
    refunds = scope_orders(
        Refund.objects.filter(created_at__gte=scope.start, created_at__lt=scope.end),
        scope.store_ids,
        "payment__order__store_id",
    )
    out["kpis"] = [
        kpi("cancelled", "Cancelled orders", cancelled.count()),
        kpi("cancellation_rate", "Cancellation rate", rate(cancelled.count(), count), PERCENT),
        kpi("cancelled_value", "Cancelled value", money(total(cancelled, "grand_total")), MONEY),
        kpi("returns", "Return requests", returns.count()),
        kpi(
            "return_rate", "Return rate", rate(returns.count(), delivered), PERCENT, "Of orders delivered in the period"
        ),
        kpi(
            "refunds_processed",
            "Refunds paid",
            money(total(refunds.filter(status=Refund.Status.PROCESSED), "amount")),
            MONEY,
        ),
        kpi("refunds_pending", "Refunds pending", refunds.filter(status=Refund.Status.PENDING).count()),
        kpi("refunds_failed", "Refunds failed", refunds.filter(status=Refund.Status.FAILED).count()),
    ]
    reasons = (
        cancelled.exclude(cancellation_reason="").values("cancellation_reason").annotate(n=Count("id")).order_by("-n")
    )
    out["tables"].append(
        table(
            "cancellation_reasons",
            "Why orders were cancelled",
            [col("reason", "Reason"), col("count", "Orders", COUNT)],
            [{"reason": r["cancellation_reason"], "count": r["n"]} for r in reasons],
            share("reason", "count"),
        )
    )
    labels = dict(ReturnRequest.Reason.choices)
    return_reasons = returns.values("reason").annotate(n=Count("id")).order_by("-n")
    out["tables"].append(
        table(
            "return_reasons",
            "Why items were returned",
            [col("reason", "Reason"), col("count", "Returns", COUNT)],
            [{"reason": labels.get(r["reason"], r["reason"]), "count": r["n"]} for r in return_reasons],
            share("reason", "count"),
        )
    )
    products = (
        returns.values("items__order_item__product_name")
        .annotate(units=Sum("items__quantity"), requests=Count("id", distinct=True))
        .exclude(items__order_item__product_name=None)
        .order_by("-units")
    )
    out["tables"].append(
        table(
            "products",
            "Most returned products",
            [col("product", "Product"), col("units", "Units", COUNT), col("requests", "Requests", COUNT)],
            [
                {"product": r["items__order_item__product_name"], "units": r["units"], "requests": r["requests"]}
                for r in products
            ],
            bar("product", "units"),
        )
    )
    statuses = refunds.values("status").annotate(n=Count("id"), amount=Sum("amount")).order_by("status")
    out["tables"].append(
        table(
            "refunds",
            "Refunds by status",
            [col("status", "Status"), col("count", "Refunds", COUNT), col("amount", "Amount", MONEY)],
            [{"status": r["status"].capitalize(), "count": r["n"], "amount": money(r["amount"])} for r in statuses],
        )
    )
    return out


def offers_report(scope: Scope) -> dict:
    out = report_frame("offers", scope)
    orders = paid(orders_in(scope))
    ids = orders.values("pk")
    offer_rows = (
        OfferRedemption.objects.filter(order_id__in=ids)
        .values("offer__name")
        .annotate(n=Count("order_id", distinct=True), discount=Sum("discount_amount"))
        .order_by("-discount")
    )
    coupon_rows = (
        CouponRedemption.objects.filter(order_id__in=ids)
        .values("coupon__code")
        .annotate(n=Count("order_id", distinct=True), discount=Sum("discount_amount"))
        .order_by("-discount")
    )
    # Net goods value of the orders that used each offer / coupon (each order once, delivery fee excluded).
    goods = {
        pk: subtotal - offer - coupon
        for pk, subtotal, offer, coupon in orders.values_list("pk", "subtotal", "offer_discount", "coupon_discount")
    }
    used_by = defaultdict(set)
    for name, order_id in OfferRedemption.objects.filter(order_id__in=ids).values_list("offer__name", "order_id"):
        used_by[("offer", name)].add(order_id)
    for code, order_id in CouponRedemption.objects.filter(order_id__in=ids).values_list("coupon__code", "order_id"):
        used_by[("coupon", code)].add(order_id)

    def goods_value(kind: str, name: str) -> str:
        return money(sum((goods.get(pk, ZERO) for pk in used_by[(kind, name)]), ZERO))

    count = orders.count()
    with_offer = orders.filter(Q(offer_discount__gt=0) | Q(coupon_discount__gt=0)).count()
    offer_total, coupon_total = total(orders, "offer_discount"), total(orders, "coupon_discount")
    credits = total(orders, "credit_discount")
    free_delivery = orders.exclude(free_delivery_reason="").count()
    out["kpis"] = [
        kpi("orders_with_discount", "Paid orders with an offer or coupon", with_offer),
        kpi("discount_share", "Share of paid orders", rate(with_offer, count), PERCENT),
        kpi("offer_discount", "Automatic offers", money(offer_total), MONEY),
        kpi("coupon_discount", "Coupons", money(coupon_total), MONEY),
        kpi("credits_used", "Credits used", money(credits), MONEY),
        kpi("free_delivery_orders", "Orders with free delivery", free_delivery),
    ]
    out["tables"].append(
        table(
            "offers",
            "Automatic offers",
            [
                col("offer", "Offer"),
                col("orders", "Orders", COUNT),
                col("discount", "Discount given", MONEY),
                col("revenue", "Net goods value of those orders", MONEY),
            ],
            [
                {
                    "offer": r["offer__name"],
                    "orders": r["n"],
                    "discount": money(r["discount"]),
                    "revenue": goods_value("offer", r["offer__name"]),
                }
                for r in offer_rows
            ],
            bar("offer", "discount"),
        )
    )
    out["tables"].append(
        table(
            "coupons",
            "Coupons",
            [
                col("code", "Code"),
                col("orders", "Orders", COUNT),
                col("discount", "Discount given", MONEY),
                col("revenue", "Net goods value of those orders", MONEY),
            ],
            [
                {
                    "code": r["coupon__code"],
                    "orders": r["n"],
                    "discount": money(r["discount"]),
                    "revenue": goods_value("coupon", r["coupon__code"]),
                }
                for r in coupon_rows
            ],
            bar("code", "discount"),
        )
    )
    reasons = (
        orders.exclude(free_delivery_reason="").values("free_delivery_reason").annotate(n=Count("id")).order_by("-n")
    )
    out["tables"].append(
        table(
            "free_delivery",
            "Why delivery was free",
            [col("reason", "Rule or offer"), col("orders", "Orders", COUNT)],
            [{"reason": r["free_delivery_reason"], "orders": r["n"]} for r in reasons],
        )
    )
    out["notes"].append(
        "Paid orders placed in the period. Net goods value: what those orders' goods sold for after offers and "
        "coupon (before credits, without delivery fees), each order counted once."
    )
    return out


def stores_report(scope: Scope) -> dict:
    out = report_frame("stores", scope)
    stores = Store.objects.filter(is_deleted=False)
    if scope.store_ids is not None:
        stores = stores.filter(pk__in=scope.store_ids)
    orders = orders_in(scope)
    by_store = {
        r["store_id"]: r
        for r in orders.values("store_id").annotate(
            n=Count("id"),
            cancelled=Count("id", filter=Q(status=S.CANCELLED)),
            paid_n=Count("id", filter=Q(payment_status__in=PAID)),
            revenue=Sum("grand_total", filter=Q(payment_status__in=PAID)),
            fast=Count("id", filter=Q(delivery_type="fast") & ~Q(status__in=NOT_A_SALE)),
            sales=Count("id", filter=~Q(status__in=NOT_A_SALE)),
        )
    }
    low = dict(
        Inventory.objects.filter(available_quantity__lte=F("low_stock_threshold"), variant__is_active=True)
        .values("store_id")
        .annotate(n=Count("id"))
        .values_list("store_id", "n")
    )
    shipped = defaultdict(lambda: [0, 0])
    for store_id, delivered_at, window_end in (
        OrderShipment.objects.filter(
            delivered_at__gte=scope.start, delivered_at__lt=scope.end, window_end__isnull=False
        )
        .values_list("store_id", "delivered_at", "window_end")
        .iterator()
    ):
        shipped[store_id][0] += 1
        shipped[store_id][1] += delivered_at <= window_end
    rows = []
    for store in stores.order_by("name"):
        r = by_store.get(store.pk, {})
        revenue = r.get("revenue") or ZERO
        rows.append(
            {
                "store": store.name,
                "kind": store.get_kind_display(),
                "orders": r.get("n", 0),
                "paid_orders": r.get("paid_n", 0),
                "revenue": money(revenue),
                "average_order_value": money(revenue / r["paid_n"]) if r.get("paid_n") else None,
                "cancellation_rate": rate(r.get("cancelled", 0), r.get("n", 0)),
                "fast_share": rate(r.get("fast", 0), r.get("sales", 0)),
                "on_time_rate": rate(shipped[store.pk][1], shipped[store.pk][0]),
                "low_stock": low.get(store.pk, 0),
            }
        )
    rows.sort(key=lambda r: (-Decimal(r["revenue"]), r["store"]))
    out["kpis"] = [
        kpi("stores", "Stores and warehouses", len(rows)),
        kpi(
            "best_store",
            "Highest revenue",
            rows[0]["store"] if rows and Decimal(rows[0]["revenue"]) > 0 else None,
            TEXT,
        ),
        kpi("revenue", "Revenue", money(sum((Decimal(r["revenue"]) for r in rows), ZERO)), MONEY),
    ]
    out["tables"].append(
        table(
            "stores",
            "Store performance",
            [
                col("store", "Store"),
                col("kind", "Type"),
                col("orders", "Orders", COUNT),
                col("paid_orders", "Paid", COUNT),
                col("revenue", "Revenue", MONEY),
                col("average_order_value", "Avg order", MONEY),
                col("cancellation_rate", "Cancelled", PERCENT),
                col("fast_share", "Fast delivery", PERCENT),
                col("on_time_rate", "On time", PERCENT),
                col("low_stock", "Low-stock items", COUNT),
            ],
            rows,
            bar("store", "revenue"),
        )
    )
    out["notes"].append("Orders count for the store chosen at checkout; deliveries for the store that shipped them.")
    return out


def margin_report(scope: Scope) -> dict:
    out = report_frame("margin", scope)
    orders = paid(orders_in(scope))
    mrp, subtotal = total(orders, "mrp_total"), total(orders, "subtotal")
    offer, coupon, credits = (
        total(orders, "offer_discount"),
        total(orders, "coupon_discount"),
        total(orders, "credit_discount"),
    )
    out["kpis"] = [
        kpi("mrp_value", "Value at MRP", money(mrp), MONEY, "Paid orders"),
        kpi("selling_value", "Value at selling price", money(subtotal), MONEY, "Before offers, coupons and credits"),
        kpi("price_discount", "Below MRP", rate(mrp - subtotal, mrp), PERCENT, "Selling price vs MRP"),
        kpi("promotions", "Offers + coupons + credits", money(offer + coupon + credits), MONEY),
        kpi(
            "realisation",
            "Realised vs MRP",
            rate(subtotal - offer - coupon - credits, mrp),
            PERCENT,
            "What customers paid for goods as a share of MRP",
        ),
    ]
    names = _top_categories()
    groups = defaultdict(_Profit)
    whole = _Profit()
    for line in _profit_lines(scope):
        g = groups[names.get(line["cat_id"], ("Products no longer in the catalogue", ""))[0]]
        g.mrp += (line["unit_mrp"] or ZERO) * line["quantity"]
        g.selling += line["line_total"]
        g.offers += line["offer_discount"]
        for bucket in (g, whole):
            bucket.add(line)
    covered = whole.lines_costed > 0
    out["kpis"] += [
        kpi("goods_revenue", "Goods revenue", money(whole.revenue), MONEY, "Paid for goods, minus refunded returns"),
        kpi("costed_revenue", "Revenue with a known cost", money(whole.costed_revenue), MONEY),
        kpi("cost_of_goods", "Purchase cost", money(whole.cost) if covered else None, MONEY, "Items with a cost only"),
        kpi("gross_profit", "Gross profit", money(whole.profit) if covered else None, MONEY, "Items with a cost only"),
        kpi("gross_margin", "Gross margin", whole.margin, PERCENT, "Gross profit ÷ revenue with a known cost"),
        kpi(
            "cost_coverage",
            "Cost coverage",
            rate(whole.costed_revenue, whole.revenue),
            PERCENT,
            f"Share of goods revenue with a purchase cost ({whole.lines_costed} of {whole.lines} order lines)",
        ),
    ]
    out["tables"].append(
        table(
            "categories",
            "Price realisation and profit by category",
            [
                col("category", "Category"),
                col("mrp", "At MRP", MONEY),
                col("selling", "At selling price", MONEY),
                col("offers", "Offer discount", MONEY),
                col("below_mrp", "Below MRP", PERCENT),
                col("revenue", "Goods revenue", MONEY),
                col("cost", "Purchase cost", MONEY),
                col("profit", "Gross profit", MONEY),
                col("margin", "Margin", PERCENT),
                col("coverage", "Cost coverage", PERCENT),
            ],
            [
                {
                    "category": name,
                    "mrp": money(g.mrp),
                    "selling": money(g.selling),
                    "offers": money(g.offers),
                    "below_mrp": rate(g.mrp - g.selling + g.offers, g.mrp),
                    "revenue": money(g.revenue),
                    "cost": money(g.cost) if g.lines_costed else None,
                    "profit": money(g.profit) if g.lines_costed else None,
                    "margin": g.margin,
                    "coverage": rate(g.costed_revenue, g.revenue),
                }
                for name, g in sorted(groups.items(), key=lambda kv: -kv[1].selling)
            ],
            bar("category", "selling"),
        )
    )
    if not covered:
        out["notes"].append(
            "No purchase costs on the items sold in this period, so profit and margin can't be shown. "
            "Add purchase costs to products to see profit."
        )
    else:
        out["notes"].append(
            "Profit and margin count only order lines with a purchase cost recorded when the order was placed "
            f"({rate(whole.costed_revenue, whole.revenue)}% of goods revenue); the rest is left out, not estimated."
        )
    out["notes"].append(
        "Goods revenue is what customers paid for the items (after offers, coupon and credits, quoted prices as "
        "quoted), minus refunds of received returns. Returned items put back on the shelf carry no cost; items not "
        "restocked keep their cost. Delivery fees are not included."
    )
    return out


class _Profit:
    """Running totals for the margin report (one category, or the whole period)."""

    def __init__(self):
        self.mrp = self.selling = self.offers = ZERO
        self.revenue = self.costed_revenue = self.cost = ZERO
        self.lines = self.lines_costed = 0

    def add(self, line: dict) -> None:
        self.revenue += line["revenue"]
        self.lines += 1
        if line["cost"] is not None:
            self.costed_revenue += line["revenue"]
            self.cost += line["cost"]
            self.lines_costed += 1

    @property
    def profit(self) -> Decimal:
        return self.costed_revenue - self.cost

    @property
    def margin(self) -> float | None:
        return rate(self.profit, self.costed_revenue) if self.lines_costed else None


def _profit_lines(scope: Scope):
    """Paid sale lines of the period with what was paid for them net of refunded returns (`revenue`) and,
    only where the order line has a purchase cost snapshot, the cost of the units kept or written off."""
    from apps.orders.returns import paid_amounts  # orders.returns imports services; keep it lazy

    lines = list(
        sales_lines(scope)
        .filter(order__payment_status__in=PAID)
        .values_list(
            "id",
            "order_id",
            "product__category_id",
            "unit_mrp",
            "quantity",
            "line_total",
            "offer_discount",
            "unit_cost",
        )
    )
    if not lines:
        return
    order_rows = Order.objects.filter(pk__in={row[1] for row in lines}).values_list(
        "pk", "coupon_discount", "credit_discount"
    )
    discounts = {pk: (coupon, credit) for pk, coupon, credit in order_rows}
    by_order = defaultdict(list)
    for row in lines:
        by_order[row[1]].append(SimpleNamespace(id=row[0], line_total=row[5], offer_discount=row[6]))
    paid_by_line = {}
    for order_id, items in by_order.items():
        coupon, credit = discounts[order_id]
        paid_by_line.update(paid_amounts(SimpleNamespace(coupon_discount=coupon, credit_discount=credit), items))
    back = defaultdict(lambda: [0, ZERO])  # line → [units back on the shelf, refunded]
    for item_id, qty, refund, restocked in ReturnItem.objects.filter(
        order_item_id__in=paid_by_line, return_request__status=ReturnRequest.Status.RECEIVED
    ).values_list("order_item_id", "quantity", "refund_amount", "return_request__restocked"):
        back[item_id][0] += qty if restocked else 0
        back[item_id][1] += refund
    for line_id, _order_id, cat_id, unit_mrp, qty, line_total, offer, unit_cost in lines:
        restocked, refunded = back.get(line_id, (0, ZERO))
        yield {
            "cat_id": cat_id,
            "unit_mrp": unit_mrp,
            "quantity": qty,
            "line_total": line_total,
            "offer_discount": offer,
            "revenue": paid_by_line[line_id] - refunded,
            "cost": None if unit_cost is None else unit_cost * max(qty - restocked, 0),
        }


@dataclass(frozen=True)
class ReportSpec:
    key: str
    title: str
    description: str
    build: callable


REPORTS: dict[str, ReportSpec] = {
    spec.key: spec
    for spec in (
        ReportSpec(
            "sales",
            "Sales and revenue",
            "Revenue, refunds, discounts, fees and GST; by day, method and hour.",
            sales_report,
        ),
        ReportSpec("orders", "Orders", "Orders by status, delivery type and payment.", orders_report),
        ReportSpec("products", "Products", "Best and slowest sellers, units, returns.", products_report),
        ReportSpec("categories", "Categories", "Sales by category and subcategory.", categories_report),
        ReportSpec("brands", "Brands", "Sales by brand.", brands_report),
        ReportSpec(
            "inventory", "Inventory", "Stock value, low stock, days of cover and stock movements.", inventory_report
        ),
        ReportSpec(
            "delivery", "Fast delivery", "On-time and fast-delivery performance, failures, by store.", delivery_report
        ),
        ReportSpec(
            "riders",
            "Delivery partners",
            "Jobs, success, time on the road, cash and earnings per rider.",
            riders_report,
        ),
        ReportSpec(
            "customers", "Customers", "New and returning customers, repeat purchases, top customers.", customers_report
        ),
        ReportSpec(
            "returns",
            "Returns, refunds and cancellations",
            "Rates, reasons, most returned products, refunds.",
            returns_report,
        ),
        ReportSpec(
            "offers",
            "Offers and coupons",
            "Discounts given by offer, coupon and credits; free delivery.",
            offers_report,
        ),
        ReportSpec(
            "stores", "Stores and warehouses", "Revenue, orders, delivery and stock by location.", stores_report
        ),
        ReportSpec(
            "margin",
            "Profit and price realisation",
            "Gross profit from purchase costs (with cost coverage), MRP vs selling price and promotions.",
            margin_report,
        ),
    )
}


def build(key: str, scope: Scope) -> dict:
    return REPORTS[key].build(scope)
