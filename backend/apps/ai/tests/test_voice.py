"""Voice shopping (Phase 18): spoken numbers and units in English/Hindi/Hinglish, the command pipeline
(catalogue search → Phase 15 pricing → confirmation), the API, history isolation, audio checks, limits
and the speech providers."""

import json
import sys
import types
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.throttling import ScopedRateThrottle

from apps.ai.models import AIConversation
from apps.ai.services import spoken, voice
from apps.ai.services.spoken import Command, parse, parse_line
from apps.ai.services.voice import VoiceShoppingService, for_speech, sniff_audio
from apps.carts.models import CartItem
from apps.catalog.models import OptionType, Product
from apps.catalog.services import set_price_tiers, set_variant_options
from apps.core.testing import add_stock, create_category, create_product, create_store
from apps.orders.models import Order
from integrations import speech
from integrations.speech import (
    AudioTooLong,
    SpeechAudio,
    SpeechError,
    SpeechUnavailable,
    STTProvider,
    Transcript,
    TTSProvider,
)
from integrations.speech import base as speech_base
from integrations.speech import providers as speech_providers

URL = "/api/ai/voice/"
COMMAND = "/api/ai/voice/command/"
TRANSCRIBE = "/api/ai/voice/transcribe/"
SPEAK = "/api/ai/voice/speak/"
SESSIONS = "/api/ai/voice-sessions/"


# --- Spoken numbers and units (no database) ------------------------------------------------------------


@pytest.mark.parametrize(
    "said, quantity",
    [
        ("10 bags cement", 10),
        ("ten bags cement", 10),
        ("twenty five packets of wall plugs", 25),
        ("one hundred and twenty pipes", 120),
        ("a dozen led bulbs", 12),
        ("half dozen led bulbs", 6),
        ("2 dozen screws", 24),
        ("das bori cement", 10),
        ("bees packet ptfe tape", 20),
        ("pachaas bori cement", 50),
        ("do sau pachas screws", 250),
        ("दस बोरी सीमेंट", 10),
        ("पच्चीस पैकेट टेप", 25),
        ("डेढ़ सौ पेच", 150),
        ("१२ बोरी सीमेंट", 12),
        ("do pipe chahiye", 2),
        ("दो बोरी सीमेंट", 2),
        ("cement 10", 10),
    ],
)
def test_spoken_quantities(said, quantity):
    line = parse_line(spoken.normalize(said))
    assert line.quantity == quantity and line.quantity_given


@pytest.mark.parametrize("said", ["cement de do", "सीमेंट डाल दो", "53 grade cement", "m8 x 50 bolt", "1.5 sq mm wire"])
def test_numbers_that_are_not_quantities(said):
    line = parse_line(spoken.normalize(said))
    assert line.quantity is None and not line.quantity_given


def test_sizes_stay_in_the_search_words_and_counting_words_leave():
    line = parse_line(spoken.normalize("two coils of 1.5 sq mm wire"))
    assert (line.quantity, line.unit, line.query) == (2, "coil", "1.5 sq mm wire")
    line = parse_line(spoken.normalize("M8 x 50 bolt 3 packs"))
    assert (line.quantity, line.unit) == (3, "pack") and "50" in line.query and "bolt" in line.query
    line = parse_line(spoken.normalize("4 bags of 53grade cement"))
    assert line.query == "53 grade cement"


def test_kilos_and_metres_are_kept_for_the_product_to_decide():
    line = parse_line(spoken.normalize("पचास किलो सीमेंट दो बोरी"))
    assert line.quantity == 2 and line.unit == "bag"
    assert line.measure == (Decimal(50), "kg") and line.query == "50 kg cement"
    line = parse_line(spoken.normalize("20 metre wire"))
    assert line.quantity is None and line.measure == (Decimal(20), "m") and line.query_without_measure == "wire"


def test_hindi_loanwords_and_tool_names_become_catalogue_words():
    assert parse_line(spoken.normalize("बीस पैकेट टेफ्लॉन टेप")).query == "ptfe tape"
    assert parse_line(spoken.normalize("2 हथौड़ा")).query == "hammer"
    assert parse_line(spoken.normalize("mujhe 2 hathoda chahiye")).query == "hammer"
    assert parse_line(spoken.normalize("5 नग वायर")).query == "wire"


