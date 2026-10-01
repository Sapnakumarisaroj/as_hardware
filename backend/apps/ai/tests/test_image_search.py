"""Photo search (Phase 14): validation, cleaning, identification outcomes, catalogue-only matching,
fallbacks, history isolation, limits and the vision providers."""

import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.throttling import ScopedRateThrottle

from apps.ai.models import AIConversation
from apps.ai.services import image_search, vision_kinds
from apps.ai.services.image_input import clean_image
from apps.catalog.models import Product, ProductVariant
from apps.core.testing import create_category, create_product, create_store
from integrations.vision import Guess, VisionError, VisionProvider, VisionResult, VisionUnavailable
from integrations.vision import base as vision_base
from integrations.vision import providers as vision_providers

pytestmark = pytest.mark.django_db

URL = "/api/ai/image-search/"
HISTORY = "/api/ai/image-searches/"


# --- Helpers ------------------------------------------------------------------------------------------


def photo(fmt="JPEG", size=(240, 180), color=(180, 120, 60), **save) -> bytes:
    image = Image.new("RGB", size, color)
    out = io.BytesIO()
    image.save(out, format=fmt, **save)
    return out.getvalue()


def upload(data: bytes | None = None, name="photo.jpg", content_type="image/jpeg"):
    return SimpleUploadedFile(name, photo() if data is None else data, content_type=content_type)


class FakeVision(VisionProvider):
    """Answers what the test tells it to and records what it was shown."""

    name = "fake"
    model = "fake-1"

    def __init__(self, guesses=(("claw hammer", 0.9),), *, calibrated=True, is_hardware=None, error=None, up=True):
        self.guesses = [
            Guess(label, conf, search) for label, conf, *rest in guesses for search in [rest[0] if rest else ""]
        ]
        self.calibrated = calibrated
        self.is_hardware = is_hardware
        self.error = error
        self.up = up
        self.seen = []

    @property
    def available(self):
        return self.up

    def identify(self, image, kinds):
        self.seen.append(image)
        if self.error:
            raise self.error
        return VisionResult(
            guesses=list(self.guesses),
            is_hardware=self.is_hardware,
            calibrated=self.calibrated,
            provider=self.name,
            model=self.model,
        )


@pytest.fixture
def vision(monkeypatch):
    """Install a fake provider: `vision(...)` returns it."""

    def install(*args, **kwargs):
        provider = FakeVision(*args, **kwargs)
        monkeypatch.setattr(image_search, "get_vision_provider", lambda: provider)
        return provider

    return install


@pytest.fixture
def shop():
    store = create_store()
    tools = create_category("Tools")
    hammers = create_category("Hammers", parent=tools)
    plumbing = create_category("Plumbing")
    made = {}
    for key, name, price, category, sub, tags in [
        ("hammer", "Claw Hammer", "450.00", tools, hammers, ["hammer"]),
        ("mallet", "Rubber Mallet Hammer", "300.00", tools, hammers, ["hammer", "mallet"]),
        ("tap", "Brass Pillar Tap", "899.00", plumbing, None, ["tap", "faucet"]),
        ("tape", "PTFE Thread Seal Tape", "60.00", plumbing, None, ["ptfe", "leak"]),
        ("drill", "Corded Impact Drill", "3200.00", tools, None, ["drill"]),
        ("bits", "Masonry Drill Bit Set", "329.00", tools, None, ["drill bit"]),
    ]:
        made[key], _ = create_product(
            name=name, price=price, mrp=price, category=category, subcategory=sub, tags=tags, stock=5, store=store
        )
    return made


def _search(client, data=None, **extra):
    return client.post(URL, {"image": upload(data, **extra)}, format="multipart")


# --- Status -------------------------------------------------------------------------------------------


def test_status_is_public_and_reveals_no_secrets(api_client, settings):
    settings.ANTHROPIC_API_KEY = "sk-secret-value"
    body = api_client.get(URL).json()
    assert body["enabled"] is False and body["provider"] == "none"
    assert body["max_megabytes"] == 8 and "image/webp" in body["accepted_types"]
    assert "sk-secret" not in str(body)


