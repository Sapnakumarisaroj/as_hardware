# ruff: noqa: E501 — word tables in three languages read better on one line
"""What a spoken shopping sentence asks for (Phase 18). Pure functions: no database, no model.

    "add 10 bags of 53 grade cement"         → add · 10 × bag · "53 grade cement"
    "das bori cement aur paanch pipe"         → add · 10 × bag "cement" + 5 × "pipe"
    "दस बोरी सीमेंट कार्ट में डालो"             → add · 10 × bag · "cement"
    "two coils of 1.5 sq mm wire"            → add · 2 × coil · "1.5 sq mm wire"
    "make it 30" / "तीस कर दो"                → change the quantity of the item being confirmed
    "haan" / "yes" / "नहीं"                    → confirm / cancel
    "open my cart" / "checkout"              → open a page (nothing is ever ordered or paid by voice)
    "which drill for concrete?"              → a question for the hardware assistant

Numbers can be digits (recognisers usually write them), English words ("twenty five"), Hindi in
Devanagari (1–100, सौ, हज़ार, डेढ़, ढाई) or the common romanised Hindi words ("das", "bees", "pachaas").
A number followed by a counting word (bags, बोरी, pieces, नग, packets, coils, pairs …) is the quantity;
a number with a size unit (kg, mm, sq mm, inch, grade, watt …) is part of the product's description
and stays in the search words, where the Phase 16 search understanding turns it into a filter. Kilos,
metres and litres are decided later, by how the product is sold (`voice.py`).

Recognisers write English loanwords in Devanagari when listening in Hindi ("सीमेंट", "वायर", "ग्रेड");
TRANSLITERATIONS turns them back into the catalogue's English words. The assistant's vocabulary covers
the Hindi and Hinglish names of tools (हथौड़ा, pechkas, nal …).
"""

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from . import vocabulary as V


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


# --- Numbers ---------------------------------------------------------------------------------------

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

EN_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}  # fmt: skip
EN_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}  # fmt: skip

