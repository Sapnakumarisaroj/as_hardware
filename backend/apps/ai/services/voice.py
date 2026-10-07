# ruff: noqa: E501 — answer sentences in three languages read better on one line
"""VoiceShoppingService (Phase 18): a spoken sentence in, an answer to show and speak out.

    transcript ("दस बोरी सीमेंट", from the browser or the server recogniser)
      → spoken.parse            what is asked: add / change quantity / yes / no / open a page / search / question
      → catalogue search        the same search + search understanding as the shop's listing (Phase 13/16)
      → quote_product           the Phase 15 pricing engine: bulk tier for that quantity, offers, stock
      → answer                  sentences in English, Hindi or Hinglish, plus the same text for the voice

Nothing is bought by voice. Adding to the cart is proposed with prices and waits for the customer's
"yes" (or a tap); the browser then uses the ordinary cart API, which prices everything again. Pages
like checkout are only opened; the customer places and pays for the order there. Questions go to the
hardware assistant (Phase 12) unchanged.
"""

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from rest_framework import status

from apps.catalog import selectors
from apps.catalog.interpret import interpret
from apps.catalog.quote import QuoteError, quote_product
from apps.core.exceptions import ServiceError
from integrations.speech import (
    AudioTooLong,
    SpeechError,
    SpeechUnavailable,
    get_stt_provider,
    get_tts_provider,
)

from . import spoken
from .catalog_match import choose_variant, find_products
from .intent import detect_language
from .schemas import LANGUAGES
from .spoken import Command

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_LENGTH = 500
ALTERNATIVES = 2
SEARCH_RESULTS = 6

LANGUAGE_OPTIONS = [
    # `speech`: what the browser listens for; `voice`: the voice that reads the answer.
    {"code": "en", "label": "English", "speech": "en-IN", "voice": "en-IN"},
    {"code": "hi", "label": "हिन्दी", "speech": "hi-IN", "voice": "hi-IN"},
    # Hinglish is spoken Hindi with English words: a Hindi recogniser hears "bori" and "cement" best.
    {"code": "hinglish", "label": "Hinglish", "speech": "hi-IN", "voice": "en-IN"},
]

EXAMPLES = {
    "en": ["5 sheets of 18 mm plywood", "4 pairs of soft close hinges", "Show me door locks", "Open my cart"],
    "hinglish": ["Paanch 18 mm plywood cart mein daalo", "Do Fevicol chahiye", "Drill dikhao", "Mera cart kholo"],
    "hi": ["पाँच 18 mm प्लाईवुड कार्ट में डालो", "दो फेविकोल", "ड्रिल दिखाओ", "मेरा कार्ट खोलो"],
}

PAGES = {
    "cart": "/cart",
    "checkout": "/checkout",
    "orders": "/account/orders",
    "wallet": "/account/wallet",
}

