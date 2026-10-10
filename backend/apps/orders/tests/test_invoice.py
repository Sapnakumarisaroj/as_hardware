"""Printable invoice: built from the order's snapshots, GST per line, tax invoice only with a seller GSTIN."""

from decimal import Decimal

import pytest

from apps.core.testing import create_product, create_store
from apps.core.validators import gstin_checksum
from apps.orders.invoice import build_invoice
from apps.orders.models import Order

from .helpers import order_with

pytestmark = pytest.mark.django_db


def _gstin(state: str, pan: str = "AAGCB7383J") -> str:
    body = f"{state}{pan}1Z"
    return body + gstin_checksum(body)


@pytest.fixture
def order(user):
    store = create_store()
    _, hinge = create_product(name="Soft-close Hinge", price="118.00", mrp="150.00", stock=50, store=store)
    order, _ = order_with(user, (hinge, 5))
    return order


def test_customer_gets_html_invoice_without_seller_gstin(auth_client, order):
    res = auth_client.get(f"/api/orders/{order.order_number}/invoice/")
    assert res.status_code == 200
    assert res["Content-Type"].startswith("text/html")
    assert res["Cache-Control"] == "private, no-store"
    html = res.content.decode()
    assert "Order receipt" in html and "Tax invoice" not in html
    assert "GSTIN has not been configured" in html
    assert order.order_number in html and "Soft-close Hinge" in html


def test_tax_invoice_with_gstins_splits_cgst_sgst(auth_client, user, order, settings):
    settings.INVOICE_SELLER_NAME = "AS Hardware"
    settings.INVOICE_SELLER_GSTIN = _gstin("29")
    Order.objects.filter(pk=order.pk).update(
        address_snapshot={
            **order.address_snapshot,
            "business_name": "Asha Interiors",
            "gstin": _gstin("29", "ABCDE1234F"),
        }
    )
    html = auth_client.get(f"/api/orders/{order.order_number}/invoice/").content.decode()
    assert "Tax invoice" in html and "Asha Interiors" in html
    assert "CGST" in html and "SGST" in html and "IGST" not in html

    data = build_invoice(Order.objects.get(pk=order.pk))
    assert data["split"] == "intra"
    line = data["lines"][0]
    assert line.gross == Decimal("590.00")  # 5 × 118, no discounts
    assert line.gst == Decimal("90.00")  # 18 % included: 590 × 18 / 118
    assert line.taxable == Decimal("500.00")
    assert sum(row["gst"] for row in data["rates"]) == Order.objects.get(pk=order.pk).tax_total


def test_other_state_buyer_is_igst(user, order, settings):
    settings.INVOICE_SELLER_GSTIN = _gstin("29")
    order.address_snapshot = {**order.address_snapshot, "gstin": _gstin("27", "ABCDE1234F")}
    assert build_invoice(order)["split"] == "inter"
    order.address_snapshot = {**order.address_snapshot, "gstin": ""}
    assert build_invoice(order)["split"] == ""  # no buyer GSTIN: state isn't guessed


def test_business_profile_used_when_address_has_none(user, order):
    user.profile.business_name = "Asha Interiors"
    user.profile.save()
    assert build_invoice(order)["buyer"]["business_name"] == "Asha Interiors"


def test_no_invoice_for_pending_or_cancelled_or_other_users(auth_client, api_client, other_user, order):
    api_client.force_authenticate(other_user)
    assert api_client.get(f"/api/orders/{order.order_number}/invoice/").status_code == 404
    Order.objects.filter(pk=order.pk).update(status="cancelled")
    res = auth_client.get(f"/api/orders/{order.order_number}/invoice/")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "invoice_unavailable"


def test_template_escapes_customer_text(auth_client, order):
    Order.objects.filter(pk=order.pk).update(
        address_snapshot={**order.address_snapshot, "business_name": "<script>alert(1)</script>"}
    )
    html = auth_client.get(f"/api/orders/{order.order_number}/invoice/").content.decode()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
