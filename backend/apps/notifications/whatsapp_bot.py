"""Keyword auto-replies to WhatsApp messages (English and Hinglish; deterministic, no LLM).

    "order status" / "mera order kahan hai"   → the customer's latest order, its status and tracking link
    "reorder" / "dobara" / "same order"       → the last delivered order back in the cart (never placed)
    "price of 18mm plywood" / "kabza hai?"     → up to 3 real products: today's price and stock wording
    "help" / "agent" / "support"               → nothing: the conversation waits for staff
    anything else                              → nothing: the conversation waits for staff

Every answer comes from the database through the same services the website uses. A reply is a
`SupportMessage(sender_type="bot")` sent as a free-form WhatsApp message, which WhatsApp allows only
within 24 hours of the customer's last message (`within_session`). Customers who turned WhatsApp off
(or said STOP) get no replies; order and cart answers need the phone to belong to an account.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

SESSION_WINDOW = timedelta(hours=24)
MAX_PRODUCTS = 3

HELP, ORDER_STATUS, REORDER, PRODUCT = "help", "order_status", "reorder", "product"

_HELP_WORDS = {"help", "agent", "support", "human", "madad", "call", "complaint", "baat"}
_REORDER = re.compile(
    r"\b(re-?order|dobara|dubara|same order|repeat order|order again|phir se( order)?|wahi order|buy again)\b"
)
_ORDER_STATUS = re.compile(
    r"\b(order status|status|track(ing)?|where is my order|mera order|my order|order kahan|order kab|"
    r"kab (aayega|ayega|milega)|kahan (hai|pahuncha))\b"
)
_PRODUCT_MARKERS = {
    "price",
    "prices",
    "rate",
    "rates",
    "cost",
    "kitna",
    "kitne",
    "kitni",
    "daam",
    "dam",
    "available",
    "availability",
    "stock",
    "milega",
    "milegi",
    "milenge",
    "hai",
    "hain",
    "have",
}
# Words of the question itself, removed before searching the catalogue.
_QUESTION_WORDS = _PRODUCT_MARKERS | {
    "of",
    "for",
    "the",
    "a",
    "an",
    "is",
    "are",
    "do",
    "you",
    "what",
    "whats",
    "how",
    "much",
    "kya",
    "ka",
    "ki",
    "ke",
    "ko",
    "me",
    "mein",
    "please",
    "pls",
    "plz",
    "bhai",
    "sir",
    "ji",
    "bata",
    "batao",
    "bataiye",
    "tell",
    "in",
    "any",
    "aapke",
    "aapka",
    "paas",
    "pass",
    "per",
    "piece",
    "pc",
}


@dataclass(frozen=True)
class Intent:
    kind: str
    query: str = ""


def _words(text: str) -> list[str]:
    return re.findall(r"[\w./-]+", text.lower())


def detect(text: str) -> Intent | None:
    """What the customer is asking for, or None when staff should answer."""
    lowered = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not lowered:
        return None
    words = _words(lowered)
    if _HELP_WORDS & set(words):
        return Intent(HELP)
    if _REORDER.search(lowered):
        return Intent(REORDER)
    if _ORDER_STATUS.search(lowered):
        return Intent(ORDER_STATUS)
    if _PRODUCT_MARKERS & set(words) or lowered.endswith("?"):
        query = " ".join(w for w in words if w not in _QUESTION_WORDS)
        query = re.sub(r"(\d+(?:\.\d+)?)\s*(mm|cm|inch|in|ft|kg|g|l|ltr|m|w|amp|a)\b", r"\1 \2", query).strip()
        if query:
            return Intent(PRODUCT, query)
    return None


def within_session(last_customer_message_at: datetime | None, now: datetime | None = None) -> bool:
    """WhatsApp's customer-service window: free-form messages only within 24 h of the customer's last one."""
    if last_customer_message_at is None:
        return False
    return (now or timezone.now()) - last_customer_message_at < SESSION_WINDOW


def _link(path: str) -> str:
    return settings.FRONTEND_URL + path


def _rupees(value) -> str:
    return f"₹{value:,.0f}" if value == value.to_integral() else f"₹{value:,.2f}"


# --- Answers -------------------------------------------------------------------------------------


@dataclass
class Reply:
    text: str
    product_id: int | None = None


def answer(intent: Intent, user) -> Reply | None:
    if intent.kind == ORDER_STATUS:
        return _order_status(user) if user else None
    if intent.kind == REORDER:
        return _reorder(user) if user else None
    if intent.kind == PRODUCT:
        return _products(intent.query)
    return None


def _order_status(user) -> Reply:
    from apps.orders.models import Order

    order = Order.objects.filter(user=user).order_by("-created_at", "-id").first()
    if order is None:
        return Reply("We couldn't find an order for this number. Reply HELP to talk to our team.")
    return Reply(
        f"Your latest order {order.order_number} is: {order.get_status_display()}.\n"
        f"Track it here: {_link(f'/account/orders/{order.order_number}')}"
    )


def _reorder(user) -> Reply:
    from apps.orders.models import Order, OrderStatus
    from apps.orders.services import reorder

    order = (
        Order.objects.filter(user=user, status=OrderStatus.DELIVERED).order_by("-delivered_at", "-created_at").first()
    )
    if order is None:
        return Reply("You don't have a delivered order to repeat yet. Reply HELP to talk to our team.")
    lines = reorder(order, user=user)
    added = [line for line in lines if line.added]
    skipped = [line for line in lines if not line.added or line.reason]
    parts = []
    if added:
        listed = "\n".join(f"• {line.name} × {line.added}" for line in added[:10])
        parts.append(f"From order {order.order_number}, we put these in your cart at today's prices:\n{listed}")
    else:
        parts.append(f"We couldn't add any items from order {order.order_number} to your cart.")
    if skipped:
        listed = "\n".join(f"• {line.name}: {line.reason}" for line in skipped[:10])
        parts.append(f"Not added in full:\n{listed}")
    parts.append(f"Review your cart and check out here (nothing is ordered until you do): {_link('/cart')}")
    return Reply("\n\n".join(parts))


_STOCK_WORDS = {"in_stock": "In stock", "low_stock": "Only a few left", "out_of_stock": "Out of stock"}


def find_products(query: str) -> list:
    """Up to 3 real catalogue products for the customer's words (the assistant's retrieval service)."""
    from apps.ai.services.intent import _search_words
    from apps.ai.services.retrieval import CatalogRetrievalService

    service = CatalogRetrievalService()
    found = service.search(query, limit=MAX_PRODUCTS)
    if not found:
        terms, _used = _search_words(query)  # Hinglish and trade words: "kabza" → "hinge"
        seen: set[int] = set()
        for term in terms:
            for product in service.search(term, limit=MAX_PRODUCTS):
                if product.pk not in seen:
                    seen.add(product.pk)
                    found.append(product)
    return [p for p in found if p.cheapest_variant_id is not None and p.price is not None][:MAX_PRODUCTS]


def _products(query: str) -> Reply | None:
    from apps.catalog.selectors import stock_status

    products = find_products(query)
    if not products:
        return None  # nothing we can answer: the shop replies
    rows = []
    for product in products:
        price = _rupees(product.price)
        if (product.variant_count or 0) > 1:
            price = f"from {price}"
        stock = _STOCK_WORDS[stock_status(product.stock_total or 0)]
        rows.append(f"• {product.name}: {price} ({stock})\n  {_link(f'/p/{product.slug}')}")
    text = "Here's what we have:\n" + "\n".join(rows) + "\n\nPrices include GST. Reply HELP to talk to our team."
    return Reply(text, product_id=products[0].pk if len(products) == 1 else None)


# --- Sending -------------------------------------------------------------------------------------


def respond(conversation, user, text: str, *, received_at: datetime | None = None) -> bool:
    """Answer one incoming customer message if it is something we can answer. Called inside the
    webhook's transaction; the WhatsApp message itself goes out after commit."""
    from apps.support.models import SupportMessage

    from . import services
    from .events import WHATSAPP

    if not settings.WHATSAPP_AUTO_REPLIES or not services.channel_enabled(WHATSAPP):
        return False
    if user is not None:
        profile = getattr(user, "profile", None)
        if not (profile and profile.whatsapp_opt_in):
            return False  # turned WhatsApp off (or said STOP): silence
    if not within_session(received_at or timezone.now()):
        return False
    intent = detect(text)
    if intent is None or intent.kind == HELP:
        return False
    reply = answer(intent, user)
    if reply is None:
        return False
    if reply.product_id and conversation.product_id is None:
        conversation.product_id = reply.product_id
        conversation.save(update_fields=["product", "updated_at"])
    message = SupportMessage.objects.create(
        conversation=conversation, sender_type=SupportMessage.Sender.BOT, body=reply.text[:4000]
    )
    phone = (user.phone if user else "") or conversation.contact_phone
    transaction.on_commit(lambda: _send(message.pk, phone, reply.text))
    return True


def _send(message_id: int, phone: str, text: str) -> None:
    from apps.support.models import SupportMessage
    from integrations.messaging import MessagingError, get_whatsapp_provider, to_e164

    provider = get_whatsapp_provider()
    if not provider.configured or not phone:
        return
    try:
        result = provider.send_text(to_e164(phone, settings.PHONE_COUNTRY_CODE), text, reference=f"s{message_id}")
    except MessagingError as exc:
        logger.warning("WhatsApp auto-reply %s not sent: %s", message_id, exc)
        return
    SupportMessage.objects.filter(pk=message_id).update(channel_message_id=result.message_id[:120])
