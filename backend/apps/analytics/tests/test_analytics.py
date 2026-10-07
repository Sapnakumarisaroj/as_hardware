"""Phase 24: business reports and the business assistant. Every figure is checked against orders
built in the test; managers see only their stores; the assistant answers from the reports and a
language model can neither invent numbers nor see table rows."""

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.analytics import assistant, reports
from apps.analytics.models import BusinessQuestion
from apps.catalog.models import Brand, Category
from apps.core.testing import create_coupon, create_product
from apps.dashboard.scope import local_day_start
from apps.delivery.tests.helpers import advance, assign, create_partner, deliver_job, packed_order, store_at, zone_for
from apps.inventory.models import Inventory
from apps.orders.models import Order
from apps.orders.returns import approve_return, request_return
from apps.orders.services import cancel_order_by_customer
from apps.orders.tests.helpers import deliver, order_with, pay
from integrations.llm import LLMReply

pytestmark = pytest.mark.django_db


def scope_for(store_ids=None, days=30):
    today = timezone.localdate()
    first = today - timedelta(days=days - 1)
    return reports.Scope(store_ids, first, today, local_day_start(first), local_day_start(today + timedelta(days=1)))


def kpis(data):
    return {k["key"]: k["value"] for k in data["kpis"]}


def rows(data, key):
    return next(t for t in data["tables"] if t["key"] == key)["rows"]


@pytest.fixture
def shop(user, other_user, admin_user):
    """Kothrud: a delivered cash order (drills), a paid online order with a coupon (drill + hinges), and a
    cancelled order. Categories are two levels: Power Tools › Drills and Hinges, Channels & Handles › Hinges."""
    power = Category.objects.create(name="Power Tools & Accessories", slug="power-tools")
    drills = Category.objects.create(name="Drills", slug="drills", parent=power)
    hardware = Category.objects.create(name="Hinges, Channels & Handles", slug="hinges-channels-handles")
    hinges = Category.objects.create(name="Hinges", slug="hinges", parent=hardware)
    forge = Brand.objects.create(name="ForgePro", slug="forgepro")
    fit = Brand.objects.create(name="FitWell", slug="fitwell")
    store = store_at(0, name="Kothrud")
    zone_for(store)
    _, drill = create_product(
        name="Drill",
        price="1000.00",
        mrp="1200.00",
        category=power,
        subcategory=drills,
        brand=forge,
        stock=20,
        store=store,
    )
    _, hinge = create_product(
        name="Hinge",
        price="300.00",
        mrp="400.00",
        category=hardware,
        subcategory=hinges,
        brand=fit,
        stock=20,
        store=store,
    )
    create_product(
        name="Dusty Knob", price="50.00", mrp="60.00", category=hardware, subcategory=hinges, stock=2, store=store
    )
    create_coupon(code="SAVE50", discount_type="fixed", value="50.00", min_order_value="0.00")

    delivered, _ = order_with(user, (drill, 2))
    deliver(delivered, admin_user)
    online, payment = order_with(other_user, (drill, 1), (hinge, 2), method="online", coupon_code="SAVE50")
    pay(online, payment)
    cancelled, _ = order_with(user, (hinge, 1))
    cancel_order_by_customer(cancelled, user=user, reason="Ordered by mistake")
    for order in (delivered, online, cancelled):
        order.refresh_from_db()
    return {
        "store": store,
        "delivered": delivered,
        "online": online,
        "cancelled": cancelled,
        "drill": drill,
        "hinge": hinge,
    }


# --- Reports ----------------------------------------------------------------------------------------


def test_sales_report_matches_the_orders(shop):
    data = reports.build("sales", scope_for())
    revenue = shop["delivered"].grand_total + shop["online"].grand_total
    k = kpis(data)
    assert k["revenue"] == str(revenue) and k["net_revenue"] == str(revenue) and k["paid_orders"] == 2
    assert k["average_order_value"] == str((revenue / 2).quantize(Decimal("0.01")))
    assert k["discounts"] == "50.00"  # the coupon on the online order
    assert sum(Decimal(r["revenue"]) for r in data["series"]) == revenue
    methods = {r["method"]: (r["orders"], r["revenue"]) for r in rows(data, "payment_methods")}
    assert methods == {
        "Cash on delivery": (1, str(shop["delivered"].grand_total)),
        "Online": (1, str(shop["online"].grand_total)),
    }
    assert sum(r["orders"] for r in rows(data, "weekdays")) == 2 and sum(r["orders"] for r in rows(data, "hours")) == 2


