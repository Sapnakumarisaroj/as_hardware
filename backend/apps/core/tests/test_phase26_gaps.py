"""Phase 26 coverage gaps: own reviews (edit → moderated again, delete), payment background jobs, and
the language-model HTTP providers (with the network faked; nothing leaves the machine)."""

import io
import json
import urllib.error
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.jobs import run_due_jobs
from apps.core.models import Job
from apps.core.testing import create_product
from apps.reviews.models import Review
from apps.reviews.services import create_review, moderate_review
from apps.reviews.tests.test_reviews import _deliver
from integrations.llm import ChatOptions, LLMError, LLMUnavailable
from integrations.llm.base import post_json
from integrations.llm.providers import AnthropicProvider, OllamaProvider, OpenAICompatibleProvider

pytestmark = pytest.mark.django_db


# --- Reviews: edit and delete your own ----------------------------------------------------------------------


def test_editing_an_approved_review_sends_it_back_to_moderation(user, staff_user, auth_client):
    product, variant = create_product(stock=5)
    _deliver(user, staff_user, variant)
    review = create_review(user=user, product=product, rating=5, body="Great")
    moderate_review(review, status=Review.Status.APPROVED, moderator=staff_user)
    product.refresh_from_db()
    assert product.rating_count == 1

    res = auth_client.patch(
        f"/api/reviews/mine/{review.pk}/", {"rating": 2, "body": "Broke after a week"}, format="json"
    )
    assert res.status_code == 200
    review.refresh_from_db()
    product.refresh_from_db()
    assert review.status == Review.Status.PENDING and review.rating == 2
    assert product.rating_count == 0  # no longer counted until approved again

    assert auth_client.delete(f"/api/reviews/mine/{review.pk}/").status_code == 204
    assert not Review.objects.filter(pk=review.pk).exists()


def test_reviews_of_others_are_out_of_reach(user, other_user, staff_user, api_client):
    from rest_framework.test import APIClient

    product, variant = create_product(stock=5)
    _deliver(user, staff_user, variant)
    review = create_review(user=user, product=product, rating=4)
    other = APIClient()
    other.force_authenticate(other_user)
    assert other.patch(f"/api/reviews/mine/{review.pk}/", {"rating": 1}, format="json").status_code == 404
    assert other.delete(f"/api/reviews/mine/{review.pk}/").status_code == 404


def test_moderation_needs_a_decision(user, staff_user):
    from apps.reviews.services import ReviewError

    product, variant = create_product(stock=5)
    _deliver(user, staff_user, variant)
    review = create_review(user=user, product=product, rating=4)
    with pytest.raises(ReviewError):
        moderate_review(review, status="pending", moderator=staff_user)


# --- Payment background jobs ----------------------------------------------------------------------------------


def test_refund_housekeeping_queues_unsubmitted_and_skips_manual(settings, user):
    from apps.orders.tests.helpers import order_with
    from apps.payments import jobs as payment_jobs
    from apps.payments.models import Refund

    settings.BACKGROUND_JOBS_MODE = "cron"
    _, variant = create_product(stock=5)
    _online, online_payment = order_with(user, (variant, 1), method="online")
    _cod, cod_payment = order_with(user, (variant, 1), method="cod")
    auto = Refund.objects.create(payment=online_payment, amount=Decimal("10.00"), reason="test")
    manual = Refund.objects.create(payment=cod_payment, amount=Decimal("5.00"), reason="cash")
    assert manual.is_manual and not auto.is_manual
    assert payment_jobs.refunds_housekeeping().startswith("queued 1")
    queued = [job.payload.get("refund_id") for job in Job.objects.filter(status=Job.Status.QUEUED)]
    assert auto.pk in queued and manual.pk not in queued  # cash refunds are paid back by staff, never a gateway


def test_periodic_payment_jobs_run_on_an_empty_shop(settings):
    from apps.payments import jobs as payment_jobs

    assert payment_jobs.reconcile_open_payments() is not None
    assert payment_jobs.expire_unpaid_orders() is not None
    assert payment_jobs.consistency_report() == "0 issue(s)"


def test_run_jobs_reports_nothing_due_when_idle(settings):
    settings.BACKGROUND_JOBS_MODE = "cron"
    assert run_due_jobs() == 0


# --- Language-model providers over (faked) HTTP ---------------------------------------------------------------