def test_a_fractional_count_is_refused():
    line = parse_line(spoken.normalize("1.5 bags cement"))
    assert line.quantity is None and line.problem == "whole_number"


@pytest.mark.parametrize(
    "said, pending, intent",
    [
        ("add 10 bags of cement", False, Command.ADD),
        ("hammer cart mein daalo", False, Command.ADD),
        ("make it 30", True, Command.SET_QUANTITY),
        ("तीस कर दो", True, Command.SET_QUANTITY),
        ("make it 30", False, Command.UNCLEAR),
        ("yes", True, Command.CONFIRM),
        ("haan ji", True, Command.CONFIRM),
        ("हाँ डाल दो", True, Command.CONFIRM),
        ("yes", False, Command.UNCLEAR),
        ("no", True, Command.CANCEL),
        ("nahi chahiye", True, Command.CANCEL),
        ("नहीं", True, Command.CANCEL),
        ("open my cart", False, Command.NAVIGATE),
        ("checkout", False, Command.NAVIGATE),
        ("show me drills", False, Command.SEARCH),
        ("drill dikhao", False, Command.SEARCH),
        ("which drill is best for concrete", False, Command.ASK),
        ("drill under 5000 rupees", False, Command.ASK),
        ("", False, Command.UNCLEAR),
    ],
)
def test_what_a_sentence_asks_for(said, pending, intent):
    assert parse(said, has_pending=pending).intent == intent


def test_navigation_pages():
    assert parse("open my cart").navigate == "cart"
    assert parse("place the order").navigate == "checkout"
    assert parse("where is my order").navigate == "orders"
    assert parse("show my wallet").navigate == "wallet"
    assert parse("मेरा कार्ट खोलो").navigate == "cart"
    # a quantity means shopping, even when the sentence mentions the cart
    assert parse("add 10 bags cement to my cart").intent == Command.ADD


def test_several_items_only_when_each_has_its_own_quantity():
    lines = parse("das bori cement aur paanch pipe").lines
    assert [(ln.quantity, ln.query) for ln in lines] == [(10, "cement"), (5, "pipe")]
    lines = parse("10 bags cement, 2 coils wire and 5 packets ptfe tape").lines
    assert [ln.quantity for ln in lines] == [10, 2, 5]
    lines = parse("nut and bolt 5 packs").lines
    assert len(lines) == 1 and lines[0].query == "nut bolt"
    assert len(parse("1 hammer, 2 drill, 3 tap, 4 pipe, 5 wire, 6 tape", max_lines=5).lines) == 5


def test_speech_text_reads_money_aloud():
    assert for_speech("Total ₹3,990.", "en") == "Total 3990 rupees."
    assert for_speech("कुल ₹3,800।", "hi") == "कुल 3800 रुपये।"
    assert for_speech("2 × Hammer: “yes”", "en") == "2 Hammer: yes"


def test_audio_formats_are_recognised_by_their_bytes():
    assert sniff_audio(b"\x1aE\xdf\xa3" + b"\0" * 10) == "audio/webm"
    assert sniff_audio(b"OggS" + b"\0" * 10) == "audio/ogg"
    assert sniff_audio(b"RIFF\0\0\0\0WAVEfmt ") == "audio/wav"
    assert sniff_audio(b"\0\0\0\x18ftypM4A ") == "audio/mp4"
    assert sniff_audio(b"ID3\x04" + b"\0" * 10) == "audio/mpeg"
    assert sniff_audio(b"%PDF-1.7 not audio") is None


# --- The pipeline on a real catalogue ------------------------------------------------------------------