# Romanised Hindi as people type and recognisers write it. Words that are also ordinary words
# ("saath" = with, "tin", "bara" = big, "sat") are left out on purpose.
HI_ROMAN = {"ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "paach": 5, "chhe": 6, "chhah": 6, "chah": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10, "dus": 10, "gyarah": 11, "gyara": 11, "barah": 12, "baarah": 12, "terah": 13, "chaudah": 14, "chauda": 14, "pandrah": 15, "pandra": 15, "solah": 16, "satrah": 17, "atharah": 18, "athara": 18, "unnis": 19, "bees": 20, "bis": 20, "pachees": 25, "pachis": 25, "pachchis": 25, "tees": 30, "chalis": 40, "chaalis": 40, "pachas": 50, "pachaas": 50, "pachpan": 55, "sattar": 70, "assi": 80, "nabbe": 90}  # fmt: skip

_HI_DEVANAGARI_1_100 = (
    "एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस "
    "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस "
    "छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस "
    "अड़तालीस उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ "
    "तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर "
    "छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी "
    "नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे सौ"
)
HI_DEVANAGARI = {_nfc(word): n for n, word in enumerate(_HI_DEVANAGARI_1_100.split(), start=1)}
HI_DEVANAGARI.update({_nfc(w): n for w, n in {"पांच": 5, "छः": 6, "छे": 6, "छै": 6, "पन्द्रह": 15, "उन्नासी": 79}.items()})

HI_NUMBERS = {**HI_ROMAN, **HI_DEVANAGARI}
AMBIGUOUS_NUMBERS = {"do", "दो"}  # also "give" ("de do", "डाल दो"): a number only before a unit or a product word

SCALES = {"hundred": 100, "thousand": 1000, "sau": 100, "so": 100, _nfc("सौ"): 100, "hazaar": 1000, "hazar": 1000, "hajar": 1000, _nfc("हज़ार"): 1000, _nfc("हजार"): 1000}  # fmt: skip
FRACTIONS = {"dedh": Decimal("1.5"), "dedth": Decimal("1.5"), _nfc("डेढ़"): Decimal("1.5"), _nfc("डेढ"): Decimal("1.5"), "dhai": Decimal("2.5"), "dhaai": Decimal("2.5"), _nfc("ढाई"): Decimal("2.5"), "half": Decimal("0.5"), "aadha": Decimal("0.5"), _nfc("आधा"): Decimal("0.5")}  # fmt: skip
DOZEN = {"dozen", "dozens", "darjan", "darzan", _nfc("दर्जन")}
POINT = {"point", "dot", _nfc("पॉइंट"), _nfc("प्वाइंट"), _nfc("दशमलव")}
ARTICLES = {"a", "an"}
MONEY = {"rs", "rs.", "rupee", "rupees", "rupaye", "rupay", "rupaiye", "inr", _nfc("रुपये"), _nfc("रुपए"), _nfc("रुपया"), _nfc("रूपये")}  # fmt: skip
MAX_QUANTITY = 9999

# --- Units -----------------------------------------------------------------------------------------
# Counting units: the number is how many to buy. Keys match catalog.Product.Unit values.
COUNT_UNITS: dict[str, tuple[str, ...]] = {
    "bag": (
        "bag",
        "bags",
        "bori",
        "boriyan",
        "bora",
        "bore",
        "katta",
        "katte",
        "sack",
        "sacks",
        "बोरी",
        "बोरियाँ",
        "बोरियां",
        "बोरे",
        "बोरा",
        "बैग",
        "बैग्स",
        "कट्टा",
        "कट्टे",
    ),
    "piece": (
        "piece",
        "pieces",
        "pc",
        "pcs",
        "nos",
        "nag",
        "units",
        "unit",
        "pis",
        "नग",
        "पीस",
        "नंबर",
        "sheet",
        "sheets",
        "शीट",
    ),  # boards are sold by the sheet (one piece)
    "box": (
        "box",
        "boxes",
        "dabba",
        "dabbe",
        "dibba",
        "dibbe",
        "carton",
        "cartons",
        "डिब्बा",
        "डिब्बे",
        "डब्बा",
        "डब्बे",
        "बॉक्स",
    ),
    "pack": ("pack", "packs", "packet", "packets", "pkt", "pkts", "पैकेट", "पैक", "पैकेट्स"),
    "coil": ("coil", "coils", "roll", "rolls", "bundle", "bundles", "कॉइल", "क्वाइल", "रोल", "बंडल"),
    "pair": ("pair", "pairs", "jodi", "jode", "jodiyan", "जोड़ी", "जोड़े", "जोड़ा"),
    "set": ("set", "sets", "सेट"),
}
# Measures: the quantity when the product is sold by that measure (wire per metre), else a size.
MEASURE_UNITS: dict[str, tuple[str, ...]] = {
    "kg": ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "किलो", "किलोग्राम", "केजी"),
    "m": ("m", "metre", "metres", "meter", "meters", "mtr", "mtrs", "मीटर"),
    "l": ("l", "litre", "litres", "liter", "liters", "ltr", "ltrs", "लीटर"),
}
# Sizes: always part of the description. Multi-word ones first. Value = the catalogue spelling.
SIZE_UNITS: dict[str, str] = {
    "square mm": "sq mm", "sq mm": "sq mm", "sqmm": "sq mm", "sq. mm": "sq mm", "स्क्वायर एमएम": "sq mm", "स्क्वेयर एमएम": "sq mm", "वर्ग मिमी": "sq mm", "स्क्वायर मिलीमीटर": "sq mm",
    "sq ft": "sq ft", "square feet": "sq ft",
    "mm": "mm", "एमएम": "mm", "मिमी": "mm", "मिलीमीटर": "mm", "millimetre": "mm", "millimeter": "mm",
    "cm": "cm", "सेमी": "cm", "inch": "inch", "inches": "inch", "इंच": "inch",
    "ft": "ft", "feet": "ft", "foot": "ft", "फीट": "ft", "फुट": "ft",
    "grade": "grade", "ग्रेड": "grade",
    "watt": "w", "watts": "w", "w": "w", "वॉट": "w", "वाट": "w",
    "amp": "a", "amps": "a", "ampere": "a", "एम्पियर": "a", "एम्प": "a",
    "volt": "v", "volts": "v", "v": "v", "वोल्ट": "v",
    "ml": "ml", "मिली": "ml", "ग्राम": "g", "gram": "g", "grams": "g", "gm": "g", "g": "g",
    "hp": "hp", "way": "way", "pin": "pin", "पिन": "pin",
}  # fmt: skip

