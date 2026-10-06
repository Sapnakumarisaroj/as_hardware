"""Every notification the shop sends, in one place (Phase 23).

An event names who it is for, the variables its message may use, the default words, the channels it
goes to unless an administrator changes them, and where it links to in the app. Code raises events
with `notify(user, event=..., context={...})`; nothing else composes customer messages.

Variables every message may use: `customer_name`, `shop_name`, `link` (the full URL of the related
page). Words in `{braces}` are replaced; an unknown variable is refused when a template is saved.

`secret` variables (the delivery code) are filled in only at the moment of sending and stored as
"••••••" in the delivery log, so the database never holds a usable code.
"""

from dataclasses import dataclass, field

IN_APP, EMAIL, WHATSAPP, SMS = "in_app", "email", "whatsapp", "sms"
ALL_CHANNELS = (IN_APP, EMAIL, WHATSAPP, SMS)
COMMON_VARIABLES = ("customer_name", "shop_name", "link")

CUSTOMER, RIDER, STAFF = "customer", "rider", "staff"

# Categories a customer may switch off. Critical events (money, delivery codes, failed deliveries,
# cancellations) ignore this: they always arrive on the channels the customer has on.
CATEGORIES = {
    "orders": "Order updates",
    "delivery": "Delivery progress (rider, ETA, picked up)",
    "payments": "Payments and refunds",
    "returns": "Returns",
    "support": "Support replies",
    "loyalty": "Credits and cashback",
    "work": "Work alerts (staff and delivery partners)",
}


@dataclass(frozen=True)
class Event:
    key: str
    label: str
    category: str
    audience: str
    title: str
    body: str
    variables: tuple[str, ...] = ()
    channels: tuple[str, ...] = (IN_APP,)  # on by default
    short: str = ""  # WhatsApp/SMS text when it should differ from `body`
    whatsapp_template: str = ""  # the approved template name used with a real WhatsApp provider
    link: str = ""  # app path; {variables} from the event data
    critical: bool = False
    secret: tuple[str, ...] = ()
    allowed: tuple[str, ...] = field(default=ALL_CHANNELS)

    @property
    def all_variables(self) -> tuple[str, ...]:
        return (*COMMON_VARIABLES, *self.variables)

    def default_text(self, channel: str) -> tuple[str, str]:
        if channel in (WHATSAPP, SMS):
            return self.title, self.short or self.body
        return self.title, self.body


ORDER = "/account/orders/{order_number}"
STAFF_ORDER = "/admin/orders/{order_number}"
_CUSTOMER_MESSAGING = (IN_APP, EMAIL, WHATSAPP)