UNIT_WORDS = {
    "en": {
        "bag": ("bag", "bags"),
        "pack": ("pack", "packs"),
        "box": ("box", "boxes"),
        "coil": ("coil", "coils"),
        "pair": ("pair", "pairs"),
        "set": ("set", "sets"),
        "m": ("metre", "metres"),
        "kg": ("kg", "kg"),
        "l": ("litre", "litres"),
        "piece": ("piece", "pieces"),
    },
    "hi": {
        "bag": ("बोरी", "बोरी"),
        "pack": ("पैक", "पैक"),
        "box": ("डिब्बा", "डिब्बे"),
        "coil": ("कॉइल", "कॉइल"),
        "pair": ("जोड़ी", "जोड़ी"),
        "set": ("सेट", "सेट"),
        "m": ("मीटर", "मीटर"),
        "kg": ("किलो", "किलो"),
        "l": ("लीटर", "लीटर"),
        "piece": ("पीस", "पीस"),
    },
}
UNIT_WORDS["hinglish"] = UNIT_WORDS["en"]

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "line": "{amount} {name}: {unit_price} each, total {total}.",
        "line_bulk": "{amount} {name}: bulk price {unit_price} each (for {min} or more), total {total}.",
        "next_tier": "Add {more} more to pay {price} each.",
        "confirm_one": "Say “yes” or tap Add to cart.",
        "confirm_many": "Say “yes” to add everything, or tap Add on each item.",
        "assumed_one": "I took 1; say a number to change it.",
        "not_found": "I couldn't find “{query}” in our catalogue.",
        "quantity_questions": "To work out the {name}, I need a few details.",
        "quantity_intro": "{title} — estimated quantity:",
        "quantity_more": "Open the quantity calculator for the full list and the breakdown.",
        "too_many": "{name}: at most {max} per order.",
        "short_stock": "{name}: not enough in stock for {quantity} right now.",
        "unavailable": "{name} isn't available right now.",
        "whole_number": "Please say a whole number, for example “2 bags”.",
        "unit_note": "Sold per {unit}: I counted {amount}.",
        "confirmed": "Adding it to your cart.",
        "confirmed_many": "Adding them to your cart.",
        "confirmed_none": "None of these can be added right now.",
        "cancelled": "Okay, nothing added.",
        "nothing_pending": "Nothing is waiting to be added. Tell me what you need, for example “10 bags of cement”.",
        "which_item": "Which item? Say it with the number, for example “20 bags of cement”.",
        "how_many_of_what": "How many of what? For example “10 bags of cement”.",
        "unclear": "Sorry, I didn't catch that. Try “10 bags of cement” or “show me drills”.",
        "navigate_cart": "Opening your cart.",
        "navigate_checkout": "Opening checkout. Check your order there and place it yourself.",
        "navigate_orders": "Opening your orders.",
        "navigate_wallet": "Opening your wallet.",
        "search": "Here's what we have for “{query}”.",
        "search_none": "I couldn't find “{query}”. Try other words.",
        "changed": "Changed to {quantity}.",
        "offer": "Includes {offer}: −{discount}.",
        "rupees": "{amount} rupees",
    },
    "hinglish": {
        "line": "{amount} {name}: {unit_price} per unit, total {total}.",
        "line_bulk": "{amount} {name}: bulk rate {unit_price} per unit ({min} ya zyada par), total {total}.",
        "next_tier": "{more} aur lene par {price} per unit lagega.",
        "confirm_one": "“Haan” bolein ya Add to cart dabayein.",
        "confirm_many": "Sab add karne ke liye “haan” bolein, ya har item par Add dabayein.",
        "assumed_one": "Maine 1 liya hai; badalne ke liye number bolein.",
        "not_found": "Catalogue mein “{query}” nahi mila.",
        "quantity_questions": "{name} ka hisaab lagane ke liye kuch details chahiye.",
        "quantity_intro": "{title} — andazan quantity:",
        "quantity_more": "Poori list aur hisaab ke liye quantity calculator kholiye.",
        "too_many": "{name}: ek order mein zyada se zyada {max}.",
        "short_stock": "{name}: abhi {quantity} ka stock nahi hai.",
        "unavailable": "{name} abhi uplabdh nahi hai.",
        "whole_number": "Poora number bolein, jaise “2 bags”.",
        "unit_note": "Ye {unit} mein bikta hai: maine {amount} gina hai.",
        "confirmed": "Cart mein daal raha hoon.",
        "confirmed_many": "Sab cart mein daal raha hoon.",
        "confirmed_none": "Inme se abhi kuch add nahi ho sakta.",
        "cancelled": "Theek hai, kuch add nahi kiya.",
        "nothing_pending": "Abhi add karne ke liye kuch nahi hai. Batayein kya chahiye, jaise “10 bori cement”.",
        "which_item": "Kaunsa item? Number ke saath bolein, jaise “20 bori cement”.",
        "how_many_of_what": "Kis cheez ke kitne? Jaise “10 bori cement”.",
        "unclear": "Maaf kijiye, samajh nahi aaya. “10 bori cement” ya “drill dikhao” bolkar dekhein.",
        "navigate_cart": "Aapka cart khol raha hoon.",
        "navigate_checkout": "Checkout khol raha hoon. Wahan order check karke khud place karein.",
        "navigate_orders": "Aapke orders khol raha hoon.",
        "navigate_wallet": "Aapka wallet khol raha hoon.",
        "search": "“{query}” ke liye ye products hain.",
        "search_none": "“{query}” nahi mila. Doosre words try karein.",
        "changed": "{quantity} kar diya.",
        "offer": "{offer} laga: −{discount}.",
        "rupees": "{amount} rupaye",
    },
    "hi": {
        "line": "{amount} {name}: {unit_price} प्रति इकाई, कुल {total}।",
        "line_bulk": "{amount} {name}: थोक दर {unit_price} प्रति इकाई ({min} या अधिक पर), कुल {total}।",
        "next_tier": "{more} और लेने पर {price} प्रति इकाई लगेगा।",
        "confirm_one": "“हाँ” बोलें या कार्ट में डालें दबाएँ।",
        "confirm_many": "सब जोड़ने के लिए “हाँ” बोलें, या हर सामान पर जोड़ें दबाएँ।",
        "assumed_one": "मैंने 1 लिया है; बदलने के लिए संख्या बोलें।",
        "not_found": "कैटलॉग में “{query}” नहीं मिला।",
        "quantity_questions": "{name} का हिसाब लगाने के लिए कुछ जानकारी चाहिए।",
        "quantity_intro": "{title} — अनुमानित मात्रा:",
        "quantity_more": "पूरी सूची और हिसाब के लिए मात्रा कैलकुलेटर खोलें।",
        "too_many": "{name}: एक ऑर्डर में अधिकतम {max}।",
        "short_stock": "{name}: अभी {quantity} का स्टॉक नहीं है।",
        "unavailable": "{name} अभी उपलब्ध नहीं है।",
        "whole_number": "पूरी संख्या बोलें, जैसे “2 बोरी”।",
        "unit_note": "यह {unit} में बिकता है: मैंने {amount} गिना है।",
        "confirmed": "कार्ट में डाल रहा हूँ।",
        "confirmed_many": "सब कार्ट में डाल रहा हूँ।",
        "confirmed_none": "इनमें से अभी कुछ नहीं जोड़ा जा सकता।",
        "cancelled": "ठीक है, कुछ नहीं जोड़ा।",
        "nothing_pending": "अभी जोड़ने के लिए कुछ नहीं है। बताइए क्या चाहिए, जैसे “10 बोरी सीमेंट”।",
        "which_item": "कौन सा सामान? संख्या के साथ बोलें, जैसे “20 बोरी सीमेंट”।",
        "how_many_of_what": "किस चीज़ के कितने? जैसे “10 बोरी सीमेंट”।",
        "unclear": "माफ़ कीजिए, समझ नहीं आया। “10 बोरी सीमेंट” या “ड्रिल दिखाओ” बोलकर देखें।",
        "navigate_cart": "आपका कार्ट खोल रहा हूँ।",
        "navigate_checkout": "चेकआउट खोल रहा हूँ। वहाँ ऑर्डर जाँचकर खुद प्लेस करें।",
        "navigate_orders": "आपके ऑर्डर खोल रहा हूँ।",
        "navigate_wallet": "आपका वॉलेट खोल रहा हूँ।",
        "search": "“{query}” के लिए ये उत्पाद हैं।",
        "search_none": "“{query}” नहीं मिला। दूसरे शब्द आज़माएँ।",
        "changed": "{quantity} कर दिया।",
        "offer": "{offer} लागू: −{discount}।",
        "rupees": "{amount} रुपये",
    },
}