UNIT_OF: dict[str, tuple[str, str]] = {}  # word → (kind, canonical)
for _unit, _words in COUNT_UNITS.items():
    UNIT_OF.update({_nfc(w): ("count", _unit) for w in _words})
for _unit, _words in MEASURE_UNITS.items():
    UNIT_OF.update({_nfc(w): ("measure", _unit) for w in _words})
SIZE_PHRASES = sorted(((_nfc(k), v) for k, v in SIZE_UNITS.items()), key=lambda kv: -len(kv[0].split()))
_SPLIT_UNITS = "|".join(
    sorted({re.escape(w) for w in [*UNIT_OF, *SIZE_UNITS] if w.isascii() and w.isalpha()}, key=len, reverse=True)
)

# --- Words -----------------------------------------------------------------------------------------

# English loanwords as a Hindi recogniser writes them → the catalogue's words.
TRANSLITERATIONS = {
    "सीमेंट": "cement", "सिमेंट": "cement", "ओपीसी": "opc", "पीपीसी": "ppc", "वायर": "wire", "केबल": "wire",
    "पाइप": "pipe", "पाईप": "pipe", "सीपीवीसी": "cpvc", "यूपीवीसी": "upvc", "पीवीसी": "pvc", "एल्बो": "elbow",
    "वाल्व": "valve", "वॉल्व": "valve", "टैप": "tap", "टेप": "tape", "टेफ्लॉन": "ptfe", "सीलेंट": "sealant",
    "सिलिकॉन": "silicone", "कनेक्टर": "connector", "रिंच": "wrench", "स्विच": "switch", "सॉकेट": "socket",
    "एमसीबी": "mcb", "एलईडी": "led", "बल्ब": "bulb", "बैटन": "batten", "ट्यूबलाइट": "led batten", "फैन": "fan",
    "मल्टीमीटर": "multimeter", "टेस्टर": "tester", "ड्रिल": "drill", "बिट": "bit", "हैमर": "hammer",
    "स्क्रूड्राइवर": "screwdriver", "स्क्रू": "screws", "स्क्रु": "screws", "बोल्ट": "bolt", "नट": "nut", "प्लग": "plugs",
    "वॉल": "wall", "टाइल": "tile", "टाइल्स": "tile", "एडहेसिव": "adhesive", "हेलमेट": "helmet", "ग्लव्स": "gloves",
    "मास्क": "mask", "गॉगल्स": "goggles", "शूज": "shoes", "शूज़": "shoes", "हैकसॉ": "hacksaw", "स्पैनर": "spanner",
    "इंसुलेशन": "insulation", "कॉपर": "copper", "ब्रास": "brass", "स्टील": "steel", "मैग्नेटिक": "magnetic",
    "कॉर्डलेस": "cordless", "इम्पैक्ट": "impact", "मेजरिंग": "measuring", "मेज़रिंग": "measuring",
    "प्लाई": "plywood", "प्लाईवुड": "plywood", "एमडीएफ": "mdf", "बोर्ड": "board", "फेविकोल": "fevicol",
    "हिंज": "hinge", "कब्जा": "hinge", "कब्ज़ा": "hinge", "चैनल": "channel", "हैंडल": "handle", "लॉक": "lock",
    "ताला": "lock", "किचन": "kitchen", "बास्केट": "basket", "वार्डरोब": "wardrobe", "अलमारी": "wardrobe",
    "ग्राइंडर": "grinder", "ग्लास": "glass", "डोर": "door", "क्लोजर": "closer",
}  # fmt: skip
# Hindi and Hinglish product words from the assistant's vocabulary that name one thing.
_HINGLISH_PRODUCT_WORDS = {"nal", "paip", "hathoda", "pechkas", "pana", "aari", "pech", "gond", "lakdi", "taar", "pankha", "dastane"}  # fmt: skip