@pytest.fixture
def shop(db):
    store = create_store()
    civil = create_category("Civil")
    cement_cat = create_category("Cement", parent=civil)
    tools = create_category("Tools")
    wires = create_category("Wires")
    opc, opc_v = create_product(
        name="OPC 53 Grade Cement",
        price="410.00",
        mrp="450.00",
        category=cement_cat,
        stock=100,
        store=store,
        unit="bag",
    )
    ppc, ppc_v = create_product(
        name="PPC Cement", price="395.00", mrp="420.00", category=cement_cat, stock=100, store=store, unit="bag"
    )
    ppc_small = ppc.variants.create(sku="PPC-25", mrp=Decimal("230.00"), price=Decimal("214.00"))
    add_stock(ppc_small, 40, store=store)
    grade = OptionType.objects.create(name="Grade")
    bag = OptionType.objects.create(name="Bag size", unit="kg")
    set_variant_options(
        opc_v, [{"option_type": grade.pk, "value": "53 Grade"}, {"option_type": bag.pk, "value": "50 kg"}]
    )
    set_variant_options(ppc_v, [{"option_type": grade.pk, "value": "PPC"}, {"option_type": bag.pk, "value": "50 kg"}])
    set_variant_options(
        ppc_small, [{"option_type": grade.pk, "value": "PPC"}, {"option_type": bag.pk, "value": "25 kg"}]
    )
    set_price_tiers(opc_v, [{"min_quantity": 10, "unit_price": "399.00"}, {"min_quantity": 30, "unit_price": "389.00"}])
    hammer, hammer_v = create_product(
        name="Claw Hammer", price="429.00", category=tools, stock=10, store=store, tags=["hammer"]
    )
    drill, _ = create_product(
        name="Impact Drill", price="3299.00", mrp="3499.00", category=tools, stock=5, store=store, tags=["drill"]
    )
    wire, wire_v = create_product(name="Copper Wire", price="20.00", category=wires, stock=500, store=store, unit="m")
    empty, empty_v = create_product(name="Hex Spanner", price="99.00", category=tools, stock=0, tags=["spanner"])
    return {
        "opc": opc,
        "opc_v": opc_v,
        "ppc": ppc,
        "ppc_v": ppc_v,
        "ppc_small": ppc_small,
        "hammer": hammer,
        "hammer_v": hammer_v,
        "drill": drill,
        "wire": wire,
        "wire_v": wire_v,
        "empty": empty,
        "empty_v": empty_v,
    }


def _command(text, **kwargs):
    return VoiceShoppingService().command(text, **kwargs)


def test_spoken_quantity_goes_through_the_bulk_price_tiers(shop):
    reply = _command("add 10 bags of 53 grade cement", language="en")
    assert reply.intent == Command.ADD and reply.needs_confirmation and not reply.add_now
    [line] = reply.lines
    assert line["status"] == "ready" and line["product_id"] == shop["opc"].pk and line["variant_id"] == shop["opc_v"].pk
    quote = line["quote"]
    assert quote["unit_price"] == "399.00" and quote["applied_tier"] == {"min_quantity": 10}
    assert quote["total"] == "3990.00"
    assert quote["next_tier"] == {"min_quantity": 30, "unit_price": "389.00", "units_more": 20, "reachable": True}
    assert "₹399" in reply.reply and "₹3,990" in reply.reply and "Add 20 more" in reply.reply and "yes" in reply.reply
    assert "rupees" in reply.speech and "₹" not in reply.speech


def test_below_the_first_tier_the_normal_price_is_used(shop):
    [line] = _command("5 bags of 53 grade cement").lines
    assert line["quote"]["unit_price"] == "410.00" and line["quote"]["applied_tier"] is None
    assert line["quote"]["next_tier"]["units_more"] == 5


def test_size_words_choose_the_variant(shop):
    [line] = _command("4 bags of 25 kg PPC cement").lines
    assert line["variant_id"] == shop["ppc_small"].pk and line["quote"]["unit_price"] == "214.00"
    assert {"Bag size: 25 kg", "Grade: PPC"} <= {f["label"] for f in line["filters"]}


def test_hindi_command_gets_a_hindi_answer(shop):
    reply = _command("दस बोरी 53 ग्रेड सीमेंट कार्ट में डालो", language="hi")
    [line] = reply.lines
    assert line["product_id"] == shop["opc"].pk and line["quantity"] == 10 and line["quote"]["unit_price"] == "399.00"
    assert "बोरी" in reply.reply and "थोक दर" in reply.reply and "हाँ" in reply.reply
    assert "रुपये" in reply.speech


def test_hinglish_order_with_two_items(shop):
    reply = _command("das bori 53 grade cement aur 2 hathoda", language="hinglish")
    assert [(ln["product_id"], ln["quantity"]) for ln in reply.lines] == [(shop["opc"].pk, 10), (shop["hammer"].pk, 2)]
    assert "haan" in reply.reply.lower()


