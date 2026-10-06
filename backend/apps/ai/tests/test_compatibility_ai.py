"""Phase 21 in the AI features: the assistant answers compatibility questions with the engine's verdict (the model
may only reword it), voice asks through the same service, project kits and Quantity AI flag lines that don't fit
and pick matching variants."""

import json

import pytest

from apps.ai.projects import kit
from apps.ai.services.assistant import HardwareAssistantService
from apps.ai.services.compatibility import CompatibilityAssistant
from apps.ai.services.voice import VoiceShoppingService
from apps.catalog.compatibility.rules import COMPATIBLE, NOT, POSSIBLY
from apps.catalog.tests.test_compatibility import hw  # noqa: F401 — the shared catalogue fixture
from integrations.llm import LLMProvider, LLMReply

CONVERSATIONS = "/api/ai/conversations/"


class FakeModel(LLMProvider):
    name = "fake"

    def __init__(self, explanation: str):
        self.explanation, self.calls = explanation, 0

    @property
    def available(self) -> bool:
        return True

    def chat(self, messages, options=None):
        self.calls += 1
        facts = json.loads(messages[-1]["content"])
        assert facts["verdict"] and "checks" in facts  # the model gets the engine's facts, not a question to decide
        return LLMReply(json.dumps({"explanation": self.explanation}))


def ask(text, **kwargs):
    return HardwareAssistantService(LLMProvider()).answer(text, **kwargs)


# --- Assistant -----------------------------------------------------------------------------------------------


def test_assistant_answers_with_the_engines_verdict(hw):  # noqa: F811
    reply = ask("Will the masonry drill bit set work with the cordless drill?")
    assert reply.compatibility["verdict"] == POSSIBLY and reply.message.startswith("⚠️ Possibly compatible")
    assert "the 12 mm won't fit" in reply.message
    assert [m.product.name for m in reply.products][:2] == ["Masonry Drill Bit Set", "Cordless Drill 12V"]
    reply = ask("Is a CPVC elbow compatible with UPVC pipe?")
    assert reply.compatibility["verdict"] == NOT and "can't be solvent-joined" in reply.message
    reply = ask("Kya modular switch 6A modular socket 16A ke saath chalega?")
    assert (
        reply.language == "hinglish"
        and reply.compatibility["verdict"] == NOT
        and reply.message.startswith("❌ Compatible nahi hai")
    )


def test_this_product_and_sizes_said(hw):  # noqa: F811
    reply = ask("Will this work with the impact drill?", product_id=hw["masonry"].pk)
    assert reply.compatibility["verdict"] == COMPATIBLE and reply.compatibility["product_a"]["id"] == hw["masonry"].pk
    reply = ask("will the 16 A MCB work with 1.5 sq mm wire")
    assert reply.compatibility["verdict"] == NOT and "(16 A)" in reply.message and "(1.5 sq mm)" in reply.message
    reply = ask("Which screws are compatible with this wall plug?", product_id=hw["plugs6"].pk)
    assert reply.compatibility["product_a"]["id"] == hw["plugs6"].pk
    reply = ask("show accessories that work with this product", product_id=hw["impact"].pk)
    assert "Masonry Drill Bit Set" in reply.message


def test_vague_questions_ask_which_products(hw):  # noqa: F811
    reply = ask("Will this drill bit work with this drill?")
    assert reply.compatibility["needs_products"] and reply.message.startswith("Tell me both products")
    assert {"Masonry Drill Bit Set", "Impact Drill 13 mm"} <= {m.product.name for m in reply.products}


def test_the_model_only_rewords_and_cannot_add_facts(hw):  # noqa: F811
    model = FakeModel("The drill's 10 mm chuck can't hold the biggest bits, and it has no hammer action.")
    reply = CompatibilityAssistant(model).answer("Will the masonry drill bit set work with the cordless drill?")
    assert model.calls == 1 and reply.compatibility["verdict"] == POSSIBLY and reply.compatibility["explained_by_ai"]
    assert reply.message.startswith("⚠️ Possibly compatible") and "Explained by the AI helper" in reply.message
    liar = FakeModel("Totally compatible, it has a 16 mm chuck.")  # 16 isn't in the facts
    reply = CompatibilityAssistant(liar).answer("Will the masonry drill bit set work with the cordless drill?")
    assert reply.compatibility["verdict"] == POSSIBLY and not reply.compatibility["explained_by_ai"]
    assert "16 mm" not in reply.message and "the 12 mm won't fit" in reply.message


