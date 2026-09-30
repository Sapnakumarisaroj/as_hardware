"""The hardware assistant: understanding, retrieval, grounding, budget, languages, fallback."""

import json
from decimal import Decimal

import pytest

from apps.ai.services.assistant import HardwareAssistantService
from apps.ai.services.intent import IntentService, detect_language, parse_budget, parse_dimensions
from apps.ai.services.retrieval import CatalogRetrievalService
from apps.core.testing import create_category, create_product, create_store
from integrations.llm import ChatOptions, LLMError, LLMProvider, LLMReply, LLMUnavailable
from integrations.llm.providers import NoLLMProvider

pytestmark = pytest.mark.django_db


class FakeProvider(LLMProvider):
    """Answers with scripted JSON, records every prompt, can be told to fail."""

    name = "fake"
    model = "fake-1"

    def __init__(self, replies=None, *, fail: Exception | None = None):
        self.replies = list(replies or [])
        self.fail = fail
        self.calls: list[list[dict]] = []

    @property
    def available(self) -> bool:
        return True

    def chat(self, messages, options: ChatOptions | None = None) -> LLMReply:
        self.calls.append(messages)
        if self.fail:
            raise self.fail
        reply = self.replies.pop(0) if self.replies else {"message": "Sure."}
        return LLMReply(content=json.dumps(reply), tokens_in=10, tokens_out=5, provider=self.name, model=self.model)


@pytest.fixture
def shop():
    store = create_store(name="Kothrud")
    plumbing, tools = create_category("Plumbing"), create_category("Tools")
    items = {}
    for name, price, category in (
        ("Brass Pillar Tap", "899.00", plumbing),
        ("PTFE Thread Seal Tape", "69.00", plumbing),
        ("Adjustable Pipe Wrench", "529.00", tools),
        ("Corded Impact Drill 650W", "3299.00", tools),
        ("Masonry Drill Bit Set", "329.00", tools),
        ("Nylon Wall Plugs 6 mm", "89.00", tools),
        ("Wood Screws Box", "129.00", tools),
        ("Measuring Tape 5 m", "159.00", tools),
    ):
        product, variant = create_product(
            name=name, price=price, mrp=str(Decimal(price) + 100), category=category, stock=10, store=store
        )
        items[name] = (product, variant)
    return items


def names(reply) -> list[str]:
    return [m.product.name for m in reply.products]


# --- Understanding (rules) ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("I need a drill for concrete", "en"),
        ("Mujhe bathroom repair karne ka saman chahiye", "hinglish"),
        ("मुझे पंखा चाहिए", "hi"),
        ("drill chahiye", "hinglish"),
    ],
)
def test_language_detection(text, language):
    assert detect_language(text) == language


@pytest.mark.parametrize(
    ("text", "budget"),
    [
        ("My budget is ₹2000", Decimal("2000")),
        ("under rs 1,500", Decimal("1500")),
        ("2000 rupees ke andar", Decimal("2000")),
        ("budget 800", Decimal("800")),
        ("I need 12 screws", None),
    ],
)
def test_budget_parsing(text, budget):
    assert parse_budget(text) == budget


def test_dimensions_parsing():
    assert parse_dimensions("paint a 12x15 room") == (12.0, 15.0)
    assert parse_dimensions("12 x 15 ft") == (12.0, 15.0)
    assert parse_dimensions("M8 x 50 bolts") == (8.0, 50.0)  # sizes look alike; painting logic decides
    assert parse_dimensions("no sizes here") is None


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("I need something to fix a leaking tap", "REPAIR_HELP"),
        ("I need a drill for concrete", "PRODUCT_SEARCH"),
        ("I need material to paint a 12x15 room", "PROJECT_HELP"),
        ("What is PTFE tape?", "GENERAL_HARDWARE_QUESTION"),
        ("Will a 6 mm wall plug work with a 4 mm screw?", "COMPATIBILITY"),
        ("How much cement for 100 sq ft?", "QUANTITY"),
        ("Find hardware under ₹1000", "BUDGET"),
        ("Mujhe bathroom repair karne ka saman chahiye", "REPAIR_HELP"),
    ],
)
def test_intents_by_rules(text, intent):
    assert IntentService(NoLLMProvider()).understand(text).intent == intent