def test_orders_products_categories_and_brands(shop):
    orders = reports.build("orders", scope_for())
    assert (kpis(orders)["orders"], kpis(orders)["cancelled"], kpis(orders)["delivered"]) == (3, 1, 1)
    assert kpis(orders)["cancellation_rate"] == 33.3
    assert sum(r["orders"] for r in rows(orders, "statuses")) == 3

    products = reports.build("products", scope_for())
    top = [(r["name"], r["units"], r["sales"]) for r in rows(products, "top")]
    assert top == [("Drill", 3, "3000.00"), ("Hinge", 2, "600.00")]  # the cancelled hinge is not a sale
    assert rows(products, "slow")[0]["name"] == "Dusty Knob" and rows(products, "slow")[0]["stock"] == 2

    categories = reports.build("categories", scope_for())
    assert [(r["category"], r["units"], r["sales"], r["share"]) for r in rows(categories, "categories")] == [
        ("Power Tools & Accessories", 3, "3000.00", 83.3),
        ("Hinges, Channels & Handles", 2, "600.00", 16.7),
    ]
    assert [(r["category"], r["subcategory"]) for r in rows(categories, "subcategories")] == [
        ("Power Tools & Accessories", "Drills"),
        ("Hinges, Channels & Handles", "Hinges"),
    ]
    brands = reports.build("brands", scope_for())
    assert [(r["brand"], r["sales"]) for r in rows(brands, "brands")] == [
        ("ForgePro", "3000.00"),
        ("FitWell", "600.00"),
    ]


def test_customers_offers_returns_stores_and_margin(shop, user, admin_user):
    # An order before the period makes its customer "returning".
    Order.objects.filter(pk=shop["delivered"].pk).update(created_at=timezone.now() - timedelta(days=60))
    customers = reports.build("customers", scope_for())
    k = kpis(customers)
    assert (k["customers"], k["new_customers"], k["returning_customers"]) == (1, 1, 0)
    assert rows(customers, "top")[0]["email"] == "ot•••@example.com"  # masked
    Order.objects.filter(pk=shop["delivered"].pk).update(created_at=timezone.now())
    order_with(user, (shop["drill"], 1))  # a second order for the first customer in the period
    k = kpis(reports.build("customers", scope_for()))
    assert (k["customers"], k["repeat_rate"]) == (2, 50.0)

    offers = reports.build("offers", scope_for())
    assert kpis(offers)["coupon_discount"] == "50.00"
    assert rows(offers, "coupons") == [
        {"code": "SAVE50", "orders": 1, "discount": "50.00", "revenue": str(shop["online"].grand_total)}
    ]

    item = shop["delivered"].items.get()
    ret = request_return(
        shop["delivered"], user=user, items=[{"order_item_id": item.id, "quantity": 1}], reason="defective"
    )
    approve_return(ret, actor=admin_user)
    returns = reports.build("returns", scope_for())
    assert kpis(returns)["returns"] == 1 and kpis(returns)["cancelled"] == 1
    assert rows(returns, "cancellation_reasons") == [{"reason": "Ordered by mistake", "count": 1}]
    assert rows(returns, "products") == [{"product": "Drill", "units": 1, "requests": 1}]
    assert rows(reports.build("products", scope_for()), "top")[0]["returned"] == 1

    stores = rows(reports.build("stores", scope_for()), "stores")
    assert stores[0]["store"] == "Kothrud" and stores[0]["paid_orders"] == 2

    margin = reports.build("margin", scope_for())
    k = kpis(margin)
    paid = [shop["delivered"], shop["online"]]
    assert k["mrp_value"] == str(sum(o.mrp_total for o in paid)) and k["gross_margin"] is None
    assert any("purchase" in note for note in margin["notes"])


def test_inventory_report_values_stock_and_flags_low_items(shop):
    Inventory.objects.filter(variant__product__name="Dusty Knob").update(available_quantity=1, low_stock_threshold=5)
    data = reports.build("inventory", scope_for())
    expected = sum(i.available_quantity * i.variant.price for i in Inventory.objects.select_related("variant"))
    assert kpis(data)["value"] == str(expected.quantize(Decimal("0.01")))
    flagged = [r["product"] for r in rows(data, "attention")]
    assert "Dusty Knob" in flagged
    assert any(r["type"].startswith("Purchase") for r in rows(data, "movements"))