class _Res(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def network(monkeypatch):
    sent = []
    replies = []

    def fake(req, timeout):
        sent.append({"url": req.full_url, "headers": dict(req.header_items()), "body": json.loads(req.data)})
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _Res(json.dumps(reply).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake)
    return sent, replies


def test_ollama_provider(network, settings):
    sent, replies = network
    replies.append({"message": {"content": '{"intent": "x"}'}, "prompt_eval_count": 12, "eval_count": 5})
    reply = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:3b").chat(
        [{"role": "user", "content": "hi"}], ChatOptions(json=True)
    )
    assert reply.json() == {"intent": "x"} and (reply.tokens_in, reply.tokens_out) == (12, 5)
    assert sent[0]["url"] == "http://localhost:11434/api/chat" and sent[0]["body"]["format"] == "json"
    replies.append({"error": "model 'qwen9' not found"})
    with pytest.raises(LLMUnavailable, match="ollama pull"):
        OllamaProvider(base_url="http://localhost:11434", model="qwen9").chat([{"role": "user", "content": "hi"}])


def test_openai_compatible_provider(network):
    sent, replies = network
    provider = OpenAICompatibleProvider(base_url="https://llm.example/v1", api_key="k", model="m")
    replies.append(
        {"choices": [{"message": {"content": "Hello"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}
    )
    assert provider.chat([{"role": "user", "content": "hi"}], ChatOptions(json=True)).content == "Hello"
    assert sent[0]["headers"]["Authorization"] == "Bearer k" and sent[0]["body"]["response_format"] == {
        "type": "json_object"
    }
    replies.append({"choices": []})
    with pytest.raises(LLMError):
        provider.chat([{"role": "user", "content": "hi"}])
    with pytest.raises(LLMUnavailable):
        OpenAICompatibleProvider(base_url="", model="").chat([{"role": "user", "content": "hi"}])


def test_anthropic_provider_moves_system_messages(network):
    sent, replies = network
    replies.append({"content": [{"type": "text", "text": "Hi"}], "usage": {"input_tokens": 4, "output_tokens": 1}})
    provider = AnthropicProvider(api_key="key", model="claude-haiku-4-5-20251001")
    reply = provider.chat(
        [{"role": "system", "content": "Be brief"}, {"role": "user", "content": "hi"}], ChatOptions(json=True)
    )
    body = sent[0]["body"]
    assert reply.content == "Hi" and body["system"].startswith("Be brief") and "JSON" in body["system"]
    assert body["messages"] == [{"role": "user", "content": "hi"}] and sent[0]["headers"]["X-api-key"] == "key"
    with pytest.raises(LLMUnavailable):
        AnthropicProvider(api_key="").chat([{"role": "user", "content": "hi"}])


def test_post_json_refuses_plain_http_and_maps_errors(network):
    sent, replies = network
    with pytest.raises(LLMError, match="https"):
        post_json("http://llm.example/v1", {}, timeout=1)
    replies.append(urllib.error.HTTPError("https://x", 401, "no", {}, io.BytesIO(b"bad key")))
    with pytest.raises(LLMUnavailable, match="credentials"):
        post_json("https://x", {}, timeout=1)
    replies.append(urllib.error.HTTPError("https://x", 500, "err", {}, io.BytesIO(b"boom")))
    with pytest.raises(LLMError, match="500"):
        post_json("https://x", {}, timeout=1)
    replies.append(urllib.error.URLError("refused"))
    with pytest.raises(LLMUnavailable):
        post_json("https://x", {}, timeout=1)


def test_unpaid_order_expiry_releases_stock(settings, user):
    """An online order left unpaid past PAYMENT_EXPIRY_MINUTES is cancelled by the periodic job."""
    from apps.inventory.models import Inventory
    from apps.orders.models import Order
    from apps.orders.tests.helpers import order_with
    from apps.payments import jobs as payment_jobs

    _, variant = create_product(stock=5)
    order, _payment = order_with(user, (variant, 2), method="online")
    reserved = Inventory.objects.get(variant=variant).reserved_quantity
    assert reserved == 2
    Order.objects.filter(pk=order.pk).update(
        created_at=timezone.now() - timedelta(minutes=settings.PAYMENT_EXPIRY_MINUTES + 5)
    )
    payment_jobs.expire_unpaid_orders()
    order.refresh_from_db()
    assert order.status == "cancelled" and Inventory.objects.get(variant=variant).reserved_quantity == 0