def test_words_in_three_languages_become_english_search_words():
    service = IntentService(NoLLMProvider())
    assert "tap" in service.understand("nal tapak raha hai").terms
    assert "tap" in service.understand("नल टपक रहा है").terms
    assert "fan" in service.understand("मुझे पंखा चाहिए").terms
    assert "screwdriver" in service.understand("pechkas chahiye").terms


def test_vague_requests_get_a_follow_up_question():
    service = IntentService(NoLLMProvider())
    paint = service.understand("I need paint.")
    assert paint.needs_clarification and "What are you painting" in paint.question
    bathroom = service.understand("Mujhe bathroom repair karne ka saman chahiye.")
    assert bathroom.needs_clarification and bathroom.question.startswith("Bathroom mein kya")
    specific = service.understand("I need paint for the bedroom walls")
    assert not specific.needs_clarification


# --- Answers (basic mode) ---------------------------------------------------------------------------


def test_leaking_tap_answer_is_built_from_real_products(shop):
    reply = HardwareAssistantService(NoLLMProvider()).answer("I need something to fix a leaking tap.")
    assert reply.ai_mode == "basic"
    assert reply.intent == "REPAIR_HELP"
    assert "dripping tap" in reply.message
    found = names(reply)
    assert "Brass Pillar Tap" in found and "PTFE Thread Seal Tape" in found and "Adjustable Pipe Wrench" in found
    assert "Measuring Tape 5 m" not in found  # "tap" is not "tape"
    for match in reply.products:
        assert match.price == match.product.price  # the row's price, nothing made up
        assert match.reason.startswith("Matches")
    assert any(a["type"] == "add_all" for a in reply.actions)
    assert {a["variant_id"] for a in reply.actions if a["type"] == "add_to_cart"} == {
        m.variant_id for m in reply.products
    }


def test_drill_for_concrete(shop):
    reply = HardwareAssistantService(NoLLMProvider()).answer("I need a drill for concrete.")
    assert names(reply)[:2] == ["Masonry Drill Bit Set", "Corded Impact Drill 650W"]
    assert "impact (hammer) drill" in reply.message


def test_paint_gives_an_estimate_and_says_nothing_is_in_the_catalogue(shop):
    reply = HardwareAssistantService(NoLLMProvider()).answer("I need material to paint a 12x15 room.")
    assert reply.estimate == {
        "kind": "paint", "length_ft": 12.0, "width_ft": 15.0, "height_ft": 10, "wall_area_sqft": 540,
        "emulsion_litres": 9, "primer_litres": 5, "is_estimate": True, "text": reply.estimate["text"],
    }  # fmt: skip
    assert "This is an estimate, not a quotation." in reply.message
    assert reply.products == []
    assert "couldn't find anything in the catalogue" in reply.message


def test_hinglish_question_is_answered_in_hinglish_with_a_follow_up(shop):
    reply = HardwareAssistantService(NoLLMProvider()).answer("Mujhe bathroom repair karne ka saman chahiye.")
    assert reply.language == "hinglish"
    assert reply.questions == [
        "Bathroom mein kya theek karna hai — tap, leak karta pipe ya joint, shower, ya tiles ke aas-paas ke gaps?"
    ]
    assert reply.products == []


def test_the_follow_up_answer_keeps_the_topic(shop):
    service = HardwareAssistantService(NoLLMProvider())
    history = [
        {"role": "user", "content": "Mujhe bathroom repair karne ka saman chahiye."},
        {"role": "assistant", "content": "Bathroom mein kya theek karna hai?"},
    ]
    reply = service.answer("nal tapak raha hai", history=history)
    assert not reply.questions
    assert "Brass Pillar Tap" in names(reply) and "PTFE Thread Seal Tape" in names(reply)


