"""Razorpay (UPI, cards, net banking, wallets) over its REST API, using only the standard library.

Flow:
1. `create_payment` → POST /v1/orders (amount in paise). The browser opens Razorpay Checkout with
   the *public* key id and the order id from `client_payload`. The key secret never leaves the server.
2. Checkout returns {razorpay_order_id, razorpay_payment_id, razorpay_signature}. `verify_payment`
   checks HMAC-SHA256(order_id|payment_id, key_secret), then fetches the payment from Razorpay and
   checks order id, amount and currency. Authorized payments are captured.
3. Webhooks (`payment.captured`, `payment.failed`, `order.paid`, `refund.*`) are verified with
   HMAC-SHA256(raw body, webhook secret) and de-duplicated by `X-Razorpay-Event-Id`.
4. Refunds carry our reference in `notes`; before creating one we look for an existing refund
   with that reference, so a retried call after a timeout never refunds twice.
"""

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import (
    GatewayError,
    GatewayPayment,
    GatewayRejected,
    InvalidSignature,
    PaymentIntent,
    PaymentProvider,
    RefundResult,
    VerificationResult,
    WebhookEvent,
    from_paise,
    parse_razorpay_style_event,
    to_paise,
)

WEBHOOK_SIGNATURE_HEADER = "X-Razorpay-Signature"
WEBHOOK_EVENT_ID_HEADER = "X-Razorpay-Event-Id"