_EVENTS = [
    # --- Orders ---------------------------------------------------------------------------------
    Event(
        "order.placed",
        "Order placed (payment pending)",
        "orders",
        CUSTOMER,
        "Order {order_number} placed — payment pending",
        "Complete the payment of ₹{amount} to confirm your order.",
        ("order_number", "amount"),
        link="/orders/{order_number}/pay",
    ),
    Event(
        "order.confirmed",
        "Order confirmed (cash on delivery)",
        "orders",
        CUSTOMER,
        "Order {order_number} confirmed",
        "Thank you! Your order of ₹{amount} ({payment_method}) is confirmed. {delivery_sentence}",
        ("order_number", "amount", "payment_method", "delivery_sentence"),
        _CUSTOMER_MESSAGING,
        short="Hi {customer_name}, your {shop_name} order {order_number} of ₹{amount} is confirmed. "
        "{delivery_sentence} Track it: {link}",
        whatsapp_template="order_confirmed",
        link=ORDER,
    ),
    Event(
        "payment.succeeded",
        "Payment received, order confirmed",
        "payments",
        CUSTOMER,
        "Payment received — order {order_number} confirmed",
        "We received ₹{amount}. Your order is confirmed. {delivery_sentence}",
        ("order_number", "amount", "delivery_sentence"),
        _CUSTOMER_MESSAGING,
        short="Hi {customer_name}, we received ₹{amount} for {shop_name} order {order_number}. "
        "Your order is confirmed. {delivery_sentence} Track it: {link}",
        whatsapp_template="payment_received",
        link=ORDER,
        critical=True,
    ),
    Event(
        "payment.failed",
        "Payment failed",
        "payments",
        CUSTOMER,
        "Payment failed for order {order_number}",
        "Your payment did not go through and no money was taken. You can retry from your orders page.",
        ("order_number",),
        link="/orders/{order_number}/pay",
        critical=True,
    ),
    Event(
        "order.accepted",
        "Store accepted the order",
        "delivery",
        CUSTOMER,
        "{store_name} is preparing order {order_number}",
        "The store has accepted your order and is getting it ready.",
        ("order_number", "store_name"),
        link=ORDER,
    ),
    Event(
        "order.packed",
        "Order packed",
        "delivery",
        CUSTOMER,
        "Order {order_number} is packed",
        "Your order is packed and waiting for a delivery partner.",
        ("order_number",),
        link=ORDER,
    ),
    Event(
        "delivery.rider_assigned",
        "Delivery partner assigned",
        "delivery",
        CUSTOMER,
        "{rider_name} will deliver order {order_number}",
        "A delivery partner has been assigned to your order and will pick it up from {store_name}.",
        ("order_number", "rider_name", "store_name"),
        link=ORDER,
    ),
    Event(
        "order.picked_up",
        "Rider picked up the order",
        "delivery",
        CUSTOMER,
        "Order {order_number} picked up",
        "{rider_name} has collected your order from {store_name}.",
        ("order_number", "rider_name", "store_name"),
        link=ORDER,
    ),
    Event(
        "order.out_for_delivery",
        "Out for delivery",
        "delivery",
        CUSTOMER,
        "Order {order_number} is on its way",
        "{rider_name} is bringing your order. Open the order page to see your delivery code and give it to the "
        "delivery partner at the door. Never share it on a call.",
        ("order_number", "rider_name"),
        _CUSTOMER_MESSAGING,
        short="Hi {customer_name}, your {shop_name} order {order_number} is out for delivery with {rider_name}. "
        "Track it: {link}",
        whatsapp_template="out_for_delivery",
        link=ORDER,
    ),
    Event(
        "delivery.otp",
        "Delivery code",
        "delivery",
        CUSTOMER,
        "Delivery code for order {order_number}",
        "Your delivery code for order {order_number} is {otp}. Give it to the delivery partner only at your "
        "door, never on a call.",
        ("order_number", "otp"),
        (WHATSAPP, SMS),
        whatsapp_template="delivery_code",
        link=ORDER,
        critical=True,
        secret=("otp",),
        allowed=(WHATSAPP, SMS),
    ),
    Event(
        "delivery.delayed",
        "Delivery running late",
        "delivery",
        CUSTOMER,
        "Order {order_number} is running late",
        "Sorry — your order is taking longer than we estimated. The store is on it and we'll update you here.",
        ("order_number",),
        (IN_APP, EMAIL),
        short="Hi {customer_name}, sorry, your {shop_name} order {order_number} is running late. Track it: {link}",
        whatsapp_template="delivery_delayed",
        link=ORDER,
    ),
    Event(
        "order.delivered",
        "Delivered",
        "orders",
        CUSTOMER,
        "Order {order_number} delivered",
        "Your order has been delivered. Thank you for shopping with us!",
        ("order_number",),
        _CUSTOMER_MESSAGING,
        short="Hi {customer_name}, your {shop_name} order {order_number} has been delivered. Thank you! "
        "Need help or a return? {link}",
        whatsapp_template="order_delivered",
        link=ORDER,
    ),
    Event(
        "order.part_delivered",
        "Part of the order delivered",
        "orders",
        CUSTOMER,
        "Part of order {order_number} delivered",
        "The items from {store_name} have been delivered. The rest of your order is still on its way.",
        ("order_number", "store_name"),
        (IN_APP, EMAIL),
        link=ORDER,
    ),
    Event(
        "delivery.failed",
        "Delivery attempt failed",
        "delivery",
        CUSTOMER,
        "We couldn't deliver order {order_number}",
        "Our delivery partner could not complete the delivery ({reason}). The store will contact you to arrange "
        "another attempt.",
        ("order_number", "reason"),
        _CUSTOMER_MESSAGING,
        whatsapp_template="delivery_failed",
        link=ORDER,
        critical=True,
    ),
    Event(
        "delivery.redispatched",
        "Sent out again",
        "delivery",
        CUSTOMER,
        "Order {order_number} is being sent again",
        "{rider_name} will try the delivery again.",
        ("order_number", "rider_name"),
        (IN_APP, WHATSAPP),
        short="Hi {customer_name}, we're sending {shop_name} order {order_number} again with {rider_name}. {link}",
        whatsapp_template="delivery_retry",
        link=ORDER,
    ),
    Event(
        "order.cancelled",
        "Order cancelled",
        "orders",
        CUSTOMER,
        "Order {order_number} cancelled",
        "Your order has been cancelled. {refund_sentence}",
        ("order_number", "refund_sentence"),
        _CUSTOMER_MESSAGING,
        whatsapp_template="order_cancelled",
        link=ORDER,
        critical=True,
    ),
    Event(
        "order.expired",
        "Cancelled: payment not completed",
        "orders",
        CUSTOMER,
        "Order {order_number} cancelled — payment not completed",
        "We didn't receive the payment in time, so the order was cancelled and the items released. No money was taken.",
        ("order_number",),
        (IN_APP, EMAIL),
        link=ORDER,
        critical=True,
    ),
    Event(
        "order.reorder",
        "Buy again",
        "orders",
        CUSTOMER,
        "Items from order {order_number} are in your cart",
        "{item_count} item(s) from order {order_number} were added to your cart at today's prices.",
        ("order_number", "item_count"),
        short="Hi {customer_name}, {item_count} item(s) from your {shop_name} order {order_number} are in your "
        "cart: {link}",
        whatsapp_template="reorder_ready",
        link="/cart",
    ),
    # --- Money back ------------------------------------------------------------------------------
    Event(
        "refund.initiated",
        "Refund started",
        "payments",
        CUSTOMER,
        "Refund of ₹{amount} started",
        "We've started a refund of ₹{amount} for order {order_number}. We'll tell you when it's paid.",
        ("order_number", "amount"),
        _CUSTOMER_MESSAGING,
        whatsapp_template="refund_started",
        link=ORDER,
        critical=True,
    ),
    Event(
        "refund.processed",
        "Refund completed",
        "payments",
        CUSTOMER,
        "Refund of ₹{amount} processed",
        "Your refund of ₹{amount} for order {order_number} has been paid {refund_method}. {bank_note}",
        ("order_number", "amount", "refund_method", "bank_note"),
        _CUSTOMER_MESSAGING,
        whatsapp_template="refund_completed",
        link=ORDER,
        critical=True,
    ),
    Event(
        "refund.delayed",
        "Refund pending",
        "payments",
        CUSTOMER,
        "Your refund of ₹{amount} is taking longer",
        "The refund for order {order_number} didn't go through on the first try. The store is handling it and "
        "you don't need to do anything.",
        ("order_number", "amount"),
        (IN_APP, EMAIL),
        link=ORDER,
        critical=True,
    ),
    # --- Returns ---------------------------------------------------------------------------------
    Event(
        "return.requested",
        "Return requested",
        "returns",
        CUSTOMER,
        "Return {return_number} requested",
        "We received your return request for order {order_number}. We'll review it shortly.",
        ("order_number", "return_number"),
        whatsapp_template="return_update",
        link="/account/returns",
    ),
    Event(
        "return.approved",
        "Return approved",
        "returns",
        CUSTOMER,
        "Return {return_number} approved",
        "Your return was approved. Please hand the items over at pickup or at the store; a refund of ₹{amount} "
        "starts once we receive them.",
        ("order_number", "return_number", "amount"),
        _CUSTOMER_MESSAGING,
        whatsapp_template="return_update",
        link="/account/returns",
    ),
    Event(
        "return.rejected",
        "Return rejected",
        "returns",
        CUSTOMER,
        "Return {return_number} rejected",
        "We couldn't accept your return: {reason}",
        ("order_number", "return_number", "reason"),
        _CUSTOMER_MESSAGING,
        whatsapp_template="return_update",
        link="/account/returns",
    ),
    Event(
        "return.received",
        "Return completed",
        "returns",
        CUSTOMER,
        "Return {return_number} received",
        "We received your returned items. A refund of ₹{amount} has been initiated {refund_method}.",
        ("order_number", "return_number", "amount", "refund_method"),
        _CUSTOMER_MESSAGING,
        whatsapp_template="return_update",
        link="/account/returns",
    ),
    # --- Support and loyalty ---------------------------------------------------------------------
    Event(
        "support.reply",
        "Support reply",
        "support",
        CUSTOMER,
        "Reply from {shop_name} support",
        "{agent_name} replied to “{subject}”: {message}",
        ("subject", "agent_name", "message"),
        _CUSTOMER_MESSAGING,
        short="Hi {customer_name}, {shop_name} support replied to “{subject}”: {message}",
        whatsapp_template="support_reply",
    ),
    Event(
        "loyalty.credit_available",
        "Credit ready to use",
        "loyalty",
        CUSTOMER,
        "₹{amount} credit is ready to use",
        "{description}. Use it at checkout within {expiry_days} days.",
        ("amount", "description", "expiry_days"),
        link="/account/wallet",
    ),
    # --- Delivery partners -----------------------------------------------------------------------
    Event(
        "delivery.assigned",
        "New job (rider)",
        "work",
        RIDER,
        "New job: order {order_number}",
        "{job_kind} for order {order_number} was assigned to you. Open the rider app to accept it.",
        ("order_number", "job_kind"),
        link="/rider/jobs/{assignment_id}",
        allowed=(IN_APP, WHATSAPP, SMS),
    ),
    Event(
        "delivery.unassigned",
        "Job removed (rider)",
        "work",
        RIDER,
        "Job removed: order {order_number}",
        "The store took order {order_number} off your list. {note}",
        ("order_number", "note"),
        link="/rider",
        allowed=(IN_APP, WHATSAPP, SMS),
    ),
    Event(
        "order.ready_for_pickup",
        "Ready for pickup (rider)",
        "work",
        RIDER,
        "Order {order_number} is ready for pickup",
        "{store_name} has packed order {order_number}. You can collect it now.",
        ("order_number", "store_name"),
        link="/rider/jobs/{assignment_id}",
        allowed=(IN_APP, WHATSAPP, SMS),
    ),
    # --- Staff ---------------------------------------------------------------------------------
    Event(
        "staff.order_new",
        "New order (staff)",
        "work",
        STAFF,
        "New order {order_number} — ₹{amount}",
        "A {delivery_type} order for {store_name} is waiting to be prepared.",
        ("order_number", "amount", "store_name", "delivery_type"),
        link=STAFF_ORDER,
        allowed=(IN_APP, EMAIL, WHATSAPP),
    ),
    Event(
        "staff.delivery_failed",
        "Delivery failed (staff)",
        "work",
        STAFF,
        "Delivery failed: order {order_number}",
        "The delivery from {store_name} could not be completed ({reason}). Contact the customer and send it again.",
        ("order_number", "store_name", "reason"),
        link=STAFF_ORDER,
        allowed=(IN_APP, EMAIL, WHATSAPP),
    ),
    Event(
        "staff.delivery_delayed",
        "Delivery running late (staff)",
        "work",
        STAFF,
        "Order {order_number} is past its delivery estimate",
        "The customer was told it is running late. Check the order and the rider.",
        ("order_number",),
        link=STAFF_ORDER,
        allowed=(IN_APP, EMAIL, WHATSAPP),
    ),
    Event(
        "staff.return_requested",
        "Return requested (staff)",
        "work",
        STAFF,
        "Return {return_number} to review",
        "The customer asked to return items from order {order_number}.",
        ("order_number", "return_number"),
        link="/admin/returns",
        allowed=(IN_APP, EMAIL, WHATSAPP),
    ),
    Event(
        "staff.refund_failed",
        "Refund failed (staff)",
        "work",
        STAFF,
        "Refund of ₹{amount} failed — order {order_number}",
        "The gateway refused the refund: {reason}. Retry it or pay it by hand from the refunds page.",
        ("order_number", "amount", "reason"),
        (IN_APP, EMAIL),
        link="/admin/refunds",
        allowed=(IN_APP, EMAIL, WHATSAPP),
    ),
]

EVENTS: dict[str, Event] = {event.key: event for event in _EVENTS}


def get_event(key: str) -> Event:
    try:
        return EVENTS[key]
    except KeyError as exc:
        raise KeyError(f"Unknown notification event '{key}'. Add it to apps/notifications/events.py.") from exc