def test_status_with_a_provider(api_client, vision):
    vision()
    body = api_client.get(URL).json()
    assert body["enabled"] is True and body["available"] is True and body["calibrated"] is True


# --- A real match -------------------------------------------------------------------------------------


def test_identified_photo_returns_real_products_with_database_prices(api_client, vision, shop):
    vision([("claw hammer", 0.91, "hammer")])
    response = _search(api_client)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "identified" and body["status_text"] == "Identified"
    assert body["identification"]["label"] == "claw hammer"
    assert body["identification"]["percent"] == 91 and body["identification"]["level"] == "high"
    assert "91% sure" in body["explanation"]
    names = [p["name"] for p in body["products"]]
    assert names[0] == "Claw Hammer" and "Rubber Mallet Hammer" in names
    real = {p.name: p for p in Product.objects.all()}
    for card in body["products"]:
        assert card["name"] in real
        variant = ProductVariant.objects.get(pk=card["variant_id"])
        assert variant.product.name == card["name"]
        assert Decimal(card["price"]) == variant.price
        assert card["reason"] == "Matches “claw hammer”" and card["match_confidence"] == 0.91
    assert body["id"] is None  # anonymous: nothing is kept
    assert not AIConversation.objects.exists()


def test_photo_is_cleaned_before_the_model_sees_it(api_client, vision):
    provider = vision()
    exif = Image.Exif()
    exif[0x0112] = 6  # rotated: the phone held upright
    exif[0x8825] = {2: (18.0, 31.0, 0.0)}  # GPS latitude
    big = Image.new("RGBA", (2400, 1200), (10, 20, 30, 0))
    out = io.BytesIO()
    big.convert("RGB").save(out, format="JPEG", exif=exif)
    assert _search(api_client, out.getvalue()).status_code == 200
    seen = provider.seen[0]
    assert seen.mode == "RGB" and max(seen.size) == 1024
    assert seen.size[1] > seen.size[0]  # orientation applied
    assert not seen.info.get("exif") and not seen.getexif()


def test_transparent_png_and_webp_are_accepted(api_client, vision):
    vision()
    png = io.BytesIO()
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(png, format="PNG")
    assert _search(api_client, png.getvalue(), name="x.png", content_type="image/png").status_code == 200
    assert _search(api_client, photo("WEBP"), name="x.webp", content_type="image/webp").status_code == 200


# --- Invalid input ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"%PDF-1.4 not an image at all", "image_invalid"),
        (b"just text renamed to .jpg", "image_invalid"),
        (photo()[:400], "image_invalid"),  # truncated
        (photo("GIF"), "image_unsupported"),
        (photo("BMP"), "image_unsupported"),
        (photo(size=(20, 20)), "image_too_small"),
        (b"", "image_empty"),
    ],
    ids=["pdf", "text", "truncated", "gif", "bmp", "tiny", "empty"],
)
def test_files_that_are_not_usable_photos_are_refused(api_client, vision, data, code):
    provider = vision()
    response = _search(api_client, data)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code
    assert provider.seen == []  # the model never sees a refused file


def test_no_file(api_client, vision):
    vision()
    response = api_client.post(URL, {}, format="multipart")
    assert response.status_code == 400 and response.json()["error"]["code"] == "image_required"


def test_oversized_photo_is_refused(api_client, vision, settings):
    provider = vision()
    settings.IMAGE_SEARCH_MAX_BYTES = 2000
    response = _search(api_client, photo(size=(800, 800), quality=95))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "image_too_large"
    assert provider.seen == []


def test_oversized_body_is_refused_before_it_is_parsed(api_client, vision, settings):
    vision()
    settings.IMAGE_SEARCH_MAX_BYTES = 1000
    response = api_client.generic("POST", URL, data=b"x" * 400_000, content_type="multipart/form-data; boundary=zzz")
    assert response.status_code == 413


def test_decompression_bomb_is_refused(api_client, vision, monkeypatch):
    vision()
    from apps.ai.services import image_input

    monkeypatch.setattr(image_input, "MAX_PIXELS", 10_000)
    response = _search(api_client, photo(size=(200, 200)))
    assert response.status_code == 400 and response.json()["error"]["code"] == "image_too_many_pixels"