def test_assistant_api_stores_the_verdict_and_uses_the_viewed_product(auth_client, hw):  # noqa: F811
    body = {"message": "Will this work with the impact drill?", "product_id": hw["masonry"].pk}
    data = auth_client.post(CONVERSATIONS, body, format="json").json()
    answer = data["messages"][-1]
    assert answer["compatibility"]["verdict"] == COMPATIBLE
    assert [p["name"] for p in answer["products"]][:2] == ["Masonry Drill Bit Set", "Impact Drill 13 mm"]


# --- Voice -------------------------------------------------------------------------------------------------


def test_voice_compatibility_question(hw):  # noqa: F811
    reply = VoiceShoppingService().command("will the masonry drill bit set work with the cordless drill", language="en")
    assert reply.intent == "compatibility" and reply.compatibility["verdict"] == POSSIBLY
    assert not reply.needs_confirmation and reply.products[0]["product_id"] == hw["masonry"].pk
    assert reply.payload()["compatibility"]["verdict"] == POSSIBLY
    order = VoiceShoppingService().command("2 packets of wall plugs", language="en")
    assert order.intent == "add_to_cart"


# --- Project builder ---------------------------------------------------------------------------------------


def test_project_kit_flags_a_bit_that_may_not_fit_and_offers_options(auth_client, hw):  # noqa: F811
    plan = auth_client.post(
        "/api/ai/projects/",
        {"description": "install 2 shelves on a concrete wall, I don't have a drill"},
        format="json",
    ).json()
    items = {i["material_key"]: i for i in plan["kit"]["items"]}
    assert (
        items["drill"]["product"]["name"] == "Impact Drill 13 mm"
        and items["drill_bit"]["product"]["name"] == "Masonry Drill Bit Set"
    )
    assert plan["kit"]["compatibility"] == []  # the suggested kit fits together; plugs and screws aligned
    screws, plugs = items["screws"], items["wall_plugs"]
    assert plugs["product"]["name"] == "Nylon Wall Plugs 6 mm" and screws["variant"]["name"] == "No. 8 x 25 mm"
    cordless = hw["cordless"].variants.first()
    plan = auth_client.patch(
        f"/api/ai/projects/{plan['id']}/items/{items['drill']['id']}/", {"variant_id": cordless.pk}, format="json"
    ).json()
    [problem] = [p for p in plan["kit"]["compatibility"] if items["drill_bit"]["id"] in p["keys"]]
    assert problem["verdict"] == POSSIBLY and "may not work" in problem["message"]
    assert all(o["product"]["name"] for o in problem["options"])


def test_project_compatibility_is_private(auth_client, other_user, api_client, hw):  # noqa: F811
    plan = auth_client.post(
        "/api/ai/projects/",
        {"description": "install 2 shelves on a concrete wall, I don't have a drill"},
        format="json",
    ).json()
    api_client.force_authenticate(other_user)
    assert api_client.get(f"/api/ai/projects/{plan['id']}/").status_code == 404


# --- Quantity AI -------------------------------------------------------------------------------------------


def test_quantity_flags_a_fitting_that_does_not_fit_the_pipe(api_client, hw):  # noqa: F811
    data = api_client.post("/api/ai/quantity/", {"text": "20 m CPVC pipe 3/4 inch with 4 elbows"}, format="json").json()
    items = {i["material_key"]: i for i in data["kit"]["items"]}
    assert items["pipe"]["variant"]["name"] == "3/4 inch" and items["elbows"]["variant"]["name"] == "1/2 inch"
    [problem] = data["kit"]["compatibility"]
    assert (
        problem["verdict"] == NOT and set(problem["keys"]) == {"pipe", "elbows"} and "won't work" in problem["message"]
    )


def test_quantity_variants_are_aligned_by_compatibility(hw):  # noqa: F811
    half, three_quarter = hw["cpvc_v"]
    lines = [
        {
            "material_key": "pipe",
            "label": "CPVC pipe",
            "variant": three_quarter,
            "quantity": 7,
            "details": {"need_amount": 20, "need_unit": "m"},
        },
        {
            "material_key": "valve",
            "label": "Ball valve",
            "variant": hw["valve_v"][0],
            "quantity": 1,
            "details": {"need_amount": 1, "need_unit": "pcs"},
        },
    ]
    aligned = kit.align_variants(lines)
    assert aligned[1]["variant"].pk == hw["valve_v"][1].pk and aligned[1]["details"]["aligned_with"] == "pipe"
    assert aligned[1]["details"]["pack_explanation"] == 'Chosen to match CPVC pipe: 3/4".'


@pytest.mark.parametrize("text", ["", "hello"])
def test_non_questions_go_to_the_normal_assistant(hw, text):  # noqa: F811
    reply = ask(text or "show me drills")
    assert reply.compatibility is None