def text(language: str, key: str, **values) -> str:
    block = TEXT.get(language) or TEXT["en"]
    return (block.get(key) or TEXT["en"][key]).format(**values)


def rupees(value) -> str:
    value = Decimal(str(value))
    return f"₹{value:,.0f}" if value == value.to_integral() else f"₹{value:,.2f}"


def amount(quantity: int, unit: str, language: str) -> str:
    words = UNIT_WORDS.get(language, UNIT_WORDS["en"]).get(unit)
    if not words or unit == "piece":
        return f"{quantity} ×"
    return f"{quantity} {words[0] if quantity == 1 else words[1]}"


def for_speech(sentence: str, language: str) -> str:
    """The answer as a voice should read it: "₹4,150" → "4150 rupees", no quote marks or ×."""

    def money(match):
        return text(language, "rupees", amount=match.group(1).replace(",", ""))

    sentence = re.sub(r"₹\s?([\d,]+(?:\.\d+)?)", money, sentence)
    sentence = sentence.replace("×", "").replace("−", "").replace("“", "").replace("”", "")
    sentence = re.sub(r"\s+", " ", sentence).strip()
    limit = settings.VOICE_MAX_SPEAK_CHARS
    if len(sentence) > limit:
        cut = max(sentence.rfind(mark, 0, limit) for mark in (".", "।", "?", "!"))
        sentence = sentence[: cut + 1] if cut > limit // 3 else sentence[:limit]
    return sentence


# --- Errors ----------------------------------------------------------------------------------------


class VoiceInputError(ServiceError):
    default_code = "audio_invalid"
    default_detail = "We couldn't use that recording. Try again, or type what you need."


class AudioTooLarge(VoiceInputError):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_code = "audio_too_large"