# --- Outcomes -----------------------------------------------------------------------------------------


def test_uncertain_identification_says_so_and_shows_possible_matches(api_client, vision, shop):
    vision([("claw hammer", 0.32, "hammer"), ("water tap", 0.21, "tap"), ("drill bit", 0.12, "drill bit")])
    body = _search(api_client).json()
    assert body["status"] == "uncertain" and body["status_text"] == "Not sure"
    assert body["identification"]["level"] == "low"
    assert "not sure" in body["explanation"].lower()
    assert [a["label"] for a in body["alternatives"]] == ["water tap", "drill bit"]
    reasons = {p["name"]: p["reason"] for p in body["products"]}
    assert reasons["Claw Hammer"] == "Possible match: claw hammer (32%)"
    assert reasons["Brass Pillar Tap"] == "Possible match: water tap (21%)"
    assert "PTFE Thread Seal Tape" not in reasons  # "tap" is inside "Tape", but a tape is not a tap


def test_not_a_hardware_item(api_client, vision, shop):
    vision([("an animal", 0.88), ("claw hammer", 0.05, "hammer")])
    body = _search(api_client).json()
    assert body["status"] == "not_hardware" and body["products"] == []
    assert "an animal" in body["explanation"]


def test_identified_but_not_sold_here(api_client, vision, shop):
    vision([("padlock", 0.97, "padlock")])
    body = _search(api_client).json()
    assert body["status"] == "no_match" and body["products"] == []
    assert body["search_query"] == "padlock"
    assert "don’t have this in our catalogue" in body["explanation"]


def test_only_published_active_products_are_ever_shown(api_client, vision, shop):
    hidden, _ = create_product(name="Secret Claw Hammer", price="1.00", category=shop["hammer"].category, stock=3)
    hidden.is_published = False
    hidden.save()
    gone, _ = create_product(name="Deleted Claw Hammer", price="1.00", category=shop["hammer"].category, stock=3)
    gone.delete()
    vision([("claw hammer", 0.9, "hammer")])
    names = [p["name"] for p in _search(api_client).json()["products"]]
    assert "Secret Claw Hammer" not in names and "Deleted Claw Hammer" not in names


def test_a_more_specific_item_is_not_offered_as_the_general_one(api_client, vision, shop):
    vision([("electric drill", 0.8, "drill")])
    names = [p["name"] for p in _search(api_client).json()["products"]]
    assert names == ["Corded Impact Drill"]  # the drill *bit* set is a different item


def test_products_related_only_by_tag_are_labelled_as_related(api_client, vision, shop):
    shop["tape"].tags = ["ptfe", "tap"]
    shop["tape"].save()
    vision([("water tap", 0.9, "tap")])
    cards = {p["name"]: p["reason"] for p in _search(api_client).json()["products"]}
    assert cards["Brass Pillar Tap"] == "Matches “water tap”"
    assert cards["PTFE Thread Seal Tape"] == "Related to “water tap”"


def test_a_models_own_confidence_is_capped_and_flagged(api_client, vision, shop):
    vision([("claw hammer", 0.99, "hammer")], calibrated=False)
    body = _search(api_client).json()
    assert body["status"] == "identified"
    assert body["identification"]["confidence"] == 0.8 and body["identification"]["calibrated"] is False
    assert "best guess" in body["explanation"] and "can be wrong" in body["notice"]


def test_a_models_loose_alternatives_do_not_bring_products_when_it_is_sure(api_client, vision, shop):
    vision([("water tap", 0.9, "tap"), ("drill bit", 0.36, "drill bit")], calibrated=False)
    body = _search(api_client).json()
    assert [p["name"] for p in body["products"]] == ["Brass Pillar Tap"]
    assert [a["label"] for a in body["alternatives"]] == ["drill bit"]  # still offered as a suggestion


def test_a_model_saying_not_hardware_is_believed(api_client, vision, shop):
    vision([("coffee mug", 0.7)], calibrated=False, is_hardware=False)
    assert _search(api_client).json()["status"] == "not_hardware"


# --- Fallbacks ----------------------------------------------------------------------------------------


