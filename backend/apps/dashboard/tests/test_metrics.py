"""The dashboard and analytics numbers are checked against orders built in the test: every
figure must be traceable to rows in the database."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.testing import create_category, create_product, create_store
from apps.dashboard.metrics import bucket_start, buckets
from apps.delivery.tests.helpers import advance, assign, create_partner, deliver_job, packed_order, store_at, zone_for
from apps.inventory.models import Inventory
from apps.orders.models import Order
from apps.orders.services import cancel_order_by_customer
from apps.orders.tests.helpers import deliver, order_with, pay

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(user, other_user, admin_user):
    """Three orders: one delivered and paid in cash, one paid online, one cancelled."""
    tools, paint = create_category("Tools"), create_category("Paint")
    store = create_store(name="Kothrud")
    _, drill = create_product(name="Drill", price="1000.00", mrp="1200.00", category=tools, stock=20, store=store)
    _, primer = create_product(name="Primer", price="300.00", mrp="300.00", category=paint, stock=20, store=store)
    create_product(name="Dusty Shelf Item", price="50.00", mrp="60.00", category=paint, stock=5, store=store)

    delivered, _ = order_with(user, (drill, 2))
    deliver(delivered, admin_user)
    online, payment = order_with(other_user, (drill, 1), (primer, 2), method="online")
    pay(online, payment)
    cancelled, _ = order_with(user, (primer, 1))
    cancel_order_by_customer(cancelled, user=user, reason="Ordered by mistake")
    for order in (delivered, online, cancelled):
        order.refresh_from_db()
    return {"store": store, "delivered": delivered, "online": online, "cancelled": cancelled, "drill": drill}


def test_dashboard_summary_matches_the_database(shop, admin_client):
    data = admin_client.get("/api/admin/summary/").data
    revenue = shop["delivered"].grand_total + shop["online"].grand_total

    assert data["orders"]["total"] == 3
    assert data["orders"]["today"] == 3
    assert data["orders"]["delivered"] == 1
    assert data["orders"]["cancelled"] == 1
    assert data["orders"]["processing"] == 1  # the online order, confirmed
    assert data["orders"]["by_status"]["confirmed"] == 1
    assert sum(data["orders"]["by_status"].values()) == 3
    assert data["revenue"]["total"] == str(revenue)
    assert data["revenue"]["today"] == str(revenue)
    assert data["revenue"]["this_month"] == str(revenue)
    assert data["customers"] == {"total": 2, "active": 2, "new_this_month": 2}
    assert data["products"]["total"] == 3
    assert data["stores"]["active"] == 1

    assert len(data["trend"]) == 14
    today = data["trend"][-1]
    assert today["start"] == timezone.localdate().isoformat()
    assert (today["orders"], today["paid_orders"], today["cancelled"]) == (3, 2, 1)
    assert today["revenue"] == str(revenue)
    assert all(day["orders"] == 0 for day in data["trend"][:-1])

    assert {a["code"]: a["count"] for a in data["attention"]} == {
        "orders_to_prepare": 1,
        "low_stock": 1,  # the shelf item: 5 left, at its threshold
    }


def test_an_empty_shop_shows_zeros_not_invented_numbers(admin_client):
    data = admin_client.get("/api/admin/summary/").data
    assert data["orders"]["total"] == 0
    assert data["revenue"] == {"total": "0.00", "today": "0.00", "this_month": "0.00", "refunded_total": "0.00"}
    assert data["attention"] == []
    assert all(day["orders"] == 0 and day["revenue"] == "0.00" for day in data["trend"])

    analytics = admin_client.get("/api/admin/analytics/").data
    assert analytics["totals"]["orders"] == 0
    assert analytics["totals"]["average_order_value"] is None
    assert analytics["totals"]["cancellation_rate"] is None
    assert analytics["top_products"] == []
    assert analytics["category_sales"] == []
    assert analytics["delivery"]["all"]["on_time_rate"] is None


def test_low_stock_and_waiting_shipments_need_attention(admin_client, user):
    store = store_at(0)
    zone_for(store)
    _, variant = create_product(stock=3, store=store)
    Inventory.objects.filter(variant=variant).update(low_stock_threshold=5)
    packed_order(user, (variant, 1), km_north=1)

    data = admin_client.get("/api/admin/summary/").data
    assert data["inventory"] == {"low_stock": 1, "out_of_stock": 0}
    assert data["delivery"]["waiting_for_rider"] == 1
    codes = {a["code"]: a["count"] for a in data["attention"]}
    assert codes["low_stock"] == 1
    assert codes["waiting_for_rider"] == 1


def test_analytics_totals_categories_and_products(shop, admin_client):
    data = admin_client.get("/api/admin/analytics/").data
    revenue = shop["delivered"].grand_total + shop["online"].grand_total
    totals = data["totals"]

    assert (totals["orders"], totals["paid_orders"], totals["cancelled"], totals["delivered"]) == (3, 2, 1, 1)
    assert totals["revenue"] == str(revenue)
    assert totals["net_revenue"] == str(revenue)
    assert totals["average_order_value"] == str((revenue / 2).quantize(Decimal("0.01")))
    assert totals["cancellation_rate"] == 33.3
    assert totals["payment_methods"] == {"cod": 2, "online": 1}

    assert data["period"]["group_by"] == "day"
    assert len(data["series"]) == 30
    assert sum(row["orders"] for row in data["series"]) == 3
    assert sum(Decimal(row["revenue"]) for row in data["series"]) == revenue

    # The cancelled primer is not a sale: drills 3 × 1000, primer 2 × 300.
    assert [(c["category"], c["units"], c["sales"]) for c in data["category_sales"]] == [
        ("Tools", 3, "3000.00"),
        ("Paint", 2, "600.00"),
    ]
    assert [c["share"] for c in data["category_sales"]] == [83.3, 16.7]
    assert [(p["name"], p["units"], p["orders"], p["sales"]) for p in data["top_products"]] == [
        ("Drill", 3, 2, "3000.00"),
        ("Primer", 2, 1, "600.00"),
    ]
    assert [(p["name"], p["units"]) for p in data["low_performing_products"]] == [
        ("Dusty Shelf Item", 0),
        ("Primer", 2),
        ("Drill", 3),
    ]
    assert data["cancellations"]["count"] == 1
    assert data["cancellations"]["value"] == str(shop["cancelled"].grand_total)
    assert data["cancellations"]["reasons"] == [{"reason": "Ordered by mistake", "count": 1}]


def test_analytics_by_period_and_date_range(shop, admin_client):
    # Move the delivered order 40 days back: outside the default period, inside a longer one.
    then = timezone.now() - timedelta(days=40)
    Order.objects.filter(pk=shop["delivered"].pk).update(created_at=then)

    recent = admin_client.get("/api/admin/analytics/").data
    assert recent["totals"]["orders"] == 2
    assert recent["totals"]["revenue"] == str(shop["online"].grand_total)

    first = (timezone.localdate() - timedelta(days=59)).isoformat()
    for period, minimum in (("week", 8), ("month", 2)):
        data = admin_client.get(f"/api/admin/analytics/?from={first}&group_by={period}").data
        assert data["period"]["group_by"] == period
        assert len(data["series"]) >= minimum
        assert sum(row["orders"] for row in data["series"]) == 3
        assert data["totals"]["orders"] == 3
    assert admin_client.get(f"/api/admin/analytics/?from={first}").data["period"]["group_by"] == "week"

    one_day = timezone.localtime(then).date().isoformat()
    data = admin_client.get(f"/api/admin/analytics/?from={one_day}&to={one_day}").data
    assert data["totals"]["orders"] == 1
    assert len(data["series"]) == 1


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("from=yesterday", "invalid_date"),
        ("from=2026-02-30", "invalid_date"),
        ("from=2026-05-10&to=2026-05-01", "invalid_date"),
        ("from=2020-01-01&to=2026-01-01", "range_too_long"),
    ],
)
def test_analytics_rejects_bad_periods(admin_client, query, code):
    response = admin_client.get(f"/api/admin/analytics/?{query}")
    assert response.status_code == 400
    assert response.data["error"]["code"] == code


def test_analytics_is_limited_to_the_managers_stores(shop, staff_client, staff_user, other_user, admin_client):
    other = store_at(40, name="Hadapsar")
    zone_for(other)
    other.managers.add(staff_user)
    _, saw = create_product(name="Saw", price="700.00", mrp="700.00", stock=5, store=other)
    packed_order(other_user, (saw, 1), km_north=41)

    mine = staff_client.get("/api/admin/analytics/").data
    assert mine["totals"]["orders"] == 1
    assert [p["name"] for p in mine["top_products"]] == ["Saw"]
    assert admin_client.get("/api/admin/analytics/").data["totals"]["orders"] == 4
    one = admin_client.get(f"/api/admin/analytics/?store={other.pk}").data
    assert one["totals"]["orders"] == 1


def test_delivery_performance_and_cash_with_riders(admin_client, admin_user, user, other_user):
    store = store_at(0, name="Kothrud")
    zone_for(store)
    _, variant = create_product(price="400.00", mrp="400.00", stock=10, store=store)
    rider = create_partner(store, max_active_assignments=2)

    done = packed_order(user, (variant, 1), km_north=1)
    job = assign(done.shipments.get(), rider, actor=admin_user)
    advance(job, "out_for_delivery")
    deliver_job(job)

    failed = packed_order(other_user, (variant, 1), km_north=1)
    from apps.delivery import workflow

    job2 = assign(failed.shipments.get(), rider, actor=admin_user)
    advance(job2, "out_for_delivery")
    workflow.fail_delivery(job2.pk, rider=rider.user, reason_code="customer_unavailable", note="Nobody home")

    data = admin_client.get("/api/admin/analytics/").data["delivery"]
    assert data["all"]["delivered"] == 1
    assert data["all"]["on_time"] == 1
    assert data["all"]["on_time_rate"] == 100.0
    assert data["first_attempt_rate"] == 100.0
    assert data["delivered_by_partners"] == 1
    assert data["failed_attempts"] == 1
    assert data["failure_reasons"] == [{"code": "customer_unavailable", "label": "Customer not available", "count": 1}]
    assert data["fast"]["delivered"] + data["standard"]["delivered"] == 1

    done.refresh_from_db()
    summary = admin_client.get("/api/admin/summary/").data
    assert summary["delivery"]["cash_with_riders"] == str(done.grand_total)
    assert summary["orders"]["delivery_failed"] == 1
    codes = {a["code"] for a in summary["attention"]}
    assert {"cash_with_riders", "failed_deliveries"} <= codes

    riders = admin_client.get("/api/admin/riders/").data["results"]
    assert riders[0]["cash_in_hand"] == str(done.grand_total)
    assert (riders[0]["delivered"], riders[0]["delivered_today"], riders[0]["failed"]) == (1, 1, 1)
    assert admin_client.get("/api/admin/jobs/?status=failed").data["count"] == 1
    assert admin_client.get("/api/admin/jobs/?status=completed").data["count"] == 1


def test_weeks_start_on_monday_and_months_on_the_first():
    from datetime import date

    assert bucket_start(date(2026, 9, 30), "week") == date(2026, 9, 28)
    assert bucket_start(date(2026, 9, 30), "month") == date(2026, 9, 1)
    assert buckets(date(2026, 11, 20), date(2027, 2, 3), "month") == [
        date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1),
    ]  # fmt: skip
    assert len(buckets(date(2026, 9, 1), date(2026, 9, 30), "day")) == 30