def test_the_language_is_detected_when_not_chosen(shop):
    assert _command("दस बोरी सीमेंट").language == "hi"
    assert _command("10 bags cement").language == "en"


def test_metres_are_the_quantity_for_wire_sold_by_the_metre(shop):
    [line] = _command("20 metre copper wire").lines
    assert line["product_id"] == shop["wire"].pk and line["quantity"] == 20 and line["quote"]["total"] == "400.00"


def test_a_counting_word_that_differs_from_how_it_is_sold_is_explained(shop):
    [line] = _command("3 boxes claw hammer").lines
    assert line["quantity"] == 3 and line["note"]


def test_add_without_a_number_assumes_one_and_says_so(shop):
    [line] = _command("hammer cart mein daalo", language="hinglish").lines
    assert line["quantity"] == 1 and "1" in line["note"]


def test_more_than_the_order_limit(shop):
    [line] = _command("60 bags PPC cement").lines
    assert line["status"] == "too_many" and "50" in line["message"]
    assert line["quote"] is None


def test_out_of_stock_is_not_proposed(shop):
    reply = _command("2 hex spanner")
    [line] = reply.lines
    assert line["status"] == "short_stock" and not reply.needs_confirmation


def test_nothing_invented_when_the_catalogue_has_no_match(shop):
    reply = _command("5 bags of gypsum plaster")
    [line] = reply.lines
    assert line["status"] == "not_found" and line["product_id"] is None and "gypsum" in reply.reply
    assert not reply.needs_confirmation


def test_unpublished_products_are_never_offered(shop):
    Product.objects.filter(pk=shop["hammer"].pk).update(is_published=False)
    [line] = _command("2 claw hammer").lines
    assert line["status"] == "not_found"


def test_changing_the_quantity_reprices_the_waiting_line(shop):
    pending = [{"product_id": shop["opc"].pk, "variant_id": shop["opc_v"].pk, "quantity": 10}]
    reply = _command("make it 30", pending=pending)
    assert reply.intent == Command.SET_QUANTITY and reply.needs_confirmation
    [line] = reply.lines
    assert line["quantity"] == 30 and line["quote"]["unit_price"] == "389.00" and "Changed to 30" in reply.reply


def test_changing_the_quantity_needs_one_waiting_line(shop):
    pending = [
        {"product_id": shop["opc"].pk, "variant_id": shop["opc_v"].pk, "quantity": 10},
        {"product_id": shop["hammer"].pk, "variant_id": shop["hammer_v"].pk, "quantity": 1},
    ]
    reply = _command("make it 30", pending=pending)
    assert reply.intent == Command.UNCLEAR and not reply.lines


def test_yes_confirms_with_prices_from_the_database(shop):
    pending = [{"product_id": shop["opc"].pk, "variant_id": shop["opc_v"].pk, "quantity": 10}]
    shop["opc_v"].price_tiers.update(unit_price=Decimal("395.00"))  # changed since the line was shown
    reply = _command("haan", pending=pending, language="hinglish")
    assert reply.intent == Command.CONFIRM and reply.add_now and not reply.needs_confirmation
    assert reply.lines[0]["quote"]["unit_price"] == "395.00"
    assert reply.reply.startswith("Cart mein")


def test_yes_for_a_line_that_is_no_longer_on_sale(shop):
    pending = [
        {"product_id": shop["hammer"].pk, "variant_id": shop["hammer_v"].pk, "quantity": 1, "name": "Claw Hammer"}
    ]
    Product.objects.filter(pk=shop["hammer"].pk).update(is_published=False)
    reply = _command("yes", pending=pending)
    assert reply.intent == Command.CONFIRM and not reply.add_now and reply.lines[0]["status"] == "unavailable"


def test_yes_with_a_variant_of_another_product_is_refused(shop):
    pending = [{"product_id": shop["hammer"].pk, "variant_id": shop["opc_v"].pk, "quantity": 1}]
    reply = _command("yes", pending=pending)
    assert not reply.add_now and reply.lines[0]["status"] == "unavailable"