def test_photo_search_off_gives_a_clear_answer_not_an_error(api_client, shop):
    response = _search(api_client)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable" and body["products"] == []
    assert "Describe the item in words" in body["explanation"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"error": VisionUnavailable("ollama is not running")},
        {"error": VisionError("garbled answer")},
        {"error": RuntimeError("model crashed")},
        {"up": False},
    ],
)
def test_a_failing_or_missing_model_falls_back(api_client, vision, shop, kwargs):
    vision(**kwargs)
    response = _search(api_client)
    assert response.status_code == 200 and response.json()["status"] == "unavailable"


def test_the_same_photo_is_analysed_once(api_client, vision, shop):
    provider = vision([("claw hammer", 0.9, "hammer")])
    _search(api_client)
    second = _search(api_client).json()
    assert len(provider.seen) == 1
    assert second["identification"]["label"] == "claw hammer" and second["products"]


# --- History and isolation ----------------------------------------------------------------------------


def test_signed_in_searches_are_kept_without_the_photo(auth_client, user, vision, shop):
    vision([("claw hammer", 0.9, "hammer")])
    body = _search(auth_client).json()
    assert body["id"]
    conversation = AIConversation.objects.get(pk=body["id"])
    assert conversation.user == user and conversation.kind == AIConversation.Kind.IMAGE
    assert set(conversation.metadata["image"]) == {"format", "width", "height", "bytes", "fingerprint"}
    listing = auth_client.get(HISTORY).json()
    row = listing["results"][0]
    assert row["label"] == "claw hammer" and row["status"] == "identified" and row["product_count"] == 2
    # the assistant's conversation list is a different thing
    assert auth_client.get("/api/ai/conversations/").json()["results"] == []


def test_history_shows_live_prices(auth_client, vision, shop):
    vision([("claw hammer", 0.9, "hammer")])
    search_id = _search(auth_client).json()["id"]
    ProductVariant.objects.filter(product=shop["hammer"]).update(price=Decimal("399.00"))
    detail = auth_client.get(f"{HISTORY}{search_id}/").json()
    card = next(p for p in detail["products"] if p["name"] == "Claw Hammer")
    assert card["price"] == "399.00" and detail["status"] == "identified"


def test_nobody_else_can_read_or_delete_a_search(auth_client, other_user, api_client, vision, shop):
    vision([("claw hammer", 0.9, "hammer")])
    search_id = _search(auth_client).json()["id"]
    api_client.force_authenticate(other_user)
    assert api_client.get(f"{HISTORY}{search_id}/").status_code == 404
    assert api_client.delete(f"{HISTORY}{search_id}/").status_code == 404
    assert api_client.get(HISTORY).json()["results"] == []
    api_client.post(f"{HISTORY}clear/")
    assert AIConversation.objects.filter(pk=search_id).exists()
    api_client.force_authenticate(None)
    assert api_client.get(HISTORY).status_code == 401
    assert api_client.get(f"{HISTORY}{search_id}/").status_code == 401


def test_customers_can_delete_one_or_all_of_their_searches(auth_client, vision, shop):
    vision([("claw hammer", 0.9, "hammer")])
    first = _search(auth_client).json()["id"]
    _search(auth_client, photo(color=(1, 2, 3)))
    assert auth_client.delete(f"{HISTORY}{first}/").status_code == 204
    assert len(auth_client.get(HISTORY).json()["results"]) == 1
    assert auth_client.post(f"{HISTORY}clear/").status_code == 204
    assert auth_client.get(HISTORY).json()["results"] == []


def test_photo_search_is_rate_limited(api_client, vision, shop, monkeypatch):
    vision()
    monkeypatch.setattr(
        ScopedRateThrottle, "THROTTLE_RATES", {**ScopedRateThrottle.THROTTLE_RATES, "image_search": "2/min"}
    )
    assert _search(api_client).status_code == 200
    assert _search(api_client).status_code == 200
    assert _search(api_client).status_code == 429
    assert api_client.get(URL).status_code == 200  # the status endpoint isn't limited