def test_delivery_and_rider_reports(admin_user, user, other_user):
    store = store_at(0, name="Baner")
    zone_for(store)
    _, variant = create_product(price="400.00", mrp="400.00", stock=10, store=store)
    rider = create_partner(store, max_active_assignments=2)
    done = packed_order(user, (variant, 1), km_north=1)
    job = assign(done.shipments.get(), rider, actor=admin_user)
    advance(job, "out_for_delivery")
    deliver_job(job)
    from apps.delivery import workflow

    failed = packed_order(other_user, (variant, 1), km_north=1)
    job2 = assign(failed.shipments.get(), rider, actor=admin_user)
    advance(job2, "out_for_delivery")
    workflow.fail_delivery(job2.pk, rider=rider.user, reason_code="customer_unavailable", note="Nobody home")

    delivery = reports.build("delivery", scope_for())
    assert (kpis(delivery)["delivered"], kpis(delivery)["on_time_rate"], kpis(delivery)["failed_attempts"]) == (
        1,
        100.0,
        1,
    )
    store_row = rows(delivery, "stores")[0]
    assert (store_row["store"], store_row["delivered"], store_row["on_time_rate"]) == ("Baner", 1, 100.0)
    riders = reports.build("riders", scope_for())
    row = rows(riders, "riders")[0]
    done.refresh_from_db()
    assert (row["jobs"], row["delivered"], row["failed"], row["success_rate"]) == (2, 1, 1, 50.0)
    assert row["cod"] == str(done.grand_total)


def test_an_empty_shop_reports_zeros_and_none_not_made_up_numbers(db):
    for key in reports.REPORTS:
        data = reports.build(key, scope_for())
        for value in kpis(data).values():
            assert value in (None, 0, "0.00") or key in ("inventory", "stores"), (key, value)


# --- API and permissions -----------------------------------------------------------------------------


def test_report_api_scopes_managers_to_their_stores(shop, staff_user, staff_client, admin_client, other_user):
    other = store_at(40, name="Hadapsar")
    zone_for(other)
    other.managers.add(staff_user)
    _, saw = create_product(name="Saw", price="700.00", mrp="700.00", stock=5, store=other)
    packed_order(other_user, (saw, 1), km_north=41)

    assert [r["key"] for r in staff_client.get("/api/admin/reports/").json()["results"]][:3] == [
        "sales",
        "orders",
        "products",
    ]
    mine = staff_client.get("/api/admin/reports/products/").json()
    assert [r["name"] for r in rows(mine, "top")] == ["Saw"]
    assert staff_client.get(f"/api/admin/reports/sales/?store={shop['store'].pk}").status_code == 404
    assert kpis(admin_client.get("/api/admin/reports/orders/").json())["orders"] == 4
    assert kpis(admin_client.get(f"/api/admin/reports/orders/?store={other.pk}").json())["orders"] == 1
    assert admin_client.get("/api/admin/reports/nope/").status_code == 404
    assert admin_client.get("/api/admin/reports/sales/?from=2026-02-01&to=2025-01-01").status_code == 400


@pytest.mark.parametrize(
    "url",
    [
        "/api/admin/reports/",
        "/api/admin/reports/sales/",
        "/api/admin/reports/sales/export/",
        "/api/admin/assistant/",
        "/api/admin/assistant/history/",
    ],
)
def test_customers_and_riders_cannot_read_reports(url, auth_client, delivery_user):
    rider = APIClient()
    rider.force_authenticate(delivery_user)
    assert auth_client.get(url).status_code == 403 and rider.get(url).status_code == 403
    assert APIClient().get(url).status_code == 401
    assert auth_client.post("/api/admin/assistant/", {"question": "revenue"}, format="json").status_code == 403