def _translations() -> dict[str, str]:
    table = {_nfc(k): v for k, v in TRANSLITERATIONS.items()}
    for phrase, terms in V.WORDS.items():
        if len(terms) == 1 and (V.DEVANAGARI.search(phrase) or phrase in _HINGLISH_PRODUCT_WORDS):
            table.setdefault(_nfc(phrase), terms[0])
    return table


TRANSLATIONS = _translations()
_TRANSLATION_PHRASES = sorted(TRANSLATIONS, key=lambda p: -len(p.split()))

# Words that carry no product meaning in a shopping command (English, Hinglish, Hindi).
FILLER = {_nfc(w) for w in """
i i'd i'll im i'm me my mine we us our you your please pls plz kindly can could would will shall want wanna need needs
like get give send bring buy order purchase add put place include also and plus then with of the some any to into in
on for from cart basket trolley list item items hey hi hello ok okay now just quickly it them that this those these
more another extra is are be am was do does have has had much many quantity qty total about around approx need
mujhe muje mujhko humein hume hamein hamen mere mera meri liye ke ka ki ko se mein main bhi aur ya wala wali wale
chahiye chaiye chahie chahiyen chaahiye dena de dedo dijiye dijie dalo daalo daal dal daaldo daldo karo kar kardo kariye
karna karen kijiye jodo jod bhejo bhej lao lana lena le lo chahta chahti hoon hu hun hai hain tha ji bhai bhaiya yaar
na zara kart abhi jaldi make change update instead badlo badal
मुझे हमें हमको मुझको मेरे मेरा मेरी लिए के का की को से में मे मैं भी और या वाला वाली वाले चाहिए चाहिये चाहिएं देना दे दीजिए
दीजिये डालो डाल डालें डालिए डाल्दो करो कर करें कीजिए करिए करना जोड़ो जोड़ जोड़ें जोड़िए भेजो भेज लाओ लेना ले लो चाहता चाहती
हूँ हूं है हैं था जी भाई भैया कृपया ज़रा जरा कार्ट कार्ड ऐड एड प्लीज़ प्लीज ओके अभी जल्दी टोटल दो बदलो बदल
""".split()}  # fmt: skip

ADD_WORDS = {_nfc(w) for w in "add put daal daalo dal dalo daaldo daldo jodo cart kart डालो डाल डालें डालिए डाल्दो जोड़ो जोड़ें जोड़िए कार्ट कार्ड ऐड एड".split()}  # fmt: skip
SEARCH_WORDS = {_nfc(w) for w in "show find search look dikhao dikhaiye dikha dikhana dhoondo dhundo dhoondho dhundho dhoondh khojo दिखाओ दिखाइए दिखाएँ दिखाएं दिखा ढूंढो ढूँढो ढूँढें ढूंढें खोजो खोजें".split()}  # fmt: skip
YES_CORE = {_nfc(w) for w in "yes yeah yep yup sure ok okay confirm confirmed correct right haan han haa ha haanji theek thik sahi done bilkul हाँ हां हा हाँजी ठीक सही बिल्कुल बिलकुल".split()}  # fmt: skip
NO_CORE = {_nfc(w) for w in "no nope cancel stop dont don't not nahi nahin nai mat rehne rahne chhodo नहीं नही ना मत रहने छोड़ो कैंसल".split()}  # fmt: skip
CONFIRM_EXTRA = {_nfc(w) for w in "it please ji hai do kar karo kardo de dedo go ahead add cart kart mein to the in daal dal daalo dalo daldo daaldo जी है दो कर करो कर्दो दे डाल डालो डाल्दो कार्ट में ऐड एड".split()}  # fmt: skip
CANCEL_EXTRA = {_nfc(w) for w in "it please ji hai do karo karna chahiye add dena don't need want thanks thank you mat rehne do दो करो करना चाहिए जी है रहने दीजिए धन्यवाद".split()}  # fmt: skip