def test_the_cart_add_uses_the_returned_variant(auth_client, vision, shop):
    vision([("claw hammer", 0.9, "hammer")])
    card = _search(auth_client).json()["products"][0]
    response = auth_client.post("/api/cart/items/", {"variant_id": card["variant_id"], "quantity": 1}, format="json")
    assert response.status_code in (200, 201), response.json()


# --- Kinds and providers (units) ----------------------------------------------------------------------


def test_kinds_include_specific_subcategories_but_not_shelf_names():
    tools = create_category("Tools")
    create_category("Torque Wrenches", parent=tools)
    create_category("Electrical Tools", parent=tools)
    create_category("Taps & Faucets", parent=tools)
    labels = {k.label for k in vision_kinds.all_kinds()}
    assert "torque wrenches" in labels
    assert "electrical tools" not in labels and "taps & faucets" not in labels and "tools" not in labels
    assert "an animal" in labels and "claw hammer" in labels


def test_vision_model_answers_are_parsed_defensively():
    result = vision_base.parse_answer(
        {"item": "Claw Hammer", "confidence": "85", "alternatives": ["mallet", "Claw Hammer"], "is_hardware": True},
        provider="x",
        model="y",
    )
    assert result.guesses[0] == Guess("claw hammer", 0.85, "claw hammer")
    assert [g.label for g in result.guesses] == ["claw hammer", "mallet"]
    assert result.calibrated is False and result.is_hardware is True
    with pytest.raises(VisionError):
        vision_base.parse_answer({"confidence": 1}, provider="x", model="y")


def test_ollama_vision_sends_the_photo_and_reports_a_missing_model(monkeypatch, settings):
    sent = {}

    def fake_post(url, body, **kwargs):
        sent.update(url=url, body=body)
        return {"message": {"content": '{"item": "pipe wrench", "confidence": 0.7, "is_hardware": true}'}}

    monkeypatch.setattr(vision_providers, "post_json", fake_post)
    provider = vision_providers.OllamaVisionProvider("qwen2.5vl:3b")
    image = Image.new("RGB", (64, 64))
    result = provider.identify(image, vision_kinds.all_kinds())
    assert result.guesses[0].label == "pipe wrench"
    assert sent["url"].endswith("/api/chat") and sent["body"]["model"] == "qwen2.5vl:3b"
    assert sent["body"]["messages"][0]["images"][0]  # base64 JPEG
    monkeypatch.setattr(vision_providers, "post_json", lambda *a, **k: {"error": "model 'x' not found"})
    with pytest.raises(VisionUnavailable):
        provider.identify(image, [])


def test_hosted_vision_providers_need_configuration(settings):
    settings.ANTHROPIC_API_KEY = ""
    settings.OPENAI_COMPATIBLE_BASE_URL = ""
    image = Image.new("RGB", (64, 64))
    for provider in (vision_providers.AnthropicVisionProvider(), vision_providers.OpenAICompatibleVisionProvider()):
        assert provider.available is False
        with pytest.raises(VisionUnavailable):
            provider.identify(image, [])


def test_clip_provider_returns_probabilities_over_the_kinds(monkeypatch):
    np = pytest.importorskip("numpy")

    class FakeClip:
        def encode(self, items, **kwargs):
            if isinstance(items[0], str):  # prompts: hammer prompts point one way, the rest another
                return np.array([[1.0, 0.0] if "hammer" in t else [0.0, 1.0] for t in items], dtype="float32")
            return np.array([[0.98, 0.2]], dtype="float32")

    provider = vision_providers.ClipVisionProvider("fake-clip")
    monkeypatch.setattr(provider, "_load", lambda: FakeClip())
    kinds = [k for k in vision_kinds.all_kinds() if k.label in ("claw hammer", "water tap", "padlock")]
    result = provider.identify(Image.new("RGB", (64, 64)), kinds)
    assert result.calibrated is True and result.guesses[0].label == "claw hammer"
    assert result.guesses[0].search == "hammer"
    assert abs(sum(g.confidence for g in result.guesses) - 1.0) < 0.01


def test_clean_image_keeps_only_a_summary():
    clean = clean_image(upload())
    assert set(clean.summary()) == {"format", "width", "height", "bytes", "fingerprint"}
    assert clean.format == "JPEG" and clean.width == 240