def test_hindi_request(shop):
    reply = HardwareAssistantService(NoLLMProvider()).answer("मुझे ड्रिल और पेचकस चाहिए")
    assert reply.language == "hi"
    assert reply.message.startswith("इसके लिए हमारे कैटलॉग में")
    assert "Corded Impact Drill 650W" in names(reply)


def test_budget_limits_products_and_adds_up_a_kit(shop):
    reply = HardwareAssistantService(NoLLMProvider()).answer("My budget is ₹1000, I need to fix a leaking tap")
    assert all(m.price <= 1000 for m in reply.products)
    assert "Brass Pillar Tap" in names(reply)  # 899
    assert "Corded Impact Drill 650W" not in names(reply)
    assert "within your budget of ₹1,000" in reply.message
    total = sum(m.price for m in reply.products if "Within your budget" in m.reason)
    assert total <= Decimal("1000")


def test_budget_only_request_shows_popular_products_within_it(shop):
    reply = HardwareAssistantService(NoLLMProvider()).answer("Find hardware under ₹500")
    assert reply.intent == "BUDGET"
    assert reply.products and all(m.price <= 500 for m in reply.products)
    assert reply.questions == [
        "What are you looking for within ₹500 — tools, plumbing, electrical, safety gear, or something specific?"
    ]


def test_general_question_is_marked_as_general_knowledge(shop):
    reply = HardwareAssistantService(NoLLMProvider()).answer("What is PTFE tape?")
    assert reply.intent == "GENERAL_HARDWARE_QUESTION"
    assert reply.knowledge[0]["title"] == "PTFE (thread seal) tape"
    assert reply.knowledge[0]["source"] == "knowledge_base"
    assert "General information (not about one specific product)" in reply.message
    assert names(reply) == ["PTFE Thread Seal Tape"]


def test_electrical_work_gets_a_safety_note(shop):
    reply = HardwareAssistantService(NoLLMProvider()).answer("I want to do the wiring of my new room myself")
    assert reply.safety and "licensed electrician" in reply.safety[0]
    assert reply.message.endswith(reply.safety[0])


def test_nothing_matching_is_said_plainly(shop):
    reply = HardwareAssistantService(NoLLMProvider()).answer("I need a lawn mower")
    assert reply.products == []
    assert "couldn't find anything in the catalogue for “lawn, mower”" in reply.message
    # Words the vocabulary doesn't know still search the catalogue as they are.
    wrench = HardwareAssistantService(NoLLMProvider()).answer("do you have an adjustable wrench?")
    assert names(wrench) == ["Adjustable Pipe Wrench"]
    assert reply.notice == ""  # no model configured: nothing is "unavailable"


def test_unpublished_products_are_never_recommended(shop):
    product, _ = shop["Brass Pillar Tap"]
    product.is_published = False
    product.save()
    reply = HardwareAssistantService(NoLLMProvider()).answer("I need a tap")
    assert "Brass Pillar Tap" not in names(reply)


def test_retrieval_uses_the_catalogue_search_backend(shop):
    matches, missing = CatalogRetrievalService().find(["ptfe tape", "unicorn dust"])
    assert [m.product.name for m in matches] == ["PTFE Thread Seal Tape"]
    assert missing == ["unicorn dust"]


# --- With a model ---------------------------------------------------------------------------------


def test_model_writes_the_recommendation_but_only_about_listed_products(shop):
    provider = FakeProvider(
        [{"message": "Start with the Brass Pillar Tap and seal the joint with PTFE Thread Seal Tape."}]
    )
    reply = HardwareAssistantService(provider).answer("I need something to fix a leaking tap.")
    assert reply.ai_mode == "llm"
    assert reply.provider == "fake" and reply.tokens_in == 10
    assert "Start with the Brass Pillar Tap" in reply.message
    assert "dripping tap usually needs" in reply.message  # the fixed explanation stays
    assert len(provider.calls) == 1  # a recognised request needs no understanding call
    prompt = json.loads(provider.calls[0][1]["content"])
    assert {p["name"] for p in prompt["products"]} == set(names(reply))