def test_csv_export(shop, admin_client):
    res = admin_client.get("/api/admin/reports/products/export/?table=top")
    assert res.status_code == 200 and res["Content-Type"].startswith("text/csv")
    assert "attachment;" in res["Content-Disposition"] and "products-top-" in res["Content-Disposition"]
    lines = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert lines[1][:3] == ["Product", "Brand", "Units"] and lines[2][0] == "Drill"
    kpi_lines = list(
        csv.reader(
            io.StringIO(admin_client.get("/api/admin/reports/sales/export/?table=kpis").content.decode("utf-8-sig"))
        )
    )
    assert kpi_lines[1] == ["Measure", "Value"] and kpi_lines[2][0] == "Revenue"
    assert admin_client.get("/api/admin/reports/sales/export/?table=nope").status_code == 404


def test_csv_cells_that_look_like_formulas_are_neutralised(shop, admin_client):
    shop["drill"].product.__class__.objects.filter(pk=shop["drill"].product_id).update(name="=HYPERLINK(1)")
    from apps.orders.models import OrderItem

    OrderItem.objects.filter(variant=shop["drill"]).update(product_name="=HYPERLINK(1)")
    text = admin_client.get("/api/admin/reports/products/export/?table=top").content.decode("utf-8-sig")
    assert "'=HYPERLINK(1)" in text and "\n=HYPERLINK" not in text


# --- Assistant ----------------------------------------------------------------------------------------

TODAY = date(2026, 10, 7)


@pytest.mark.parametrize(
    "question,intent",
    [
        ("How much did we sell last month?", "revenue"),
        ("aaj ki bikri kitni hai", "revenue"),
        ("इस महीने की बिक्री", "revenue"),
        ("What are our top 10 products this month?", "top_products"),
        ("sabse zyada bikne wala saman", "top_products"),
        ("Which products are not selling?", "slow_products"),
        ("Which items are low on stock?", "low_stock"),
        ("What is our stock value?", "inventory"),
        ("Which category sells the most?", "categories"),
        ("Which brands sold best last month?", "brands"),
        ("How are our riders performing?", "riders"),
        ("Are deliveries on time?", "delivery"),
        ("Why are orders being cancelled?", "refunds"),
        ("How much discount did we give with coupons?", "offers"),
        ("How many new customers did we get?", "customers"),
        ("Which store has the highest revenue?", "stores"),
        ("What is our average order value?", "aov"),
        ("How many orders did we get today?", "orders"),
        ("What is our profit margin?", "profit"),
    ],
)
def test_questions_reach_the_right_report(question, intent):
    assert assistant.understand(question, stores=[], today=TODAY, use_model=False).intent.key == intent


@pytest.mark.parametrize(
    "question,first,last",
    [
        ("sales today", "2026-10-07", "2026-10-07"),
        ("sales yesterday", "2026-10-06", "2026-10-06"),
        ("sales last 7 days", "2026-10-01", "2026-10-07"),
        ("sales this month", "2026-10-01", "2026-10-07"),
        ("sales last month", "2026-09-01", "2026-09-30"),
        ("pichle mahine ki bikri", "2026-09-01", "2026-09-30"),
        ("sales this week", "2026-10-05", "2026-10-07"),
        ("sales last week", "2026-09-28", "2026-10-04"),
        ("sales in august", "2026-08-01", "2026-08-31"),
        ("sales in december", "2025-12-01", "2025-12-31"),
        ("sales from 2026-09-10 to 2026-09-20", "2026-09-10", "2026-09-20"),
        ("sales", "2026-09-08", "2026-10-07"),  # default: the last 30 days
    ],
)
def test_periods_are_read_from_the_question(question, first, last):
    reading = assistant.understand(question, stores=[], today=TODAY, use_model=False)
    assert (reading.first.isoformat(), reading.last.isoformat()) == (first, last)


def test_answers_quote_the_report_and_are_saved(shop, admin_client):
    res = admin_client.post("/api/admin/assistant/", {"question": "How much did we sell this month?"}, format="json")
    body = res.json()
    revenue = shop["delivered"].grand_total + shop["online"].grand_total
    assert body["intent"] == "revenue" and body["source"] == "rules"
    assert {k["key"]: k["value"] for k in body["kpis"]}["revenue"] == str(revenue)
    assert assistant.inr(revenue) in body["text"]
    assert body["link"].startswith("/admin/reports?report=sales&from=")
    top = admin_client.post("/api/admin/assistant/", {"question": "top 1 products this month"}, format="json").json()
    assert [r["name"] for r in top["table"]["rows"]] == ["Drill"]
    history = admin_client.get("/api/admin/assistant/history/").json()["results"]
    assert [h["question"] for h in history] == ["top 1 products this month", "How much did we sell this month?"]
    assert BusinessQuestion.objects.count() == 2