class AudioUnsupported(VoiceInputError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    default_code = "unsupported_audio"
    default_detail = "That recording format isn't supported. Use WebM, Ogg, WAV, MP4 or MP3 audio."


class SpeechServiceUnavailable(ServiceError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "speech_unavailable"
    default_detail = "Voice input on the server isn't available. Type what you need instead."


# --- Audio -----------------------------------------------------------------------------------------


def sniff_audio(data: bytes) -> str | None:
    """The audio format by its first bytes (never by the file name or the browser's content type)."""
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "audio/webm"  # WebM/Matroska: Chrome, Edge, Firefox recordings
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data[4:8] == b"ftyp":
        return "audio/mp4"  # Safari / iPhone recordings
    if data.startswith(b"fLaC"):
        return "audio/flac"
    if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    return None


def read_audio(upload) -> tuple[bytes, str]:
    """Check a recording and return its bytes and format. Recordings are never stored."""
    limit = settings.VOICE_MAX_AUDIO_BYTES
    if upload is None:
        raise VoiceInputError("Record something first.", code="audio_missing")
    if upload.size and upload.size > limit:
        raise AudioTooLarge(f"The recording is too long ({limit // 1024} KB at most).")
    data = upload.read(limit + 1)
    if len(data) > limit:
        raise AudioTooLarge(f"The recording is too long ({limit // 1024} KB at most).")
    if len(data) < 64:
        raise VoiceInputError("The recording is empty.", code="audio_empty")
    content_type = sniff_audio(data)
    if content_type is None:
        raise AudioUnsupported()
    return data, content_type


# --- The answer --------------------------------------------------------------------------------------


@dataclass
class VoiceReply:
    transcript: str
    language: str
    intent: str
    reply: str = ""
    lines: list[dict] = field(default_factory=list)  # proposed / confirmed cart lines (product refs, not cards)
    products: list[dict] = field(default_factory=list)  # refs: search results or the assistant's products
    navigate: dict | None = None
    search_path: str = ""
    needs_confirmation: bool = False
    add_now: bool = False  # the customer said yes: the browser adds the `ready` lines through the cart API
    ai_mode: str = "basic"
    questions: list[str] = field(default_factory=list)
    notice: str = ""
    quantity: dict | None = None  # Phase 20: a quantity request ({calculator, title, complete, path})
    compatibility: dict | None = None  # Phase 21: the compatibility engine's verdict

    @property
    def speech(self) -> str:
        # The assistant's longer answers add general information after a blank line: say the first part only.
        spoken_text = self.reply.split("\n\n")[0]
        if self.questions:
            spoken_text = f"{spoken_text} {self.questions[0]}"
        return for_speech(spoken_text, self.language)

    def payload(self) -> dict:
        return {
            "transcript": self.transcript,
            "language": self.language,
            "intent": self.intent,
            "reply": self.reply,
            "speech": self.speech,
            "lines": self.lines,
            "navigate": self.navigate,
            "search_path": self.search_path,
            "needs_confirmation": self.needs_confirmation,
            "add_now": self.add_now,
            "ai_mode": self.ai_mode,
            "questions": self.questions,
            "notice": self.notice,
            "quantity": self.quantity,
            "compatibility": self.compatibility,
        }

    def refs(self) -> list[dict]:
        """Every product shown, for the conversation record (audit, like the assistant)."""
        out = []
        for line in self.lines:
            if line.get("product_id"):
                out.append({"product_id": line["product_id"], "variant_id": line.get("variant_id"), "reason": "voice"})
            out.extend(line.get("alternatives") or [])
        return out + self.products


class VoiceShoppingService:
    def __init__(self, *, stt=None, tts=None, assistant=None):
        self.stt = stt or get_stt_provider()
        self.tts = tts or get_tts_provider()
        self._assistant = assistant

    @property
    def assistant(self):
        if self._assistant is None:
            from .assistant import HardwareAssistantService

            self._assistant = HardwareAssistantService()
        return self._assistant

    # --- Status -----------------------------------------------------------------------------------

    def status(self) -> dict:
        """What the voice page needs before listening. Never exposes keys or URLs."""
        return {
            "languages": LANGUAGE_OPTIONS,
            "examples": EXAMPLES,
            "browser_recognition": True,  # the browser listens when it can; the server is the fallback
            "server_recognition": self.stt.describe(),
            "server_voice": self.tts.describe(),
            "max_audio_bytes": settings.VOICE_MAX_AUDIO_BYTES,
            "max_audio_seconds": settings.VOICE_MAX_AUDIO_SECONDS,
            "max_lines": settings.VOICE_MAX_LINES,
            "max_speak_chars": settings.VOICE_MAX_SPEAK_CHARS,
        }

    # --- Speech -----------------------------------------------------------------------------------

    def transcribe(self, upload, *, language: str = "") -> dict:
        data, content_type = read_audio(upload)
        if self.stt.name == "none" or not self.stt.available:
            raise SpeechServiceUnavailable()
        try:
            result = self.stt.transcribe(data, language=language, content_type=content_type)
        except AudioTooLong as exc:
            raise VoiceInputError(str(exc), code="audio_too_long") from exc
        except SpeechUnavailable as exc:
            logger.warning("Server speech recognition unavailable: %s", exc)
            raise SpeechServiceUnavailable() from exc
        except SpeechError as exc:
            logger.info("Recording not understood: %s", exc)
            raise VoiceInputError(
                "We couldn't make out the recording. Try again closer to the microphone, or type it.",
                code="audio_unreadable",
            ) from exc
        return {
            "text": result.text[:MAX_TRANSCRIPT_LENGTH],
            "language": result.language,
            "confidence": result.confidence,
            "duration": result.duration,
            "empty": not result.text,
            "provider": result.provider,
            "model": result.model,
        }

    def speak(self, sentence: str, *, language: str = ""):
        if self.tts.name == "none" or not self.tts.available:
            raise SpeechServiceUnavailable("The server has no voice; your browser reads the answer instead.")
        try:
            return self.tts.synthesize(for_speech(sentence, language or "en"), language=language)
        except SpeechError as exc:
            logger.warning("Server voice unavailable: %s", exc)
            raise SpeechServiceUnavailable("The server voice isn't available right now.") from exc

    # --- Commands ---------------------------------------------------------------------------------

    def command(
        self,
        transcript: str,
        *,
        language: str = "",
        pending: list[dict] | None = None,
        user=None,
        postal_code: str = "",
    ) -> VoiceReply:
        transcript = " ".join((transcript or "").split())[:MAX_TRANSCRIPT_LENGTH]
        language = language if language in LANGUAGES else detect_language(transcript)
        pending = pending or []
        user = user if user is not None and user.is_authenticated else None
        parsed = spoken.parse(transcript, has_pending=bool(pending), max_lines=settings.VOICE_MAX_LINES)
        reply = VoiceReply(transcript=transcript, language=language, intent=parsed.intent)
        handler = {
            Command.ADD: self._add,
            Command.SET_QUANTITY: self._set_quantity,
            Command.CONFIRM: self._confirm,
            Command.CANCEL: self._cancel,
            Command.NAVIGATE: self._navigate,
            Command.SEARCH: self._search,
            Command.ASK: self._ask,
        }.get(parsed.intent, self._unclear)
        if (
            not pending
            and parsed.intent in (Command.ADD, Command.ASK, Command.SEARCH)
            and self._wants_quantity(transcript, parsed)
        ):
            handler = self._quantity
        elif not pending and parsed.intent in (Command.ASK, Command.SEARCH) and self._wants_compatibility(transcript):
            handler = self._compatibility
        handler(reply, parsed, pending=pending, user=user, postal_code=postal_code)
        return reply

    # --- Compatibility (Phase 21) -----------------------------------------------------------------

    @staticmethod
    def _wants_compatibility(transcript: str) -> bool:
        from .compatibility import is_question

        return is_question(transcript)

    def _compatibility(self, reply, parsed, **kwargs):
        """ "Will the masonry bits work with the cordless drill?" through the same CompatibilityService."""
        from .compatibility import CompatibilityAssistant

        answer = CompatibilityAssistant(self.assistant.provider).answer(reply.transcript, language=reply.language)
        if (answer.compatibility or {}).get("needs_products") and not answer.products:
            self._ask(reply, parsed, **kwargs)
            return
        reply.intent = "compatibility"
        reply.reply = answer.message
        reply.products = answer.product_refs()
        reply.compatibility = answer.compatibility

    # --- Quantity AI (Phase 20) -------------------------------------------------------------------

    @staticmethod
    def _wants_quantity(transcript: str, parsed) -> bool:
        """ "500 sq ft plastering ka saman", "how much paint for a 12 by 15 room": the quantity calculator.
        A counted order ("5 packets of screws", "2 coils of wire") stays an order."""
        from ..quantity.service import QuantityAIService
        from ..quantity.units import AREA, DIMENSIONS

        if not QuantityAIService.detect(transcript):
            return False
        normal = spoken.normalize(transcript)
        if AREA.search(normal) or DIMENSIONS.search(normal):
            return True
        counted = any(line.quantity_given and line.unit for line in parsed.lines)
        return not counted and QuantityAIService.is_quantity_request(transcript)

    def _quantity(self, reply, parsed, *, user, postal_code, **kwargs):
        from urllib.parse import quote

        from apps.catalog.models import ProductVariant

        from ..quantity.service import QuantityAIService

        result = QuantityAIService().estimate(
            text=reply.transcript, language=reply.language, user=user, postal_code=postal_code
        )
        if not result.get("calculator"):
            self._ask(reply, parsed, **kwargs)
            return
        reply.intent = "quantity"
        reply.quantity = {
            "calculator": result["calculator"],
            "title": result.get("title") or result["name"],
            "complete": result["complete"],
            "path": f"/quantity?q={quote(reply.transcript)}",
        }
        if not result["complete"]:
            reply.reply = text(reply.language, "quantity_questions", name=result["name"])
            reply.questions = [q["text"] for q in result["questions"] if q["key"] in result["missing"]][:2]
            return
        items = [i for i in result["kit"]["items"] if i["included"] and i["variant"]]
        variants = ProductVariant.objects.in_bulk([i["variant"]["id"] for i in items])
        products = {p.pk: p for p in selectors.product_queryset().filter(pk__in=[i["product_id"] for i in items])}
        lines = []
        for item in items[: settings.VOICE_MAX_LINES]:
            product, variant = products.get(item["product_id"]), variants.get(item["variant"]["id"])
            out = self._line(heard=item["label"], query=item["label"], quantity=item["quantity"])
            if product is None:
                out.update(status="unavailable", message=text(reply.language, "unavailable", name=item["label"]))
                lines.append(out)
                continue
            lines.append(
                self._priced(
                    out,
                    product,
                    variant,
                    item["quantity"],
                    reply.language,
                    user=user,
                    postal_code=postal_code,
                    notes=[],
                )
            )
        reply.lines = lines
        prefix = text(reply.language, "quantity_intro", title=reply.quantity["title"])
        self._propose(reply, prefix)
        if len(items) > settings.VOICE_MAX_LINES or result["kit"]["not_found_count"]:
            reply.reply = f"{reply.reply} {text(reply.language, 'quantity_more')}"

    def _add(self, reply, parsed, *, user, postal_code, **_):
        reply.lines = [self._resolve(line, reply.language, user=user, postal_code=postal_code) for line in parsed.lines]
        self._propose(reply)

    def _propose(self, reply, prefix: str = ""):
        sentences = [prefix] if prefix else []
        sentences += [line["message"] for line in reply.lines if line["message"]]
        ready = [line for line in reply.lines if line["status"] == "ready"]
        if ready:
            reply.needs_confirmation = True
            sentences.append(text(reply.language, "confirm_one" if len(ready) == 1 else "confirm_many"))
        reply.reply = " ".join(sentences)

    def _set_quantity(self, reply, parsed, *, pending, user, postal_code, **_):
        line = parsed.lines[0]
        if len(pending) != 1:
            reply.intent = Command.UNCLEAR
            reply.reply = text(reply.language, "which_item")
            return
        if line.quantity is None:
            reply.reply = text(reply.language, "whole_number")
            return
        item = pending[0]
        reply.lines = [self._requote(item, line.quantity, reply.language, user=user, postal_code=postal_code)]
        self._propose(reply, prefix=text(reply.language, "changed", quantity=line.quantity))

    def _confirm(self, reply, parsed, *, pending, user, postal_code, **_):
        reply.lines = [
            self._requote(item, item["quantity"], reply.language, user=user, postal_code=postal_code)
            for item in pending
        ]
        ready = [line for line in reply.lines if line["status"] == "ready"]
        reply.add_now = bool(ready)
        if not ready:
            key = "confirmed_none"
        else:
            key = "confirmed" if len(ready) == 1 else "confirmed_many"
        problems = [line["message"] for line in reply.lines if line["status"] != "ready"]
        reply.reply = " ".join([text(reply.language, key), *problems])

    def _cancel(self, reply, parsed, **_):
        reply.reply = text(reply.language, "cancelled")

    def _navigate(self, reply, parsed, **_):
        reply.navigate = {"page": parsed.navigate, "path": PAGES[parsed.navigate]}
        reply.reply = text(reply.language, f"navigate_{parsed.navigate}")

    def _search(self, reply, parsed, **_):
        query = parsed.lines[0].query
        rows, _labels, _params, _match = self._find(query, limit=SEARCH_RESULTS)
        reply.products = [
            {"product_id": p.pk, "variant_id": p.cheapest_variant_id, "reason": "voice search"} for p in rows
        ]
        reply.search_path = f"/search?q={query}"
        reply.reply = text(reply.language, "search" if rows else "search_none", query=query)

    def _ask(self, reply, parsed, **_):
        answer = self.assistant.answer(reply.transcript, language_hint=reply.language)
        reply.ai_mode = answer.ai_mode
        reply.reply = answer.message
        reply.questions = list(answer.questions[:2])
        reply.notice = answer.notice
        reply.products = answer.product_refs()

    def _unclear(self, reply, parsed, *, pending, **_):
        if parsed.intent == Command.UNCLEAR and parsed.text and not parsed.lines and not pending:
            # "yes" / "no" with nothing waiting
            reply.reply = text(reply.language, "nothing_pending")
        elif parsed.lines and parsed.lines[0].quantity_given and not parsed.lines[0].query:
            reply.reply = text(reply.language, "how_many_of_what")
        else:
            reply.reply = text(reply.language, "unclear")
        reply.intent = Command.UNCLEAR

    # --- History ----------------------------------------------------------------------------------

    @staticmethod
    def record(user, conversation_id, reply: VoiceReply):
        """Signed-in customers keep a history of their voice commands (the words, never the recording)."""
        from django.db import transaction
        from django.utils import timezone

        from ..models import AIConversation, AIMessage

        if user is None or not user.is_authenticated:
            return None
        conversation = None
        if conversation_id:
            conversation = AIConversation.objects.filter(
                pk=conversation_id, user=user, kind=AIConversation.Kind.VOICE
            ).first()
        with transaction.atomic():
            if conversation is None:
                conversation = AIConversation.objects.create(
                    user=user, kind=AIConversation.Kind.VOICE, language=reply.language, title=reply.transcript[:60]
                )
            AIMessage.objects.create(conversation=conversation, role=AIMessage.Role.USER, content=reply.transcript)
            AIMessage.objects.create(
                conversation=conversation,
                role=AIMessage.Role.ASSISTANT,
                content=reply.reply,
                product_refs=reply.refs(),
                payload=reply.payload(),
                provider="voice",
            )
            AIConversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now(), language=reply.language)
        return conversation

    # --- Products and prices ----------------------------------------------------------------------

    @staticmethod
    def _find(query: str, *, limit: int = 1 + ALTERNATIVES):
        match = find_products(query, limit=limit)
        return match.products, match.labels, match.params, match.quality

    @staticmethod
    def _variant(product, params: dict):
        return choose_variant(product, params)

    def _line(self, heard="", query="", quantity=None) -> dict:
        return {
            "heard": heard,
            "query": query,
            "quantity": quantity,
            "quantity_given": quantity is not None,
            "spoken_unit": "",
            "status": "",
            "match": "",
            "message": "",
            "note": "",
            "product_id": None,
            "variant_id": None,
            "product_name": "",
            "unit": "",
            "alternatives": [],
            "filters": [],
            "quote": None,
        }

    def _resolve(self, spoken_line, language: str, *, user, postal_code: str) -> dict:
        out = self._line(spoken_line.heard, spoken_line.query, spoken_line.quantity)
        out["quantity_given"] = spoken_line.quantity_given
        out["spoken_unit"] = spoken_line.unit
        rows, labels, params, match = self._find(spoken_line.query)
        if match != "exact" and spoken_line.measure and spoken_line.query_without_measure:
            # "20 metre wire": the measure may be how much, not which product
            found = self._find(spoken_line.query_without_measure)
            if found[0] and (found[3] == "exact" or not rows):
                rows, labels, params, match = found
        if not rows:
            out.update(status="not_found", message=text(language, "not_found", query=spoken_line.query))
            return out
        product = rows[0]
        out["alternatives"] = [
            {"product_id": p.pk, "variant_id": p.cheapest_variant_id, "reason": "voice alternative"} for p in rows[1:]
        ]
        out.update(match=match, filters=labels)
        if spoken_line.problem:
            out.update(product_id=product.pk, product_name=product.name, status="whole_number")
            out["message"] = text(language, "whole_number")
            return out

        quantity, notes = spoken_line.quantity, []
        if spoken_line.measure and not spoken_line.quantity_given:
            value, unit = spoken_line.measure
            if product.unit == unit and value == value.to_integral() and 1 <= value <= spoken.MAX_QUANTITY:
                quantity = int(value)  # "20 metre wire" for wire sold by the metre
                out["quantity_given"] = True
        if quantity is None:
            quantity = 1
            notes.append(text(language, "assumed_one"))
        if spoken_line.unit and spoken_line.unit not in (product.unit, "piece") and not spoken_line.dozen:
            unit_word = UNIT_WORDS.get(language, UNIT_WORDS["en"]).get(product.unit, (product.unit,))[0]
            notes.append(
                text(
                    language, "unit_note", unit=unit_word, amount=amount(quantity, product.unit, language).rstrip(" ×")
                )
            )
        out["quantity"] = quantity
        # The variant follows every size word said ("25 kg"), even when the product was found without them.
        said = interpret(spoken_line.query, {})
        sizes = {k: v for k, v in said.filters.items() if k.startswith("opt_")}
        known = {label["param"] for label in out["filters"]}
        out["filters"] += [label for label in said.labels if label["param"] in sizes and label["param"] not in known]
        variant = self._variant(product, {**sizes, **params})
        return self._priced(out, product, variant, quantity, language, user=user, postal_code=postal_code, notes=notes)

    def _requote(self, item: dict, quantity: int, language: str, *, user, postal_code: str) -> dict:
        """A line the customer is confirming or changing, priced again from the database."""
        from apps.catalog.models import ProductVariant

        out = self._line(query="", quantity=quantity)
        product = selectors.product_queryset().filter(pk=item["product_id"]).first()
        variant = (
            ProductVariant.objects.filter(pk=item["variant_id"], product_id=item["product_id"], is_active=True).first()
            if product is not None
            else None
        )
        if product is None or variant is None:
            out.update(
                status="unavailable", message=text(language, "unavailable", name=item.get("name") or "This item")
            )
            out["product_id"], out["variant_id"] = item["product_id"], item["variant_id"]
            return out
        return self._priced(out, product, variant, quantity, language, user=user, postal_code=postal_code, notes=[])

    def _priced(self, out, product, variant, quantity, language, *, user, postal_code, notes) -> dict:
        out.update(product_id=product.pk, product_name=product.name, unit=product.unit, quantity=quantity)
        if variant is None:
            out.update(status="unavailable", message=text(language, "unavailable", name=product.name))
            return out
        out["variant_id"] = variant.pk
        try:
            quote = quote_product(
                product, {"variant": str(variant.pk), "quantity": str(quantity), "postal_code": postal_code}, user=user
            )
        except QuoteError as exc:
            if exc.error_code == "max_quantity_exceeded":
                out.update(
                    status="too_many",
                    message=text(language, "too_many", name=product.name, max=product.max_order_quantity),
                )
            else:
                out.update(status="unavailable", message=text(language, "unavailable", name=product.name))
            return out
        out["quote"] = {
            key: quote[key]
            for key in (
                "quantity",
                "sku",
                "options",
                "mrp",
                "base_unit_price",
                "unit_price",
                "applied_tier",
                "next_tier",
                "line_total",
                "bulk_saving",
                "offer_discount",
                "offers",
                "total",
                "stock_status",
                "within_stock",
                "max_order_quantity",
            )
        }
        if not quote["within_stock"]:
            out.update(
                status="short_stock", message=text(language, "short_stock", name=product.name, quantity=quantity)
            )
            return out
        name = product.name
        tier = quote["applied_tier"]
        sentence = text(
            language,
            "line_bulk" if tier else "line",
            amount=amount(quantity, product.unit, language),
            name=name,
            unit_price=rupees(quote["unit_price"]),
            total=rupees(quote["total"]),
            min=tier["min_quantity"] if tier else "",
        )
        nxt = quote["next_tier"]
        parts = [sentence]
        if Decimal(quote["offer_discount"]) > 0:
            offer = ", ".join(o["name"] for o in quote["offers"]) or "offer"
            parts.append(text(language, "offer", offer=offer, discount=rupees(quote["offer_discount"])))
        if nxt and nxt["reachable"]:
            parts.append(text(language, "next_tier", more=nxt["units_more"], price=rupees(nxt["unit_price"])))
        parts += notes
        out.update(status="ready", message=" ".join(parts), note=" ".join(notes))
        return out