def test_no_cancels_and_yes_alone_explains(shop):
    pending = [{"product_id": shop["opc"].pk, "variant_id": shop["opc_v"].pk, "quantity": 10}]
    assert _command("cancel", pending=pending).intent == Command.CANCEL
    reply = _command("yes")
    assert reply.intent == Command.UNCLEAR and "Nothing is waiting" in reply.reply


def test_navigation_only_opens_pages(shop, user):
    reply = _command("place the order", user=user)
    assert reply.navigate == {"page": "checkout", "path": "/checkout"} and "yourself" in reply.reply
    assert not Order.objects.exists()


def test_search_lists_real_products(shop):
    reply = _command("show me drills")
    assert reply.intent == Command.SEARCH and [p["product_id"] for p in reply.products] == [shop["drill"].pk]
    assert reply.search_path == "/search?q=drills"


def test_questions_go_to_the_hardware_assistant(shop):
    reply = _command("which drill is best for concrete?")
    assert reply.intent == Command.ASK and reply.ai_mode == "basic" and reply.reply
    assert shop["drill"].pk in [p["product_id"] for p in reply.products]


# --- API ---------------------------------------------------------------------------------------------


def test_status_is_public_and_reveals_no_secrets(api_client, db, settings):
    settings.SPEECH_API_KEY = "sk-voice-secret"
    settings.OPENAI_COMPATIBLE_API_KEY = "sk-other-secret"
    body = api_client.get(URL).json()
    assert [ln["code"] for ln in body["languages"]] == ["en", "hi", "hinglish"]
    assert body["browser_recognition"] is True
    assert body["server_recognition"]["enabled"] is False and body["server_voice"]["enabled"] is False
    assert body["examples"]["hi"] and body["max_audio_seconds"] == 20
    assert "secret" not in json.dumps(body)


def test_command_api_for_a_guest_returns_cards_and_keeps_no_history(api_client, shop):
    response = api_client.post(COMMAND, {"transcript": "10 bags 53 grade cement", "language": "en"}, format="json")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["conversation_id"] is None and body["intent"] == "add_to_cart"
    line = body["lines"][0]
    assert line["product"]["slug"] == shop["opc"].slug and line["product"]["variant_id"] == shop["opc_v"].pk
    assert line["quote"]["unit_price"] == "399.00" and body["speech"]
    assert not AIConversation.objects.filter(kind=AIConversation.Kind.VOICE).exists()


def test_command_never_writes_the_cart(auth_client, shop):
    pending = [{"product_id": shop["opc"].pk, "variant_id": shop["opc_v"].pk, "quantity": 10}]
    body = auth_client.post(COMMAND, {"transcript": "yes", "pending": pending}, format="json").json()
    assert body["add_now"] is True
    assert not CartItem.objects.exists()  # the browser adds through the cart API
    response = auth_client.post(
        "/api/cart/items/", {"variant_id": body["lines"][0]["variant_id"], "quantity": 10}, format="json"
    )
    assert response.status_code in (200, 201)
    line = response.json()["items"][0]
    assert line["quantity"] == 10 and line["unit_price"] == "399.00"


def test_signed_in_history_is_kept_and_private(auth_client, api_client, other_user, shop):
    first = auth_client.post(COMMAND, {"transcript": "10 bags cement"}, format="json").json()
    conversation_id = first["conversation_id"]
    assert conversation_id
    again = auth_client.post(
        COMMAND, {"transcript": "show me drills", "conversation_id": conversation_id}, format="json"
    ).json()
    assert again["conversation_id"] == conversation_id
    sessions = auth_client.get(SESSIONS).json()["results"]
    assert [(s["id"], s["turns"]) for s in sessions] == [(conversation_id, 2)]
    detail = auth_client.get(f"{SESSIONS}{conversation_id}/").json()
    assert [t["transcript"] for t in detail["turns"]] == ["10 bags cement", "show me drills"]
    assert detail["turns"][0]["intent"] == "add_to_cart"

    # someone else's conversation id starts a new conversation for them, never continues this one
    api_client.force_authenticate(other_user)
    theirs = api_client.post(COMMAND, {"transcript": "hi", "conversation_id": conversation_id}, format="json").json()
    assert theirs["conversation_id"] != conversation_id
    assert api_client.get(f"{SESSIONS}{conversation_id}/").status_code == 404
    assert api_client.delete(f"{SESSIONS}{conversation_id}/").status_code == 404
    assert AIConversation.objects.get(pk=conversation_id).messages.count() == 4

    assert auth_client.delete(f"{SESSIONS}{conversation_id}/").status_code == 204
    assert auth_client.post(f"{SESSIONS}clear/").status_code == 204
    assert auth_client.get(SESSIONS).json()["results"] == []
    assert AIConversation.objects.filter(kind=AIConversation.Kind.VOICE, user=other_user).count() == 1