def hmac_sha256(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


class RazorpayClient:
    def __init__(self, key_id: str, key_secret: str, base_url: str, timeout: float = 20):
        if not base_url.startswith("https://"):
            # Credentials go in every request: never over plain HTTP, file: or other schemes.
            raise ImproperlyConfigured("RAZORPAY_API_BASE must be an https:// URL.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        token = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
        self._auth = f"Basic {token}"

    def request(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
        url = self.base_url + path + (f"?{urllib.parse.urlencode(params)}" if params else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)  # noqa: S310 — https enforced in __init__
        req.add_header("Authorization", self._auth)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:  # noqa: S310 — https enforced in __init__
                return json.loads(res.read() or b"{}")
        except urllib.error.HTTPError as err:
            try:
                detail = json.loads(err.read() or b"{}").get("error", {}).get("description", "")
            except ValueError:
                detail = ""
            message = detail or f"HTTP {err.code}"
            if err.code >= 500 or err.code == 429:
                raise GatewayError(f"Razorpay unavailable: {message}") from err
            raise GatewayRejected(message) from err
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            raise GatewayError(f"Could not reach Razorpay: {err}") from err


def _payment(entity: dict) -> GatewayPayment:
    return GatewayPayment(
        provider_payment_id=entity.get("id", ""),
        status=entity.get("status", ""),
        amount=from_paise(entity.get("amount")),
        provider_order_id=entity.get("order_id") or "",
        currency=entity.get("currency", "INR"),
        method=entity.get("method") or "unknown",
        failure_reason=entity.get("error_description") or "",
    )


def _refund(entity: dict) -> RefundResult:
    status = entity.get("status", "pending")
    return RefundResult(
        success=status != "failed",
        provider_refund_id=entity.get("id"),
        status=status if status in ("pending", "processed", "failed") else "pending",
        failure_reason="Refund failed at Razorpay." if status == "failed" else "",
    )


class RazorpayPaymentProvider(PaymentProvider):
    name = "razorpay"

    def __init__(self):
        self.key_id = settings.RAZORPAY_KEY_ID
        self.key_secret = settings.RAZORPAY_KEY_SECRET
        self.webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
        if not (self.key_id and self.key_secret):
            raise ImproperlyConfigured("PAYMENT_PROVIDER=razorpay needs RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")
        self.is_test_mode = self.key_id.startswith("rzp_test_")
        self.client = RazorpayClient(self.key_id, self.key_secret, settings.RAZORPAY_API_BASE)

    # --- payments ---------------------------------------------------------------------------

    def create_payment(
        self, *, reference: str, amount: Decimal, currency: str = "INR", customer: dict | None = None
    ) -> PaymentIntent:
        order = self.client.request(
            "POST",
            "/orders",
            {
                "amount": to_paise(amount),
                "currency": currency,
                "receipt": reference[:40],
                "notes": {"reference": reference},
            },
        )
        customer = customer or {}
        return PaymentIntent(
            provider=self.name,
            provider_order_id=order["id"],
            amount=amount,
            currency=currency,
            client_payload={
                "razorpay": True,
                "key_id": self.key_id,  # public by design; the secret is never sent
                "order_id": order["id"],
                "amount": to_paise(amount),
                "currency": currency,
                "name": settings.APP_NAME,
                "description": f"Order {reference}",
                "prefill": {k: v for k, v in customer.items() if k in ("name", "email", "contact") and v},
                "test_mode": self.is_test_mode,
            },
        )

    def verify_payment(
        self, *, provider_order_id: str, payload: dict, expected_amount: Decimal | None = None
    ) -> VerificationResult:
        if payload.get("cancelled"):
            # Only closes this attempt. If money was actually taken, the webhook/reconciliation still records it.
            return VerificationResult(success=False, cancelled=True, failure_reason="Payment cancelled by customer.")
        order_id = str(payload.get("razorpay_order_id", ""))
        payment_id = str(payload.get("razorpay_payment_id", ""))
        signature = str(payload.get("razorpay_signature", ""))
        if order_id != provider_order_id or not payment_id or not signature:
            return VerificationResult(success=False, failure_reason="Payment response does not match this order.")
        expected = hmac_sha256(self.key_secret, f"{order_id}|{payment_id}".encode())
        if not hmac.compare_digest(expected, signature):
            return VerificationResult(success=False, failure_reason="Invalid payment signature.")

        # The signature is genuine; now ask Razorpay what actually happened.
        gateway = _payment(self.client.request("GET", f"/payments/{urllib.parse.quote(payment_id)}"))
        if gateway.provider_order_id != provider_order_id:
            return VerificationResult(success=False, failure_reason="Payment belongs to a different order.")
        if expected_amount is not None and gateway.amount != expected_amount:
            return VerificationResult(
                success=False, provider_payment_id=payment_id, failure_reason="Paid amount does not match the order."
            )
        if gateway.status == "authorized":
            gateway = self.capture(provider_payment_id=payment_id, amount=gateway.amount, currency=gateway.currency)
        if gateway.status == "captured":
            return VerificationResult(
                success=True, provider_payment_id=payment_id, method=gateway.method, amount=gateway.amount
            )
        if gateway.status == "failed":
            return VerificationResult(
                success=False,
                provider_payment_id=payment_id,
                failure_reason=gateway.failure_reason or "Payment failed.",
            )
        return VerificationResult(success=False, pending=True, provider_payment_id=payment_id)

    def fetch_order_payments(self, *, provider_order_id: str) -> list[GatewayPayment]:
        data = self.client.request("GET", f"/orders/{urllib.parse.quote(provider_order_id)}/payments")
        return [_payment(item) for item in data.get("items", [])]

    def capture(self, *, provider_payment_id: str, amount: Decimal, currency: str = "INR") -> GatewayPayment:
        return _payment(
            self.client.request(
                "POST",
                f"/payments/{urllib.parse.quote(provider_payment_id)}/capture",
                {"amount": to_paise(amount), "currency": currency},
            )
        )

    # --- refunds ----------------------------------------------------------------------------

    def refund(self, *, provider_payment_id: str, amount: Decimal, reference: str) -> RefundResult:
        path = f"/payments/{urllib.parse.quote(provider_payment_id)}/refunds"
        existing = self.client.request("GET", path, params={"count": 100}).get("items", [])
        for item in existing:
            if (item.get("notes") or {}).get("reference") == reference:
                return _refund(item)  # an earlier attempt already went through
        created = self.client.request(
            "POST",
            f"/payments/{urllib.parse.quote(provider_payment_id)}/refund",
            {
                "amount": to_paise(amount),
                "speed": "normal",
                "receipt": reference[:40],
                "notes": {"reference": reference},
            },
        )
        return _refund(created)

    def fetch_refund(self, *, provider_payment_id: str, provider_refund_id: str) -> RefundResult:
        path = f"/payments/{urllib.parse.quote(provider_payment_id)}/refunds/{urllib.parse.quote(provider_refund_id)}"
        return _refund(self.client.request("GET", path))

    # --- webhooks ---------------------------------------------------------------------------

    def parse_webhook(self, *, body: bytes, headers) -> WebhookEvent:
        if not self.webhook_secret:
            raise InvalidSignature("RAZORPAY_WEBHOOK_SECRET is not configured.")
        signature = headers.get(WEBHOOK_SIGNATURE_HEADER, "")
        if not signature or not hmac.compare_digest(hmac_sha256(self.webhook_secret, body), signature):
            raise InvalidSignature("Invalid Razorpay webhook signature.")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise InvalidSignature("Webhook body is not JSON.") from exc
        event_id = headers.get(WEBHOOK_EVENT_ID_HEADER) or hashlib.sha256(body).hexdigest()
        return parse_razorpay_style_event(event_id, data)