SPLITTERS = re.compile(
    r"\s*(?:,|\band\b|\baur\b|\bplus\b|\balso\b|&|\+|" + "|".join(_nfc(w) for w in ("और", "तथा", "एवं")) + r")\s*"
)

NAVIGATION: list[tuple[str, re.Pattern]] = [
    (
        "checkout",
        re.compile(
            r"\bcheck ?out\b|\bplace (?:the |my )?order\b|\border place\b|\bpayment\b|\bpay now\b|चेकआउट|चेक आउट|ऑर्डर प्लेस|भुगतान|पेमेंट"
        ),
    ),
    (
        "orders",
        re.compile(
            r"\bmy orders?\b|\border status\b|\btrack\b|\bwhere is my order\b|\bmera order\b|\border kaha|\borders? dikhao|मेरे ऑर्डर|मेरा ऑर्डर|ऑर्डर कहा|ट्रैक"
        ),
    ),
    ("wallet", re.compile(r"\bwallet\b|\bmy credits?\b|\bcashback balance\b|वॉलेट|वालेट")),
    (
        "cart",
        re.compile(
            r"\b(?:open|show|view|see|go to|take me to)\b.*\b(?:cart|basket)\b|\bmy (?:cart|basket)\b|\b(?:mera|meri) cart\b|\bcart\b.*\b(?:dikhao|dikhaiye|kholo|khol|batao|open|show)\b|^(?:cart|basket)$|(?:कार्ट|कार्ड).*(?:दिखाओ|दिखाइए|खोलो|बताओ|दिखाएं)|^कार्ट$|मेरा कार्ट"
        ),
    ),
]


# --- Result ----------------------------------------------------------------------------------------


class Command:
    ADD = "add_to_cart"
    SET_QUANTITY = "set_quantity"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    NAVIGATE = "navigate"
    SEARCH = "search"
    ASK = "ask"
    UNCLEAR = "unclear"


@dataclass
class SpokenLine:
    heard: str  # the part of the sentence this line came from
    query: str = ""  # catalogue search words (English where we know the word), sizes included
    quantity: int | None = None
    quantity_given: bool = False  # False: nobody said a number; 1 is assumed for an explicit "add X"
    unit: str = ""  # counting unit said ("bag", "coil" …); "" when none
    dozen: bool = False
    measure: tuple[Decimal, str] | None = None  # "20 m", "50 kg": a size, or the quantity if sold that way
    query_without_measure: str = ""
    money: bool = False  # a rupee amount was said ("under 500 rupees"): a budget, not a quantity
    problem: str = ""  # "whole_number": "1.5 bags"


@dataclass
class ParsedCommand:
    intent: str
    text: str  # normalised sentence
    lines: list[SpokenLine] = field(default_factory=list)
    navigate: str = ""  # cart | checkout | orders | wallet


# --- Normalising and reading numbers ---------------------------------------------------------------