@pytest.mark.parametrize(
    "bad",
    [
        {"message": "Buy the SuperDrill 9000, only ₹499 today!"},  # a product we don't have and a price
        {"message": "The Brass Pillar Tap costs 899 and ships in 2 days."},  # numbers of its own
        {"message": "Try product 17 or 23."},  # ids
        {"message": "Hello there, let me think about this for you."},  # none of the products
        {"nothing": "here"},
        "not json at all",
    ],
)
def test_ungrounded_model_text_is_dropped(shop, bad):
    provider = FakeProvider([bad])
    if isinstance(bad, str):
        provider.replies = []
        provider.chat = lambda messages, options=None: LLMReply(content=bad)  # type: ignore[method-assign]
    reply = HardwareAssistantService(provider).answer("I need something to fix a leaking tap.")
    assert reply.ai_mode == "basic"
    assert "Here is what we have in the catalogue for that:" in reply.message
    assert "SuperDrill" not in reply.message and "₹499" not in reply.message
    assert names(reply)[0] == "Brass Pillar Tap"


def test_model_understands_phrasings_the_rules_do_not(shop):
    provider = FakeProvider(
        [
            {
                "intent": "REPAIR_HELP",
                "language": "en",
                "search_terms": ["tap", "PTFE tape"],
                "budget": None,
                "needs_clarification": False,
            },
            {"message": "The Brass Pillar Tap will replace the old one."},
        ]
    )
    reply = HardwareAssistantService(provider).answer("the thing in my kitchen keeps dripping water at the base")
    assert reply.intent == "REPAIR_HELP"
    assert "Brass Pillar Tap" in names(reply)
    assert len(provider.calls) == 2


def test_model_search_words_cannot_invent_products(shop):
    provider = FakeProvider(
        [{"intent": "PRODUCT_SEARCH", "language": "en", "search_terms": ["gold plated unicorn", "tap"]}]
    )
    reply = HardwareAssistantService(provider).answer("the thing in my kitchen keeps dripping water at the base")
    assert names(reply) == ["Brass Pillar Tap"]


def test_model_explains_a_concept_we_have_no_text_for_as_general_information(shop):
    provider = FakeProvider(
        [
            {"intent": "GENERAL_HARDWARE_QUESTION", "language": "en", "search_terms": []},
            {"message": "Galvanising coats steel with zinc so it does not rust."},
        ]
    )
    reply = HardwareAssistantService(provider).answer("What does galvanised mean?")
    assert reply.knowledge == [
        {"title": "", "text": "Galvanising coats steel with zinc so it does not rust.", "source": "model"}
    ]
    assert reply.message.startswith("General information (not about one specific product):")
    assert reply.products == []


@pytest.mark.parametrize("failure", [LLMUnavailable("connection refused"), LLMError("500"), TimeoutError("slow")])
def test_when_the_model_fails_the_basic_answer_comes_with_a_notice(shop, failure):
    reply = HardwareAssistantService(FakeProvider(fail=failure)).answer("I need something to fix a leaking tap.")
    assert reply.ai_mode == "basic"
    assert reply.notice == "AI is temporarily unavailable. You can search products normally."
    assert "Brass Pillar Tap" in names(reply)
    hinglish = HardwareAssistantService(FakeProvider(fail=failure)).answer("nal tapak raha hai")
    assert hinglish.notice == "AI abhi uplabdh nahi hai. Aap products normally search kar sakte hain."


def test_a_model_is_not_asked_when_nothing_is_to_be_said(shop):
    provider = FakeProvider()
    reply = HardwareAssistantService(provider).answer("I need paint.")
    assert reply.questions and provider.calls == []  # the follow-up question needs no model
    assert reply.notice == ""