def test_unknown_questions_get_suggestions_not_guesses(admin_client):
    body = admin_client.post("/api/admin/assistant/", {"question": "write me a poem"}, format="json").json()
    assert body["understood"] is False and body["intent"] is None and body["suggestions"]


def test_comparison_with_the_previous_period(shop):
    Order.objects.filter(pk=shop["delivered"].pk).update(created_at=timezone.now() - timedelta(days=8))
    body = assistant.answer(
        "revenue last 7 days compared to previous period", store_ids=None, stores=[], use_model=False
    )
    c = body["comparison"]
    assert c["current"] == str(shop["online"].grand_total) and c["previous"] == str(shop["delivered"].grand_total)
    assert "Previous 7 days" in body["text"]


def test_naming_a_store_narrows_but_never_widens(shop, staff_user, staff_client, admin_client, other_user):
    other = store_at(40, name="Hadapsar")
    zone_for(other)
    _, saw = create_product(name="Saw", price="700.00", mrp="700.00", stock=5, store=other)
    packed_order(other_user, (saw, 1), km_north=41)
    body = admin_client.post(
        "/api/admin/assistant/", {"question": "orders this month in Hadapsar"}, format="json"
    ).json()
    assert body["store"] == "Hadapsar" and {k["key"]: k["value"] for k in body["kpis"]}["orders"] == 1

    shop["store"].managers.add(staff_user)  # manages Kothrud only
    mine = staff_client.post(
        "/api/admin/assistant/", {"question": "orders this month in Hadapsar"}, format="json"
    ).json()
    assert mine["store"] is None and {k["key"]: k["value"] for k in mine["kpis"]}["orders"] == 3  # Kothrud's
    assert [s["name"] for s in staff_client.get("/api/admin/assistant/").json()["stores"]] == ["Kothrud"]


class FakeModel:
    name, model, available = "fake", "fake-1", True

    def __init__(self, replies):
        self.replies = list(replies)
        self.messages = []

    def chat(self, messages, options=None):
        self.messages.append(messages)
        return LLMReply(content=self.replies.pop(0) if self.replies else "")


def test_a_model_may_route_and_reword_but_not_invent_numbers(shop, monkeypatch):
    fake = FakeModel(['{"intent": "revenue"}', "This month you took ₹99,999.00."])
    monkeypatch.setattr(assistant, "get_llm_provider", lambda: fake)
    body = assistant.answer("how are things looking for us", store_ids=None, stores=[])
    assert body["intent"] == "revenue" and body["source"] == "ai"  # routed by the model
    assert "99,999" not in body["text"] and body["text"].startswith("Sales and revenue")  # invented number refused

    revenue = shop["delivered"].grand_total + shop["online"].grand_total
    good = f"You earned {assistant.inr(revenue)} from 2 paid orders."
    fake = FakeModel([good])
    monkeypatch.setattr(assistant, "get_llm_provider", lambda: fake)
    body = assistant.answer("revenue this month", store_ids=None, stores=[])
    assert body["text"] == good and body["source"] == "ai"
    sent = str(fake.messages)
    assert "other@example.com" not in sent and "Drill" not in sent  # no table rows or customer data


def test_a_model_cannot_choose_a_report_outside_the_list(monkeypatch):
    monkeypatch.setattr(assistant, "get_llm_provider", lambda: FakeModel(['{"intent": "DROP TABLE orders"}']))
    assert assistant.understand("how are things looking for us", stores=[], today=TODAY).intent is None


def test_rupees_use_indian_grouping():
    assert assistant.inr(Decimal("25670269")) == "₹2,56,70,269.00"
    assert assistant.inr(Decimal("999.5")) == "₹999.50"


def test_profit_questions_are_never_reworded_and_say_margin_is_unavailable(shop, monkeypatch):
    fake = FakeModel(["The profit margin is 77.0%."])
    monkeypatch.setattr(assistant, "get_llm_provider", lambda: fake)
    body = assistant.answer("What is our profit margin this month?", store_ids=None, stores=[])
    assert body["intent"] == "profit" and body["source"] == "rules" and fake.messages == []
    assert body["text"].startswith("Profit and gross margin can't be calculated yet")