def normalize(text: str) -> str:
    text = _nfc((text or "").strip().lower()).translate(DEVANAGARI_DIGITS)
    text = text.replace("₹", " rs ").replace("।", " ").replace("॥", " ")
    text = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", text)  # twenty-five
    text = re.sub(r"(\d)(?:\s*)x(?:\s*)(\d)", r"\1 x \2", text)  # 8x25 → 8 x 25 (sizes)
    if _SPLIT_UNITS:
        text = re.sub(rf"(\d)({_SPLIT_UNITS})\b", r"\1 \2", text)  # 50kg → 50 kg, 10bags → 10 bags
    text = re.sub(r"(?<!\d),|,(?!\d)", " , ", text)  # a list separator ("cement, wire"), kept for splitting
    text = re.sub(r"(?<!\d)[.!?;:\"“”‘’()]+|[.!?;:\"“”‘’()]+(?!\d)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _number_word(word: str) -> int | None:
    if word in EN_ONES:
        return EN_ONES[word]
    if word in EN_TENS:
        return EN_TENS[word]
    return None


@dataclass
class _Token:
    text: str
    value: Decimal | None = None  # numbers
    unit_kind: str = ""  # count | measure | size | money | dozen
    unit: str = ""
    span: int = 1  # words this token covers


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _read_number(words: list[str], i: int) -> tuple[Decimal, int] | None:
    """A number starting at words[i] → (value, index after it)."""
    n = len(words)
    word = words[i]
    nxt = words[i + 1] if i + 1 < n else ""

    if re.fullmatch(r"\d+(?:\.\d+)?", word):
        value, j = Decimal(word), i + 1
        if j + 1 < n and words[j] in POINT and words[j + 1].isdigit():
            value, j = Decimal(f"{word}.{words[j + 1]}"), j + 2
        elif j < n and words[j] in SCALES and value == value.to_integral():
            value, j = value * SCALES[words[j]], j + 1
        return value, j

    if word in FRACTIONS:
        if nxt in SCALES:
            return FRACTIONS[word] * SCALES[nxt], i + 2
        if nxt in DOZEN or _unit_at(words, i + 1):
            return FRACTIONS[word], i + 1
        return None

    if word in ARTICLES:
        if nxt in DOZEN or (_unit_at(words, i + 1) or ("", "", 0))[0] == "count":
            return Decimal(1), i + 1
        return None

    if _number_word(word) is not None:
        total, current, j = 0, 0, i
        while j < n:
            w = words[j]
            if (v := _number_word(w)) is not None:
                current += v
            elif w == "hundred":
                current = (current or 1) * 100
            elif w == "thousand":
                total, current = total + (current or 1) * 1000, 0
            elif w == "and" and j + 1 < n and _number_word(words[j + 1]) is not None and (total or current >= 100):
                pass
            else:
                break
            j += 1
        value = Decimal(total + current)
        if j + 1 < n and words[j] in POINT and words[j + 1] in EN_ONES and EN_ONES[words[j + 1]] < 10:
            value, j = Decimal(f"{total + current}.{EN_ONES[words[j + 1]]}"), j + 2
        return value, j

    if word in HI_NUMBERS:
        if word in AMBIGUOUS_NUMBERS:
            # "do bori", "do pipe" → 2; "de do", "dal do", "pipe do na" → the verb "give".
            prev = words[i - 1] if i else ""
            if not nxt or nxt in FILLER or prev in {"de", "दे", "kar", "कर", "dal", "daal", "डाल", "rehne", "रहने"}:
                if not (nxt in SCALES or nxt in DOZEN or _unit_at(words, i + 1)):
                    return None
        value, j = Decimal(HI_NUMBERS[word]), i + 1
        if j < n and words[j] in SCALES:
            value, j = value * SCALES[words[j]], j + 1
            if j < n and words[j] in HI_NUMBERS and HI_NUMBERS[words[j]] < 100 and words[j] not in AMBIGUOUS_NUMBERS:
                value, j = value + HI_NUMBERS[words[j]], j + 1
        return value, j
    return None


def _unit_at(words: list[str], i: int) -> tuple[str, str, int] | None:
    """(kind, canonical unit, words used) for a unit starting at words[i]."""
    if i >= len(words):
        return None
    for phrase, canonical in SIZE_PHRASES:
        parts = phrase.split()
        if words[i : i + len(parts)] == parts:
            return "size", canonical, len(parts)
    if words[i] in UNIT_OF:
        kind, unit = UNIT_OF[words[i]]
        return kind, unit, 1
    if words[i] in MONEY:
        return "money", "rs", 1
    return None


def _tokens(words: list[str]) -> list[_Token]:
    out: list[_Token] = []
    i = 0
    while i < len(words):
        read = _read_number(words, i)
        if read is None:
            unit = _unit_at(words, i)
            if unit is not None and unit[0] == "size":
                out.append(
                    _Token(
                        SIZE_UNITS.get(" ".join(words[i : i + unit[2]]), unit[1]), unit_kind="size_word", span=unit[2]
                    )
                )
                i += unit[2]
                continue
            out.append(_Token(words[i]))
            i += 1
            continue
        value, j = read
        token = _Token(_format(value), value=value)
        if j < len(words) and words[j] in DOZEN:
            token.value, token.unit_kind, token.unit = value * 12, "dozen", "piece"
            token.text = _format(token.value)
            j += 1
        elif (unit := _unit_at(words, j)) is not None:
            token.unit_kind, token.unit = unit[0], unit[1]
            j += unit[2]
        out.append(token)
        i = j
    return out


def _format(value: Decimal) -> str:
    return str(int(value)) if value == value.to_integral() else format(value.normalize(), "f")


# --- Lines -----------------------------------------------------------------------------------------


def _translate(words: list[str]) -> list[str]:
    text = " " + " ".join(words) + " "
    for phrase in _TRANSLATION_PHRASES:
        if f" {phrase} " in text:
            text = text.replace(f" {phrase} ", f" {TRANSLATIONS[phrase]} ")
    return text.split()


def parse_line(segment: str) -> SpokenLine:
    words = segment.split()
    tokens = _tokens(words)
    line = SpokenLine(heard=segment)
    quantity_at = None
    line.money = any(token.unit_kind == "money" for token in tokens)
    if not line.money:
        # 1st choice: a number with a counting word; 2nd: a bare whole number that isn't part of a size.
        for k, token in enumerate(tokens):
            if token.unit_kind in ("count", "dozen"):
                quantity_at = k
                break
        if quantity_at is None:
            for k, token in enumerate(tokens):
                if token.value is None or token.unit_kind:
                    continue
                before = tokens[k - 1].text if k else ""
                after = tokens[k + 1] if k + 1 < len(tokens) else None
                if before in {"x", "m", "no", "grade", "size", "model"} or (
                    after is not None and (after.text == "x" or after.unit_kind == "size_word")
                ):
                    continue  # "M 8", "8 x 25", "grade 53", "53 grade": sizes, not quantities
                quantity_at = k
                break
    query_words: list[str] = []
    measure_words: list[str] = []
    for k, token in enumerate(tokens):
        if k == quantity_at:
            value = token.value
            if value != value.to_integral() or value < 1 or value > MAX_QUANTITY:
                line.problem = "whole_number" if value != value.to_integral() else "out_of_range"
            else:
                line.quantity, line.quantity_given = int(value), True
            line.unit = token.unit if token.unit_kind in ("count", "dozen") else ""
            line.dozen = token.unit_kind == "dozen"
            continue
        if token.value is not None:
            unit_text = {"measure": token.unit, "size": token.unit, "count": token.unit, "money": "rs"}.get(
                token.unit_kind, ""
            )
            if token.unit_kind == "measure" and line.measure is None:
                line.measure = (token.value, token.unit)
                measure_words.append(f"{token.text} {unit_text}".strip())
                continue
            if token.unit_kind == "money":
                continue
            query_words.append(f"{token.text} {unit_text}".strip())
            continue
        if (
            token.text == ","
            or token.text in FILLER
            or token.text in ADD_WORDS
            or token.text in SEARCH_WORDS
            or token.text in MONEY
        ):
            continue
        query_words.append(token.text)
    translated = _translate(query_words)
    line.query_without_measure = " ".join(translated)
    line.query = " ".join([*measure_words, *translated]) if measure_words else line.query_without_measure
    return line


def _words(text: str) -> set[str]:
    return set(text.split())


def _is_yes(words: list[str]) -> bool:
    return (
        bool(words)
        and len(words) <= 5
        and all(w in YES_CORE | CONFIRM_EXTRA | ADD_WORDS for w in words)
        and any(w in YES_CORE or w in ADD_WORDS for w in words)
    )


def _is_no(words: list[str]) -> bool:
    return (
        bool(words)
        and len(words) <= 6
        and all(w in NO_CORE | CANCEL_EXTRA | FILLER for w in words)
        and any(w in NO_CORE for w in words)
    )


def parse(transcript: str, *, has_pending: bool = False, max_lines: int = 5) -> ParsedCommand:
    text = normalize(transcript)
    words = [w for w in text.split() if w != ","]
    if not words:
        return ParsedCommand(Command.UNCLEAR, text)
    if _is_yes(words):
        return ParsedCommand(Command.CONFIRM if has_pending else Command.UNCLEAR, text)
    if _is_no(words):
        return ParsedCommand(Command.CANCEL if has_pending else Command.UNCLEAR, text)

    whole = parse_line(text)
    lines = [whole]
    segments = [s for s in SPLITTERS.split(text) if s.strip()]
    if len(segments) > 1:
        parts = [parse_line(s) for s in segments]
        # Several items only when every part names its own quantity and product ("10 bags cement and
        # 5 pipes"); "nut and bolt, 5 packets" stays one item.
        if all(p.quantity_given and p.query for p in parts):
            lines = parts[:max_lines]
    said = _words(text)

    navigate = ""
    if not whole.quantity_given:
        navigate = next((name for name, pattern in NAVIGATION if pattern.search(text)), "")
    if navigate:
        return ParsedCommand(Command.NAVIGATE, text, navigate=navigate)
    if whole.money:
        return ParsedCommand(Command.ASK, text, lines=[whole])
    if any(line.quantity_given for line in lines) or whole.problem:
        if all(line.query for line in lines) and not whole.problem:
            return ParsedCommand(Command.ADD, text, lines=lines)
        if not whole.query:
            return ParsedCommand(Command.SET_QUANTITY if has_pending else Command.UNCLEAR, text, lines=[whole])
        return ParsedCommand(Command.ADD, text, lines=[whole])
    if whole.query and said & ADD_WORDS:  # "add a hammer": 1 is assumed (and said) when pricing
        return ParsedCommand(Command.ADD, text, lines=[whole])
    if whole.measure and whole.query_without_measure and not _is_question(text):
        # "20 metre wire", "50 kg cement": how the product is sold decides (voice.py) whether that is the
        # quantity (wire by the metre) or the pack size (one 50 kg bag).
        return ParsedCommand(Command.ADD, text, lines=[whole])
    if whole.query and said & SEARCH_WORDS and not _is_question(text):
        return ParsedCommand(Command.SEARCH, text, lines=[whole])
    if whole.query or len(words) > 1:
        return ParsedCommand(Command.ASK, text, lines=[whole])
    return ParsedCommand(Command.UNCLEAR, text, lines=[whole])


QUESTION = re.compile(
    r"^(?:what|which|why|how|when|where|kya|kaun|kaunsa|kaise|kitna|kitne|क्या|कौन|कैसे|कितना|कितने)\b|\b(?:best|better|suitable|recommend|sahi|accha|achha|बढ़िया|अच्छा)\b"
)


def _is_question(text: str) -> bool:
    return bool(QUESTION.search(text))