def test_sessions_need_sign_in(api_client):
    assert api_client.get(SESSIONS).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"transcript": ""},
        {"transcript": "x" * 501},
        {"transcript": "yes", "language": "fr"},
        {"transcript": "yes", "pending": [{"product_id": 1, "variant_id": 1, "quantity": 0}]},
        {"transcript": "yes", "pending": [{"product_id": 1, "variant_id": 1, "quantity": 1}] * 6},
        {"transcript": "yes", "postal_code": "12ab"},
    ],
)
def test_command_validation(api_client, db, body):
    assert api_client.post(COMMAND, body, format="json").status_code == 400


def test_command_rate_limit(api_client, shop, monkeypatch):
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {**ScopedRateThrottle.THROTTLE_RATES, "voice": "2/min"})
    for _ in range(2):
        assert api_client.post(COMMAND, {"transcript": "open my cart"}, format="json").status_code == 200
    assert api_client.post(COMMAND, {"transcript": "open my cart"}, format="json").status_code == 429
    assert api_client.get(URL).status_code == 200  # the status endpoint isn't limited


# --- Recordings and the server voice ---------------------------------------------------------------------


class FakeSTT(STTProvider):
    name = "fake"
    model = "fake-whisper"

    def __init__(self, text="10 bags cement", error=None):
        self.text = text
        self.error = error
        self.calls = []

    @property
    def available(self):
        return True

    def transcribe(self, audio, *, language="", content_type=""):
        self.calls.append((len(audio), language, content_type))
        if self.error:
            raise self.error
        return Transcript(self.text, language="hi", confidence=0.9, duration=2.0, provider=self.name, model=self.model)


class FakeTTS(TTSProvider):
    name = "fake"

    def __init__(self, error=None):
        self.error = error
        self.said = []

    @property
    def available(self):
        return True

    def synthesize(self, text, *, language=""):
        self.said.append((text, language))
        if self.error:
            raise self.error
        return SpeechAudio(b"ID3fake-mp3", "audio/mpeg")


@pytest.fixture
def stt(monkeypatch):
    def install(*args, **kwargs):
        provider = FakeSTT(*args, **kwargs)
        monkeypatch.setattr(voice, "get_stt_provider", lambda: provider)
        return provider

    return install


@pytest.fixture
def tts(monkeypatch):
    def install(*args, **kwargs):
        provider = FakeTTS(*args, **kwargs)
        monkeypatch.setattr(voice, "get_tts_provider", lambda: provider)
        return provider

    return install


def webm(size=2000):
    return b"\x1aE\xdf\xa3" + b"\x00" * size


def _upload(api_client, data, name="recording.webm", content_type="audio/webm", language="hi"):
    return api_client.post(
        TRANSCRIBE,
        {"audio": SimpleUploadedFile(name, data, content_type=content_type), "language": language},
        format="multipart",
    )


def test_transcribe_without_server_recognition_says_so(api_client, db):
    response = _upload(api_client, webm())
    assert response.status_code == 503 and response.json()["error"]["code"] == "speech_unavailable"


def test_transcribe_with_a_provider(api_client, stt, db):
    provider = stt("दस बोरी सीमेंट")
    response = _upload(api_client, webm(), name="anything.txt", content_type="text/plain")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["text"] == "दस बोरी सीमेंट" and body["empty"] is False and body["confidence"] == 0.9
    assert provider.calls == [(2004, "hi", "audio/webm")]  # format from the bytes, not the name
    assert not AIConversation.objects.exists()  # recordings and their words are not stored here


