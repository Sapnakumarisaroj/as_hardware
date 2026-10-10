"""Printable invoice: GET /api/orders/<number>/invoice/ → an HTML page the customer prints or saves
as PDF from the browser (no PDF library).

Everything comes from the order's own snapshots (lines, address, totals), never from today's
catalogue. GST is included in every price; each line's tax is worked out on its net amount after
offers, coupon and credits, exactly as `pricing.calculate_totals` did at checkout, and the total
GST printed is the order's stored `tax_total`.

It is a GST tax invoice only when the shop's own GSTIN is configured (`INVOICE_SELLER_GSTIN`);
otherwise the page is titled "Order receipt" and says why. Nothing is made up: blank seller
details stay blank. The buyer's business name and GSTIN come from the delivery address snapshot,
else from the customer's business profile at the time the invoice is printed.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from apps.core.exceptions import ConflictError
from apps.core.money import ZERO, included_tax, q

from .models import Order, OrderStatus

# Orders that never became a sale have no invoice.
NO_INVOICE = {OrderStatus.PENDING, OrderStatus.CANCELLED}


@dataclass(frozen=True)
class InvoiceLine:
    name: str
    sku: str
    hsn_code: str
    quantity: int
    unit: str
    unit_price: Decimal
    gross: Decimal  # what was paid for the line (after offers, coupon, credits), GST inclusive
    gst_rate: Decimal
    gst: Decimal
    taxable: Decimal


def _seller() -> dict:
    return {
        "name": getattr(settings, "INVOICE_SELLER_NAME", "") or "",
        "address": getattr(settings, "INVOICE_SELLER_ADDRESS", "") or "",
        "gstin": (getattr(settings, "INVOICE_SELLER_GSTIN", "") or "").upper(),
    }


def _buyer(order: Order) -> dict:
    address = order.address_snapshot or {}
    profile = getattr(order.user, "profile", None)
    return {
        "name": address.get("name") or order.user.get_full_name(),
        "business_name": address.get("business_name") or (profile.business_name if profile else ""),
        "gstin": (address.get("gstin") or (profile.gstin if profile else "") or "").upper(),
        "address": address,
    }


def _lines(order: Order) -> list[InvoiceLine]:
    items = list(order.items.all())
    subtotal = sum((item.line_total for item in items), ZERO)
    after_offers = subtotal - order.offer_discount
    paid = after_offers - order.coupon_discount - order.credit_discount
    factor = (paid / after_offers) if after_offers else ZERO
    lines = []
    for item in items:
        gross = q((item.line_total - min(item.offer_discount, item.line_total)) * factor)
        gst = included_tax(gross, item.gst_rate)
        name = f"{item.product_name} – {item.variant_name}" if item.variant_name else item.product_name
        lines.append(
            InvoiceLine(
                name=name,
                sku=item.sku,
                hsn_code=item.hsn_code,
                quantity=item.quantity,
                unit=item.unit,
                unit_price=item.unit_price,
                gross=gross,
                gst_rate=item.gst_rate,
                gst=gst,
                taxable=gross - gst,
            )
        )
    return lines


def _tax_split(seller_gstin: str, buyer: dict) -> str:
    """'intra' (CGST + SGST), 'inter' (IGST) or '' when the place of supply can't be told.

    The state is the first two digits of a GSTIN; for a buyer without one we don't guess from the
    address text."""
    if not seller_gstin or not buyer["gstin"]:
        return ""
    return "intra" if seller_gstin[:2] == buyer["gstin"][:2] else "inter"


def build_invoice(order: Order) -> dict:
    if order.status in NO_INVOICE:
        raise ConflictError("An invoice is available once the order is confirmed.", code="invoice_unavailable")
    seller, buyer = _seller(), _buyer(order)
    lines = _lines(order)
    by_rate: dict[Decimal, dict] = defaultdict(lambda: {"taxable": ZERO, "gst": ZERO})
    for line in lines:
        by_rate[line.gst_rate]["taxable"] += line.taxable
        by_rate[line.gst_rate]["gst"] += line.gst
    split = _tax_split(seller["gstin"], buyer)
    rates = [
        {
            "rate": rate,
            "taxable": q(row["taxable"]),
            "gst": q(row["gst"]),
            "half_rate": rate / 2,
            "half": q(row["gst"] / 2),
        }
        for rate, row in sorted(by_rate.items())
    ]
    return {
        "order": order,
        "is_tax_invoice": bool(seller["gstin"]),
        "seller": seller,
        "buyer": buyer,
        "lines": lines,
        "rates": rates,
        "split": split,
        "printed_at": timezone.localtime(),
        "invoice_date": timezone.localtime(order.delivered_at or order.created_at),
    }


def render_invoice(order: Order) -> str:
    return render_to_string("orders/invoice.html", build_invoice(order))