@pytest.mark.parametrize(
    "data, status_code, code",
    [
        (b"%PDF-1.7" + b"\0" * 500, 415, "unsupported_audio"),
        (b"\x1aE\xdf\xa3", 400, "audio_empty"),
    ],
)
def test_bad_recordings(api_client, stt, db, data, status_code, code):
    stt()
    response = _upload(api_client, data)
    assert response.status_code == status_code and response.json()["error"]["code"] == code


def test_missing_and_oversized_recordings(api_client, stt, db, settings):
    stt()
    assert api_client.post(TRANSCRIBE, {}, format="multipart").json()["error"]["code"] == "audio_missing"
    settings.VOICE_MAX_AUDIO_BYTES = 1000
    response = _upload(api_client, webm(5000))
    assert response.status_code == 413 and response.json()["error"]["code"] == "audio_too_large"


@pytest.mark.parametrize(
    "error, status_code, code",
    [
        (AudioTooLong("Recordings can be 20 seconds at most."), 400, "audio_too_long"),
        (SpeechError("broken file"), 400, "audio_unreadable"),
        (SpeechUnavailable("model missing"), 503, "speech_unavailable"),
    ],
)
def test_recogniser_problems(api_client, stt, db, error, status_code, code):
    stt(error=error)
    response = _upload(api_client, webm())
    assert response.status_code == status_code and response.json()["error"]["code"] == code


def test_transcribe_rate_limit(api_client, stt, db, monkeypatch):
    stt()
    monkeypatch.setattr(
        ScopedRateThrottle, "THROTTLE_RATES", {**ScopedRateThrottle.THROTTLE_RATES, "voice_audio": "1/min"}
    )
    assert _upload(api_client, webm()).status_code == 200
    assert _upload(api_client, webm()).status_code == 429


def test_speak_without_a_server_voice(api_client, db):
    response = api_client.post(SPEAK, {"text": "Opening your cart."}, format="json")
    assert response.status_code == 503 and response.json()["error"]["code"] == "speech_unavailable"


def test_speak_with_a_server_voice(api_client, tts, db):
    provider = tts()
    response = api_client.post(SPEAK, {"text": "Total ₹3,990.", "language": "en"}, format="json")
    assert response.status_code == 200 and response["Content-Type"] == "audio/mpeg"
    assert response["Cache-Control"] == "no-store" and response.content == b"ID3fake-mp3"
    assert provider.said == [("Total 3990 rupees.", "en")]


def test_speak_limits(api_client, tts, db, settings):
    tts(error=SpeechError("down"))
    assert api_client.post(SPEAK, {"text": "x" * 401}, format="json").status_code == 400
    assert api_client.post(SPEAK, {"text": "hello"}, format="json").status_code == 503


# --- Providers -------------------------------------------------------------------------------------------


def test_unknown_provider_names_mean_none(settings):
    settings.SPEECH_STT_PROVIDER = "typo"
    settings.SPEECH_TTS_PROVIDER = "typo"
    speech.reset_speech_providers()
    try:
        assert speech.get_stt_provider().name == "none" and speech.get_tts_provider().name == "none"
    finally:
        speech.reset_speech_providers()


class FakeResponse:
    def __init__(self, body: bytes, content_type="application/json"):
        self.body = body
        self.headers = {"Content-Type": content_type}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_openai_compatible_transcription(monkeypatch, settings):
    settings.SPEECH_BASE_URL = "https://speech.example.com/v1"
    settings.SPEECH_API_KEY = "key-123"
    seen = {}

    def urlopen(req, timeout):
        seen.update(
            url=req.full_url, body=req.data, auth=req.get_header("Authorization"), type=req.get_header("Content-type")
        )
        return FakeResponse(json.dumps({"text": " दस बोरी सीमेंट "}).encode())

    monkeypatch.setattr(speech_base.urllib.request, "urlopen", urlopen)
    result = speech_providers.OpenAICompatibleSTTProvider("whisper-1").transcribe(
        webm(), language="hinglish", content_type="audio/webm"
    )
    assert result.text == "दस बोरी सीमेंट"
    assert seen["url"] == "https://speech.example.com/v1/audio/transcriptions" and seen["auth"] == "Bearer key-123"
    assert seen["type"].startswith("multipart/form-data; boundary=")
    assert b'name="model"\r\n\r\nwhisper-1' in seen["body"] and b'name="language"\r\n\r\nhi' in seen["body"]
    assert b'filename="recording.webm"' in seen["body"]


def test_openai_compatible_voice(monkeypatch, settings):
    settings.SPEECH_BASE_URL = "https://speech.example.com/v1"
    monkeypatch.setattr(
        speech_base.urllib.request, "urlopen", lambda req, timeout: FakeResponse(b"ID3audio", "audio/mpeg")
    )
    audio = speech_providers.OpenAICompatibleTTSProvider().synthesize("Hello", language="en")
    assert audio == SpeechAudio(b"ID3audio", "audio/mpeg")
    monkeypatch.setattr(
        speech_base.urllib.request, "urlopen", lambda req, timeout: FakeResponse(b"<html>", "text/html")
    )
    with pytest.raises(SpeechError):
        speech_providers.OpenAICompatibleTTSProvider().synthesize("Hello")


def test_plain_http_to_a_remote_server_is_refused(settings):
    settings.SPEECH_BASE_URL = "http://speech.example.com/v1"
    with pytest.raises(SpeechUnavailable):
        speech_providers.OpenAICompatibleSTTProvider().transcribe(webm(), language="en")


class _Segment:
    def __init__(self, text, avg_logprob=-0.1, no_speech_prob=0.01):
        self.text, self.avg_logprob, self.no_speech_prob = text, avg_logprob, no_speech_prob


@pytest.fixture
def fake_whisper(monkeypatch):
    """A stand-in `faster_whisper` module: decode gives `seconds` of silence, the model echoes its settings."""
    state = {"seconds": 2.0, "decode_error": False, "calls": []}

    class WhisperModel:
        def __init__(self, name, **kwargs):
            state["loaded"] = (name, kwargs)

        def transcribe(self, samples, **kwargs):
            state["calls"].append(kwargs)
            segments = [_Segment(" 10 bags "), _Segment("cement."), _Segment(" [music]", no_speech_prob=0.95)]
            return iter(segments), types.SimpleNamespace(language=kwargs.get("language") or "en")

    def decode_audio(file, sampling_rate):
        if state["decode_error"]:
            raise ValueError("Invalid data found when processing input")
        return [0.0] * int(state["seconds"] * sampling_rate)

    module = types.SimpleNamespace(WhisperModel=WhisperModel, decode_audio=decode_audio)
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return state


def test_local_whisper(fake_whisper, settings):
    settings.SPEECH_MODEL_LOCAL_ONLY = True
    provider = speech_providers.FasterWhisperSTTProvider("small")
    result = provider.transcribe(webm(), language="hinglish")
    assert result.text == "10 bags cement." and result.duration == 2.0 and 0 < result.confidence <= 1
    assert fake_whisper["loaded"] == ("small", {"device": "cpu", "compute_type": "int8", "local_files_only": True})
    call = fake_whisper["calls"][0]
    assert call["language"] == "hi" and call["vad_filter"] is True and "बोरी" in call["initial_prompt"]
    assert provider.describe()["loaded"] is True


def test_local_whisper_limits_and_broken_files(fake_whisper, settings):
    provider = speech_providers.FasterWhisperSTTProvider()
    fake_whisper["seconds"] = settings.VOICE_MAX_AUDIO_SECONDS + 1
    with pytest.raises(AudioTooLong):
        provider.transcribe(webm(), language="en")
    assert "loaded" not in fake_whisper  # refused before loading the model
    fake_whisper["seconds"], fake_whisper["decode_error"] = 2.0, True
    with pytest.raises(SpeechError):
        provider.transcribe(webm(), language="en")


def test_local_whisper_end_to_end_through_the_api(api_client, fake_whisper, shop, monkeypatch):
    provider = speech_providers.FasterWhisperSTTProvider("small")
    monkeypatch.setattr(voice, "get_stt_provider", lambda: provider)
    heard = _upload(api_client, webm(), language="en").json()
    assert heard["text"] == "10 bags cement."
    body = api_client.post(COMMAND, {"transcript": heard["text"], "language": "en"}, format="json").json()
    assert body["intent"] == "add_to_cart" and body["lines"][0]["quantity"] == 10
