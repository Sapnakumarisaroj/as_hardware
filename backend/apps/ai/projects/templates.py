# ruff: noqa: E501 — sentences in three languages read better on one line
"""Project templates (Phase 19): what each kind of job needs to know, and what it needs to buy.

A template has:
- detection patterns (English, Hindi, Hinglish) for the customer's description,
- the questions it may ask — each asked only when its answer changes the materials and the
  description didn't already give it; questions with a sensible default are not asked at all
  (the default is shown as an assumption),
- `materials(answers)`: needs in natural units (litres of paint, screws, metres of pipe, bags of
  cement) from simple, labelled rules of thumb. These are estimates for a shopping list, not an
  engineering calculation; the plan says so.

A need names catalogue *search words*, never a product: products, variants, prices, offers, stock
and delivery are all decided later from the database (`kit.py`).

Every amount is worked out by `apps.ai.quantity.formulas` (Phase 20), the one set of formulas shared with the
quantity calculators and the assistant; a template only decides which formulas a job needs.

Adding a project type = adding a ProjectTemplate here (and its key to `Project.Type`).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from apps.catalog.compatibility.rules import CHANNEL_REAR_CLEARANCE_MM

from ..quantity import formulas as F
from ..quantity import units as U
from ..quantity.text import say, t

__all__ = ["ALL_TEMPLATES", "CALCULATORS", "Choice", "Need", "ProjectTemplate", "Question", "TEMPLATES", "say", "t"]

# The templates keep each three-language sentence on one line.
# fmt: off


@dataclass(frozen=True)
class Choice:
    value: str
    label: dict[str, str]
    patterns: tuple[str, ...] = ()  # found in the description → this answer


@dataclass(frozen=True)
class Question:
    key: str
    kind: str  # number | choice
    text: dict[str, str]
    choices: tuple[Choice, ...] = ()
    unit: str = ""
    minimum: float = 1
    maximum: float = 10_000
    default: object = None  # with a default the question is never asked; the default is an assumption
    when: Callable[[dict], bool] | None = None  # asked only when this is true for the answers so far
    count_words: tuple[str, ...] = ()  # "4 holes", "६ छेद": a number followed by one of these words
    role: str = ""  # length | width | height | area | metres: read from "12x15", "120 sq ft", "10 m"

    def applies(self, answers: dict) -> bool:
        return self.when is None or bool(self.when(answers))

    @property
    def units(self) -> list[str]:
        """Units the customer may answer in ("ft" → ft, m, cm, mm, inch); converted to `unit`."""
        return U.units_for(self.unit) if self.kind == "number" else []

    def convert(self, value) -> tuple[float | None, str]:
        """{"value": 5, "unit": "m"} or a plain number → (number in `unit`, interpretation or "")."""
        unit = ""
        if isinstance(value, dict):
            value, unit = value.get("value"), str(value.get("unit") or "")
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None, ""
        if not math.isfinite(number):
            return None, ""
        if unit and self.units and U.canonical(unit) != U.canonical(self.unit):
            converted = U.convert(number, unit, self.unit)  # UnitError for a unit of another kind
            return converted, f"{U.fmt(number, 2)} {U.canonical(unit)} = {U.fmt(converted, 2)} {self.unit}"
        return number, ""

    def clean(self, value):
        """A valid answer or None."""
        if value is None or value == "":
            return None
        if self.kind == "choice":
            value = str(value).strip().lower()
            return value if value in {c.value for c in self.choices} else None
        try:
            number, _ = self.convert(value)
        except U.UnitError:
            return None
        if number is None or not (self.minimum <= number <= self.maximum):
            return None
        return int(number) if number == int(number) else round(number, 2)

    def describe(self, language: str) -> dict:
        return {
            "key": self.key,
            "kind": self.kind,
            "text": say(self.text, language),
            "unit": self.unit,
            "min": self.minimum,
            "max": self.maximum,
            "choices": [{"value": c.value, "label": say(c.label, language)} for c in self.choices],
            "default": self.default,
            "units": self.units,
        }


@dataclass(frozen=True)
class Need:
    key: str  # stable within the template: edits and regeneration follow it
    label: dict[str, str]
    search: tuple[str, ...]  # catalogue words, tried in order
    amount: float  # how much is needed, in `unit`
    unit: str  # l | kg | m | pcs | sqft | cft
    reason: dict[str, str]
    optional: bool = False  # listed, not in the kit until the customer ticks it
    estimate: bool = True  # from a rule of thumb (labelled), not a simple count the customer gave
    hint: str = ""  # preferred variant words ("1/2", "1.5 sq mm")
    note: dict[str, str] = field(default_factory=dict)  # how the amount was worked out
    steps: tuple = ()  # the breakdown: ((label in three languages, value), …) from the formulas
    avoid: tuple[str, ...] = ()  # words that rule a product out ("tiles" must not match "tile adhesive")
    # the customer's sizes the product must fit, for the compatibility engine: (("board_mm", 18), ("depth_mm", 500))
    fit: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class ProjectTemplate:
    key: str
    name: dict[str, str]
    patterns: tuple[str, ...]
    summary: dict[str, str]
    questions: tuple[Question, ...]
    materials: Callable[[dict], list[Need]]
    safety: tuple[str, ...] = ()  # keys into vocabulary.SAFETY_TEXT
    caution: dict[str, str] = field(default_factory=dict)  # a job-specific caution
    professional: Callable[[dict], bool] | None = None  # answers → recommend a qualified professional
    not_sold: dict[str, str] = field(default_factory=dict)  # also needed, not sold by the shop
    title: Callable[[dict, str], str] | None = None
    infer: Callable[[dict, str], None] | None = None  # (answers, description) → fills answers implied by the words
    risky: bool = False  # building/technical work: "verify measurements with a qualified professional"
    examples: tuple[str, ...] = ()  # sample requirements for the calculator page


def _infer_shelves(answers: dict, text: str) -> None:
    """A shelf without a hole count ("install a shelf"): 4 holes per shelf (two brackets), shown as an assumption."""
    import re

    if not answers.get("holes") and re.search(r"shel(f|ves)|शेल्फ|rack", text, re.IGNORECASE):
        answers.setdefault("shelves", 1)


# --- Shared questions and choices --------------------------------------------------------------------

YES = Choice("yes", t("Yes", "हाँ", "Haan"))
NO = Choice("no", t("No", "नहीं", "Nahi"))


def _length(text: dict | None = None, when=None) -> Question:
    return Question(
        "length", "number", text or t("How long is the room (in feet)?", "कमरा कितना लंबा है (फ़ुट में)?", "Room kitni lambi hai (feet mein)?"),
        unit="ft", maximum=200, role="length", when=when,
    )  # fmt: skip


def _width(text: dict | None = None, when=None) -> Question:
    return Question(
        "width", "number", text or t("How wide is the room (in feet)?", "कमरा कितना चौड़ा है (फ़ुट में)?", "Room kitni chaudi hai (feet mein)?"),
        unit="ft", maximum=200, role="width", when=when,
    )  # fmt: skip


def _area(text: dict) -> Question:
    return Question("area", "number", text, unit="sq ft", maximum=50_000, role="area")


WALL_TYPE = Question(
    "wall_type",
    "choice",
    t("What is the wall made of?", "दीवार किस चीज़ की है?", "Deewar kis cheez ki hai?"),
    choices=(
        Choice("concrete", t("Concrete", "कंक्रीट", "Concrete"), (r"concrete", r"rcc", r"कंक्रीट", r"cement\s+(wall|ki\s+deewar)")),
        Choice("brick", t("Brick", "ईंट", "Eent / brick"), (r"brick", r"\beent\b", r"\bint\b", r"ईंट")),
        Choice("wood", t("Wood / plywood", "लकड़ी / प्लाई", "Lakdi / ply"), (r"\bwood", r"plywood", r"\bply\b", r"lakdi", r"लकड़ी")),
        Choice("drywall", t("Gypsum / drywall", "जिप्सम / ड्राईवॉल", "Gypsum / drywall"), (r"gypsum", r"drywall", r"plasterboard", r"जिप्सम")),
    ),
)

HAVE_DRILL = Question(
    "have_drill",
    "choice",
    t("Do you already have a drill machine?", "क्या आपके पास ड्रिल मशीन है?", "Kya aapke paas drill machine hai?"),
    choices=(
        Choice("yes", YES.label, (r"(?<!n't )(?<!not )(?<!no )(have|got|own)\s+(a\s+)?drill", r"drill\s+(hai|है)", r"मेरे\s+पास\s+ड्रिल")),
        Choice("no", NO.label, (r"(no|don'?t\s+have\s+(a\s+)?)\s*drill", r"drill\s+nahi", r"ड्रिल\s+नहीं")),
    ),
)


# --- Painting ----------------------------------------------------------------------------------------


def _painting(a: dict) -> list[Need]:
    walls = F.wall_area(a["length"], a["width"], a.get("height", F.WALL_HEIGHT_FT), int(a.get("doors", 1)), int(a.get("windows", 1)))
    area = walls.amount
    surface, condition = a["surface"], a["condition"]
    paint = F.paint_litres(area, surface)
    primer = F.primer_litres(area)
    coverage = F.EMULSION_SQFT_PER_L_PER_COAT[surface]
    area_text = round(area)
    needs = [
        Need(
            "emulsion", t(f"{surface.title()} emulsion paint", "इमल्शन पेंट (दीवार का रंग)", f"{surface.title()} emulsion paint"),
            (f"{surface} emulsion paint", f"{surface} emulsion", "emulsion paint", "paint"),
            paint.amount, "l",
            t(f"About {area_text} sq ft of wall, {F.COATS} coats at about {coverage} sq ft per litre per coat.",
              f"लगभग {area_text} वर्ग फ़ुट दीवार, {F.COATS} कोट, लगभग {coverage} वर्ग फ़ुट प्रति लीटर प्रति कोट।",
              f"Lagbhag {area_text} sq ft deewar, {F.COATS} coat, lagbhag {coverage} sq ft per litre per coat."),
            steps=tuple(walls.steps + paint.steps),
        ),
        Need(
            "primer", t("Wall primer", "वॉल प्राइमर"), ("wall primer", "primer"), primer.amount, "l",
            t("One coat of primer seals the wall so the paint sticks evenly.", "प्राइमर का एक कोट दीवार को सील करता है ताकि रंग बराबर चढ़े।",
              "Primer ka ek coat deewar seal karta hai taaki paint barabar chadhe."),
            steps=tuple(walls.steps[-1:] + primer.steps),
        ),
    ]
    if condition in F.PUTTY_SQFT_PER_KG:
        putty = F.putty_kg(area, condition)
        needs.append(
            Need(
                "putty", t("Wall putty", "वॉल पुट्टी"), ("wall putty", "putty"), putty.amount, "kg",
                t("Recommended because you said the walls have cracks.", "आपने दीवारों में दरारें बताईं, इसलिए सुझाया गया।",
                  "Aapne deewar mein daraarein batayi, isliye suggest kiya.")
                if condition == "minor" else
                t("Recommended because you said the walls are damaged: two coats of putty.", "आपने दीवारें खराब बताईं, इसलिए पुट्टी के दो कोट।",
                  "Aapne deewar kharab batayi, isliye putty ke do coat."),
                steps=tuple(walls.steps[-1:] + putty.steps),
            )
        )
    needs += [
        Need("sandpaper", t("Sandpaper", "रेगमाल (सैंडपेपर)"), ("sandpaper",), 10 if condition != "good" else 5, "pcs",
             t("Smooths putty and old paint before priming.", "प्राइमर से पहले पुट्टी और पुराना रंग चिकना करने के लिए।", "Primer se pehle putty aur purana paint smooth karne ke liye."),
             optional=condition == "good", estimate=False),
        Need("roller", t("Paint roller", "पेंट रोलर"), ("paint roller", "roller"), 1, "pcs",
             t("A roller is fastest for walls.", "दीवारों के लिए रोलर सबसे तेज़ है।", "Deewar ke liye roller sabse tez hai."), estimate=False),
        Need("brush", t("Paint brushes", "पेंट ब्रश"), ("paint brush", "brush"), 2, "pcs",
             t("Brushes for edges and corners.", "किनारों और कोनों के लिए ब्रश।", "Kinaron aur konon ke liye brush."), estimate=False),
        Need("masking_tape", t("Masking tape", "मास्किंग टेप"), ("masking tape",),
             2 * (a["length"] + a["width"]) * 0.3048 * 2, "m",
             t("Along the ceiling line and skirting, so the edges stay clean.", "छत की लाइन और नीचे की पट्टी पर, ताकि किनारे साफ़ रहें।",
               "Chhat ki line aur skirting par, taaki kinare saaf rahein.")),
    ]
    return needs


PAINTING = ProjectTemplate(
    key="painting",
    name=t("Painting", "पुताई / पेंटिंग", "Painting"),
    patterns=(r"\bpaint", r"\brang\b", r"रंग", r"पेंट", r"पुताई", r"\bputai\b", r"emulsion", r"whitewash", r"safedi", r"सफ़ेदी"),
    summary=t(
        "Walls are prepared (putty where needed, sanding), primed once and painted with two coats of emulsion.",
        "दीवारें तैयार की जाती हैं (ज़रूरत हो तो पुट्टी, घिसाई), एक कोट प्राइमर और फिर इमल्शन के दो कोट।",
        "Deewarein taiyaar hoti hain (zaroorat ho to putty, ghisai), ek coat primer aur phir emulsion ke do coat.",
    ),
    questions=(
        _length(),
        _width(),
        Question("height", "number", t("Wall height (feet)", "दीवार की ऊँचाई (फ़ुट)", "Deewar ki unchai (feet)"), unit="ft", maximum=40, default=F.WALL_HEIGHT_FT, role="height"),
        Question("doors", "number", t("How many doors?", "कितने दरवाज़े?", "Kitne darwaze?"), unit="doors", minimum=0, maximum=20, default=1,
                 count_words=("doors", "door", "darwaze", "darwaza", "दरवाज़े", "दरवाजे", "दरवाज़ा")),
        Question("windows", "number", t("How many windows?", "कितनी खिड़कियाँ?", "Kitni khidkiyan?"), unit="windows", minimum=0, maximum=40, default=1,
                 count_words=("windows", "window", "khidki", "khidkiyan", "खिड़की", "खिड़कियाँ")),
        Question(
            "surface", "choice", t("Inside walls or outside walls?", "अंदर की दीवारें या बाहर की?", "Andar ki deewarein ya bahar ki?"),
            choices=(
                Choice("interior", t("Inside (interior)", "अंदर (इंटीरियर)", "Andar (interior)"),
                       (r"\broom\b", r"bedroom", r"hall\b", r"kitchen", r"interior", r"inside", r"kamr[ae]", r"कमर[ाे]", r"अंदर", r"andar")),
                Choice("exterior", t("Outside (exterior)", "बाहर (एक्सटीरियर)", "Bahar (exterior)"),
                       (r"exterior", r"outside", r"outer\s+wall", r"boundary", r"compound", r"bahar", r"बाहर")),
            ),
        ),
        Question(
            "condition", "choice", t("What condition are the walls in?", "दीवारें किस हालत में हैं?", "Deewarein kis haalat mein hain?"),
            choices=(
                Choice("good", t("Good, just repainting", "अच्छी, बस दोबारा रंगना है", "Achhi, bas dobara paint karna hai"), (r"good\s+condition", r"just\s+repaint", r"fresh\s+wall")),
                Choice("minor", t("A few cracks or holes", "कुछ दरारें या छेद", "Kuch daraarein ya chhed"), (r"crack", r"daraar", r"दरार", r"small\s+holes")),
                Choice("damaged", t("Peeling or damaged", "पपड़ी उखड़ी या खराब", "Paint utra hua ya kharab"), (r"peel", r"damage", r"damp", r"kharab", r"खराब", r"उखड़")),
            ),
        ),
    ),  # fmt: skip
    materials=_painting,
    safety=(),
    caution=t(
        "Keep the room ventilated, cover floors and furniture, and use a stable ladder for high parts.",
        "कमरे में हवा आने दें, फ़र्श और फ़र्नीचर ढकें, और ऊँचाई के लिए मज़बूत सीढ़ी का उपयोग करें।",
        "Kamre mein hawa aane dein, farsh aur furniture dhakein, aur unchai ke liye mazboot ladder use karein.",
    ),
    title=lambda a, lang: say(t("Painting · {l} × {w} ft room", "पुताई · {l} × {w} फ़ुट कमरा", "Painting · {l} × {w} ft room"), lang, l=_n(a.get("length")), w=_n(a.get("width"))),
)


# --- Wall drilling (shelves, TV mounts, frames) ------------------------------------------------------


def _holes(a: dict) -> int:
    return int(a.get("holes") or 4 * int(a.get("shelves") or 1))


def _drilling(a: dict) -> list[Need]:
    wall, holes = a["wall_type"], _holes(a)
    counted = F.fasteners(holes)
    spare = int(counted.amount)
    because = {
        "concrete": t("Recommended because you selected a concrete wall.", "आपने कंक्रीट की दीवार चुनी, इसलिए सुझाया गया।", "Aapne concrete deewar chuni, isliye suggest kiya."),
        "brick": t("Recommended because you selected a brick wall.", "आपने ईंट की दीवार चुनी, इसलिए सुझाया गया।", "Aapne brick deewar chuni, isliye suggest kiya."),
        "wood": t("Recommended because you selected a wooden surface.", "आपने लकड़ी चुनी, इसलिए सुझाया गया।", "Aapne lakdi chuni, isliye suggest kiya."),
        "drywall": t("Recommended because you selected a gypsum / drywall surface.", "आपने जिप्सम दीवार चुनी, इसलिए सुझाया गया।", "Aapne gypsum deewar chuni, isliye suggest kiya."),
    }[wall]
    count_note = t(f"{holes} holes plus a few spares.", f"{holes} छेद और कुछ अतिरिक्त।", f"{holes} chhed aur kuch extra.")
    needs = []
    if wall != "wood":
        needs.append(Need("wall_plugs", t("Wall plugs", "वॉल प्लग"), ("wall plugs", "wall plug"), spare, "pcs", because, note=count_note, steps=tuple(counted.steps)))
    needs.append(Need("screws", t("Screws", "स्क्रू"), ("wood screws", "screws"), spare, "pcs",
                      t("One screw per hole.", "हर छेद में एक स्क्रू।", "Har chhed mein ek screw."), note=count_note, steps=tuple(counted.steps)))
    masonry = wall in ("concrete", "brick")
    needs.append(
        Need("drill_bit", t("Masonry drill bits" if masonry else "Drill bits", "ड्रिल बिट"),
             ("masonry drill bit", "drill bit") if masonry else ("hss drill bit", "drill bit"), 1, "pcs", because, estimate=False)
    )  # fmt: skip
    if a.get("have_drill") == "no":
        needs.append(
            Need("drill", t("Impact drill" if masonry else "Drill driver", "ड्रिल मशीन"),
                 ("impact drill",) if masonry else ("cordless drill driver", "drill driver", "drill"), 1, "pcs",
                 t("You said you don't have a drill; concrete and brick need an impact (hammer) drill." if masonry else "You said you don't have a drill.",
                   "आपने बताया कि ड्रिल नहीं है; कंक्रीट और ईंट के लिए इम्पैक्ट ड्रिल चाहिए।" if masonry else "आपने बताया कि ड्रिल नहीं है।",
                   "Aapne bataya drill nahi hai; concrete aur brick ke liye impact drill chahiye." if masonry else "Aapne bataya drill nahi hai."),
                 estimate=False)
        )  # fmt: skip
    needs += [
        Need("goggles", t("Safety goggles", "सुरक्षा चश्मा"), ("safety goggles", "goggles"), 1, "pcs",
             t("Drilling throws dust towards your eyes.", "ड्रिल करते समय धूल आँखों की ओर आती है।", "Drill karte waqt dhool aankhon ki taraf aati hai."), optional=True, estimate=False),
        Need("measuring_tape", t("Measuring tape", "मापने का टेप"), ("measuring tape",), 1, "pcs",
             t("To mark the holes level.", "छेद सीध में लगाने के लिए।", "Chhed seedh mein lagane ke liye."), optional=True, estimate=False),
    ]  # fmt: skip
    return needs


WALL_DRILLING = ProjectTemplate(
    key="wall_drilling",
    name=t("Wall drilling / mounting", "दीवार में ड्रिल / फ़िटिंग", "Wall drilling / mounting"),
    patterns=(r"\bdrill", r"\bholes?\b", r"chhed", r"छेद", r"shel(f|ves)", r"शेल्फ", r"\brack\b", r"\bmount", r"\bhang", r"tv\s+(stand|bracket|mount)",
              r"curtain\s+rod", r"पर्दा", r"photo\s+frame", r"clock"),
    summary=t(
        "Holes are drilled with the right bit for the wall, wall plugs go in, and screws hold the item.",
        "दीवार के हिसाब से सही बिट से छेद, उनमें वॉल प्लग और फिर स्क्रू से सामान टिकाया जाता है।",
        "Deewar ke hisaab se sahi bit se chhed, unmein wall plug aur phir screw se saamaan tikaya jata hai.",
    ),
    questions=(
        WALL_TYPE,
        Question("holes", "number", t("How many holes do you need?", "कितने छेद चाहिए?", "Kitne chhed chahiye?"), unit="holes", maximum=500,
                 count_words=("holes", "hole", "chhed", "छेद"), when=lambda a: not a.get("shelves")),
        Question("shelves", "number", t("How many shelves?", "कितनी शेल्फ?", "Kitni shelf?"), unit="shelves", maximum=50,
                 count_words=("shelves", "shelf", "शेल्फ"), default=None, when=lambda a: False),
        HAVE_DRILL,
    ),  # fmt: skip
    materials=_drilling,
    infer=_infer_shelves,
    safety=("structural",),
    caution=t(
        "Check for hidden electrical wires and water pipes before drilling (they usually run straight up and down from switches and taps).",
        "ड्रिल करने से पहले छिपे बिजली के तार और पानी के पाइप देख लें (ये आमतौर पर स्विच और नल से सीधे ऊपर-नीचे जाते हैं)।",
        "Drill karne se pehle chhupe bijli ke taar aur paani ke pipe check karein (ye aksar switch aur nal se seedhe upar-neeche jaate hain).",
    ),
)


# --- Bathroom repair ---------------------------------------------------------------------------------


def _bathroom(a: dict) -> list[Need]:
    problem = a["problem"]
    needs = [
        Need("ptfe_tape", t("PTFE thread seal tape", "PTFE टेप"), ("ptfe tape",), 1, "pcs",
             t("Seals threaded joints so they don't drip.", "चूड़ीदार जोड़ों को सील करता है ताकि पानी न टपके।", "Threaded joints seal karta hai taaki paani na tapke."), estimate=False),
    ]  # fmt: skip
    if problem == "replace_tap":
        taps = int(a.get("taps") or 1)
        needs += [
            Need("tap", t("Tap", "नल"), ("pillar tap", "tap"), taps, "pcs", t("The new tap(s) you asked for.", "आपके बताए नए नल।", "Aapke bataye naye nal."), estimate=False),
            Need("connector", t("Braided connector", "कनेक्टर पाइप"), ("braided connector", "connector"), taps, "pcs",
                 t("A fresh connector per tap avoids old, leaking hoses.", "हर नल के लिए नया कनेक्टर, ताकि पुराना रिसता पाइप न रहे।", "Har nal ke liye naya connector."), estimate=False),
        ]  # fmt: skip
    if problem in ("tap_leak", "replace_tap", "joint_leak"):
        needs.append(Need("wrench", t("Pipe wrench", "पाइप रिंच"), ("pipe wrench", "wrench", "spanner"), 1, "pcs",
                          t("To open and tighten the fittings.", "फ़िटिंग खोलने और कसने के लिए।", "Fitting kholne aur kasne ke liye."), optional=True, estimate=False))  # fmt: skip
    if problem in ("joint_leak", "sealing"):
        metres = float(a.get("gap_length") or 3)
        needs.append(
            Need("sealant", t("Silicone sealant", "सिलिकॉन सीलेंट"), ("silicone sealant", "sealant"), max(1, math.ceil(metres / 8)), "pcs",
                 t("For gaps around the basin, tiles and joints.", "बेसिन, टाइल और जोड़ों की दरारों के लिए।", "Basin, tiles aur joints ke gaps ke liye."),
                 note=t(f"About 8 m of bead per 280 ml tube; {_n(metres)} m of gaps.", f"280 ml ट्यूब से लगभग 8 मीटर; {_n(metres)} मीटर दरारें।",
                        f"280 ml tube se lagbhag 8 m; {_n(metres)} m gaps."))
        )  # fmt: skip
    return needs


BATHROOM = ProjectTemplate(
    key="bathroom_repair",
    name=t("Bathroom repair", "बाथरूम की मरम्मत", "Bathroom repair"),
    patterns=(r"bathroom", r"washroom", r"toilet", r"बाथरूम", r"टॉयलेट", r"basin", r"shower", r"\btap\b", r"\bnal\b", r"नल", r"faucet"),
    summary=t(
        "Most bathroom repairs are a dripping tap, a leaking joint or gaps around the basin and tiles: turn the water off, fix the part, seal the joints.",
        "ज़्यादातर बाथरूम की मरम्मत टपकता नल, रिसता जोड़ या बेसिन/टाइल के पास की दरारें होती हैं: पानी बंद करें, पुर्ज़ा ठीक करें, जोड़ सील करें।",
        "Zyadatar bathroom repair tapakta nal, leak karta joint ya basin/tiles ke gaps hote hain: paani band karein, part theek karein, joints seal karein.",
    ),
    questions=(
        Question(
            "problem", "choice", t("What needs fixing?", "क्या ठीक करना है?", "Kya theek karna hai?"),
            choices=(
                Choice("tap_leak", t("A dripping tap", "टपकता नल", "Tapakta nal"), (r"drip", r"leak\w*\s+(tap|faucet)", r"tap\s+(is\s+)?leak", r"tapak", r"टपक")),
                Choice("replace_tap", t("Replace a tap", "नल बदलना", "Nal badalna"), (r"(new|replace|change)\s+(the\s+)?taps?", r"nal\s+badal", r"नल\s+बदल")),
                Choice("joint_leak", t("A leaking pipe joint", "पाइप का जोड़ रिसना", "Pipe joint leak"), (r"(pipe|joint)\s+leak", r"leak\w*\s+(pipe|joint)", r"रिस")),
                Choice("sealing", t("Gaps around basin / tiles", "बेसिन / टाइल के पास दरारें", "Basin / tiles ke gaps"), (r"gap", r"seal", r"grout", r"दरार")),
            ),
        ),
        Question("taps", "number", t("How many taps?", "कितने नल?", "Kitne nal?"), unit="taps", maximum=20, count_words=("taps", "tap", "nal", "नल"),
                 when=lambda a: a.get("problem") == "replace_tap"),
        Question("gap_length", "number", t("Total length of gaps to seal (metres)", "सील करने वाली दरारों की कुल लंबाई (मीटर)", "Seal karne wale gaps ki lambai (metre)"),
                 unit="m", maximum=100, default=3, role="metres"),
    ),  # fmt: skip
    materials=_bathroom,
    caution=t("Turn off the water supply (or the valve under the basin) before opening any fitting.", "कोई भी फ़िटिंग खोलने से पहले पानी की सप्लाई (या बेसिन के नीचे का वाल्व) बंद करें।",
              "Koi bhi fitting kholne se pehle paani ki supply (ya basin ke neeche ka valve) band karein."),
)


# --- Plumbing ----------------------------------------------------------------------------------------

PIPE_LENGTH_M = 3  # catalogue pipes come in 3 m lengths (the product name says so)


def _plumbing(a: dict) -> list[Need]:
    job, kind, size = a["job"], a.get("pipe_kind") or "cpvc", a.get("pipe_size") or "1/2"
    needs = []
    if job == "new_line":
        metres = float(a["length_m"])
        pipe = F.pipe_metres(metres)
        needs.append(
            Need("pipe", t(f"{kind.upper()} pipe", f"{kind.upper()} पाइप"), (f"{kind} pipe", "pipe"), pipe.amount, "m",
                 t("CPVC takes hot and cold water." if kind == "cpvc" else "UPVC is for cold water lines.",
                   "CPVC गर्म और ठंडे पानी दोनों के लिए है।" if kind == "cpvc" else "UPVC ठंडे पानी की लाइन के लिए है।"),
                 hint=size, steps=tuple(pipe.steps))
        )  # fmt: skip
    if job in ("new_line", "replace_fittings"):
        fittings = int(a.get("fittings") or 0)
        if fittings:
            needs.append(Need("elbows", t(f"{kind.upper()} elbows", "एल्बो (मोड़)"), (f"{kind} elbow", "elbow"), fittings, "pcs",
                              t("One per bend you told us about.", "आपके बताए हर मोड़ के लिए एक।", "Har mod ke liye ek."), estimate=False, hint=size))  # fmt: skip
        valves = int(a.get("valves") or 0)
        if valves:
            needs.append(Need("valve", t("Ball valve", "बॉल वाल्व"), ("ball valve", "valve"), valves, "pcs",
                              t("Lets you shut off this line for repairs.", "मरम्मत के लिए इस लाइन को बंद करने देता है।", "Repair ke liye line band kar sakte hain."), estimate=False, hint=size))  # fmt: skip
        lengths = math.ceil(float(a.get("length_m") or 0) * (1 + F.PIPE_CUT_SHARE) / PIPE_LENGTH_M) if job == "new_line" else 0
        solvent = F.solvent_tins(fittings, int(a.get("tees") or 0), lengths)
        needs.append(Need("solvent", t("Solvent cement", "सॉल्वेंट सीमेंट"), (f"{kind} solvent cement", "solvent cement"), solvent.amount, "pcs",
                          t("Glues the pipe into the fittings.", "पाइप को फ़िटिंग में जोड़ता है।", "Pipe ko fitting mein jodta hai."), steps=tuple(solvent.steps)))  # fmt: skip
        needs.append(Need("hacksaw", t("Hacksaw", "आरी"), ("hacksaw",), 1, "pcs", t("To cut the pipe.", "पाइप काटने के लिए।", "Pipe kaatne ke liye."), optional=True, estimate=False))
    needs.append(Need("ptfe_tape", t("PTFE thread seal tape", "PTFE टेप"), ("ptfe tape",), 1, "pcs",
                      t("For threaded joints (taps, valves).", "चूड़ीदार जोड़ों (नल, वाल्व) के लिए।", "Threaded joints (nal, valve) ke liye."), estimate=False))  # fmt: skip
    if job == "fix_leak":
        needs.append(Need("sealant", t("Silicone sealant", "सिलिकॉन सीलेंट"), ("silicone sealant", "sealant"), 1, "pcs",
                          t("Seals small leaks around joints.", "जोड़ों के आसपास छोटे रिसाव सील करता है।", "Joints ke aas-paas chhote leak seal karta hai."), estimate=False))  # fmt: skip
    needs.append(Need("wrench", t("Pipe wrench", "पाइप रिंच"), ("pipe wrench", "wrench"), 1, "pcs",
                      t("To tighten threaded fittings.", "चूड़ीदार फ़िटिंग कसने के लिए।", "Threaded fitting kasne ke liye."), optional=True, estimate=False))  # fmt: skip
    return needs


PLUMBING = ProjectTemplate(
    key="plumbing",
    name=t("Plumbing", "प्लंबिंग", "Plumbing"),
    patterns=(r"plumb", r"\bpipes?\b", r"\bpaip\b", r"पाइप", r"fitting", r"valve", r"water\s+line", r"पानी\s+की\s+लाइन", r"geyser\s+line"),
    summary=t(
        "Plumbing work needs the right pipe (CPVC for hot water, UPVC for cold), matching fittings and solvent cement, and PTFE tape on threaded joints.",
        "प्लंबिंग में सही पाइप (गर्म पानी के लिए CPVC, ठंडे के लिए UPVC), उसकी फ़िटिंग, सॉल्वेंट सीमेंट और चूड़ीदार जोड़ों पर PTFE टेप चाहिए।",
        "Plumbing mein sahi pipe (garam paani ke liye CPVC, thande ke liye UPVC), matching fittings, solvent cement aur threaded joints par PTFE tape chahiye.",
    ),
    questions=(
        Question(
            "job", "choice", t("What kind of plumbing job?", "किस तरह का प्लंबिंग काम?", "Kis tarah ka plumbing kaam?"),
            choices=(
                Choice("new_line", t("Lay a new water line", "नई पानी की लाइन", "Nayi paani ki line"), (r"new\s+(water\s+)?line", r"new\s+pipe", r"nayi\s+line", r"नई\s+लाइन", r"\blay\b")),
                Choice("replace_fittings", t("Replace fittings / valves", "फ़िटिंग / वाल्व बदलना", "Fitting / valve badalna"), (r"replace\s+(the\s+)?(fittings?|valves?|elbow)", r"fitting\s+badal")),
                Choice("fix_leak", t("Fix a leak", "रिसाव ठीक करना", "Leak theek karna"), (r"\bleak", r"tapak", r"रिस", r"टपक")),
            ),
        ),
        Question("pipe_kind", "choice", t("Hot water too, or cold water only?", "गर्म पानी भी या सिर्फ़ ठंडा?", "Garam paani bhi ya sirf thanda?"),
                 choices=(Choice("cpvc", t("Hot and cold (CPVC)", "गर्म और ठंडा (CPVC)", "Garam aur thanda (CPVC)"), (r"cpvc", r"hot", r"geyser", r"garam", r"गर्म")),
                          Choice("upvc", t("Cold only (UPVC)", "सिर्फ़ ठंडा (UPVC)", "Sirf thanda (UPVC)"), (r"upvc", r"cold\s+only", r"thanda"))),
                 when=lambda a: a.get("job") in ("new_line", "replace_fittings")),
        Question("pipe_size", "choice", t("Pipe size", "पाइप का साइज़", "Pipe size"),
                 choices=(Choice("1/2", t('1/2 inch (most taps)', '1/2 इंच (ज़्यादातर नल)', '1/2 inch'), (r"1/2", r"half\s+inch", r"आधा\s+इंच")),
                          Choice("3/4", t('3/4 inch', '3/4 इंच'), (r"3/4",)), Choice("1", t("1 inch", "1 इंच"), (r"\b1\s*inch", r"one\s+inch"))),
                 default="1/2"),
        Question("length_m", "number", t("Roughly how many metres of pipe?", "लगभग कितने मीटर पाइप?", "Lagbhag kitne metre pipe?"), unit="m", maximum=500, role="metres",
                 when=lambda a: a.get("job") == "new_line"),
        Question("fittings", "number", t("How many bends (elbows)?", "कितने मोड़ (एल्बो)?", "Kitne mod (elbow)?"), unit="elbows", minimum=0, maximum=200,
                 count_words=("elbows", "elbow", "bends", "bend", "fittings", "fitting", "मोड़"), when=lambda a: a.get("job") in ("new_line", "replace_fittings")),
        Question("valves", "number", t("How many valves?", "कितने वाल्व?", "Kitne valve?"), unit="valves", minimum=0, maximum=50,
                 count_words=("valves", "valve", "वाल्व"), default=1, when=lambda a: a.get("job") in ("new_line", "replace_fittings")),
    ),  # fmt: skip
    materials=_plumbing,
    caution=t("Shut the main water valve first. Concealed (in-wall) lines and drainage are best left to a plumber.", "पहले मुख्य वाल्व बंद करें। दीवार के अंदर की लाइन और ड्रेनेज का काम प्लंबर से करवाएँ।",
              "Pehle main valve band karein. Deewar ke andar ki line aur drainage ka kaam plumber se karwayein."),
    professional=lambda a: a.get("job") == "new_line",
)


# --- Electrical --------------------------------------------------------------------------------------

WIRE_COIL_M = 90


def _electrical(a: dict) -> list[Need]:
    job = a["job"]
    needs = []
    if job == "new_points":
        points, metres = int(a["points"]), float(a["wire_m"])
        wire = F.wire_metres(metres)
        needs += [
            Need("wire", t("1.5 sq mm copper wire", "1.5 sq mm तांबे का तार"), ("1.5 sq mm wire", "wire"), wire.amount, "m",
                 t("1.5 sq mm is the usual size for lights, fans and 6 A sockets; the electrician confirms it for the load.",
                   "लाइट, पंखे और 6 A सॉकेट के लिए आमतौर पर 1.5 sq mm; लोड के हिसाब से इलेक्ट्रीशियन पक्का करें।",
                   "Light, fan aur 6 A socket ke liye aksar 1.5 sq mm; load ke hisaab se electrician confirm karein."), hint="1.5 sq mm", steps=tuple(wire.steps)),
            Need("switches", t("Modular switches", "मॉड्यूलर स्विच"), ("modular switch", "switch"), points, "pcs",
                 t("One switch per point.", "हर पॉइंट पर एक स्विच।", "Har point par ek switch."), estimate=False),
            Need("sockets", t("Sockets", "सॉकेट"), ("socket",), math.ceil(points / 2), "pcs",
                 t("About one socket for every two points.", "लगभग हर दो पॉइंट पर एक सॉकेट।", "Lagbhag har do point par ek socket.")),
            Need("mcb", t("MCB", "MCB"), ("mcb",), 1, "pcs", t("Protects the new circuit; the electrician picks the rating.", "नए सर्किट की सुरक्षा; रेटिंग इलेक्ट्रीशियन तय करें।",
                 "Naye circuit ki suraksha; rating electrician tay karein."), optional=True, estimate=False),
        ]  # fmt: skip
    elif job == "replace_switches":
        needs.append(Need("switches", t("Modular switches", "मॉड्यूलर स्विच"), ("modular switch", "switch"), int(a["points"]), "pcs",
                          t("The switches you want to replace.", "जो स्विच बदलने हैं।", "Jo switch badalne hain."), estimate=False))  # fmt: skip
    elif job == "fan":
        needs.append(Need("fan", t("Ceiling fan", "छत का पंखा"), ("ceiling fan", "fan"), int(a.get("count") or 1), "pcs",
                          t("The fan(s) you want to install.", "जो पंखे लगाने हैं।", "Jo pankhe lagane hain."), estimate=False))  # fmt: skip
    elif job == "lights":
        needs.append(Need("lights", t("LED lights", "LED लाइट"), ("led batten", "led bulb"), int(a.get("count") or 1), "pcs",
                          t("The lights you want to install.", "जो लाइटें लगानी हैं।", "Jo lights lagani hain."), estimate=False))  # fmt: skip
    needs += [
        Need("insulation_tape", t("Insulation tape", "इंसुलेशन टेप"), ("insulation tape",), 1, "pcs",
             t("Covers bare joints.", "खुले जोड़ ढकने के लिए।", "Khule joints dhakne ke liye."), estimate=False),
        Need("tester", t("Line tester", "लाइन टेस्टर"), ("line tester", "tester"), 1, "pcs",
             t("Check the supply is really off before touching wires.", "तार छूने से पहले जाँचें कि सप्लाई सच में बंद है।", "Taar chhoone se pehle check karein ki supply sach mein band hai."), estimate=False),
    ]  # fmt: skip
    return needs


ELECTRICAL = ProjectTemplate(
    key="electrical",
    name=t("Electrical work", "बिजली का काम", "Electrical work"),
    patterns=(r"wiring", r"electric", r"bijli", r"बिजली", r"switch", r"socket", r"\bfan\b", r"pankha", r"पंखा", r"\blights?\b", r"\bmcb\b", r"स्विच", r"सॉकेट"),
    summary=t(
        "Electrical work needs the right wire for the load, switches and sockets, protection by an MCB, and a line tester. New circuits must be done by a licensed electrician.",
        "बिजली के काम में लोड के हिसाब से तार, स्विच और सॉकेट, MCB से सुरक्षा और लाइन टेस्टर चाहिए। नए सर्किट लाइसेंस प्राप्त इलेक्ट्रीशियन ही लगाएँ।",
        "Bijli ke kaam mein load ke hisaab se wire, switch aur socket, MCB se suraksha aur line tester chahiye. Naye circuit licensed electrician hi lagayein.",
    ),
    questions=(
        Question(
            "job", "choice", t("What electrical work?", "कौन सा बिजली का काम?", "Kaunsa bijli ka kaam?"),
            choices=(
                Choice("new_points", t("New points / wiring", "नए पॉइंट / वायरिंग", "Naye point / wiring"), (r"wiring", r"new\s+points?", r"rewir", r"वायरिंग")),
                Choice("replace_switches", t("Replace switches", "स्विच बदलना", "Switch badalna"), (r"(replace|change)\s+(the\s+)?switch", r"switch\s+badal", r"स्विच\s+बदल")),
                Choice("fan", t("Install a fan", "पंखा लगाना", "Pankha lagana"), (r"\bfan\b", r"pankha", r"पंखा")),
                Choice("lights", t("Install lights", "लाइट लगाना", "Light lagana"), (r"\blights?\b", r"\bled\b", r"tube\s*light", r"लाइट")),
            ),
        ),
        Question("points", "number", t("How many switch points?", "कितने स्विच पॉइंट?", "Kitne switch point?"), unit="points", maximum=100,
                 count_words=("points", "point", "switches", "switch", "पॉइंट", "स्विच"), when=lambda a: a.get("job") in ("new_points", "replace_switches")),
        Question("wire_m", "number", t("Roughly how many metres of wiring?", "लगभग कितने मीटर वायरिंग?", "Lagbhag kitne metre wiring?"), unit="m", maximum=2000, role="metres",
                 when=lambda a: a.get("job") == "new_points"),
        Question("count", "number", t("How many?", "कितने?", "Kitne?"), unit="", maximum=50, count_words=("fans", "fan", "lights", "light", "pankhe", "पंखे", "लाइट"),
                 default=1, when=lambda a: a.get("job") in ("fan", "lights")),
    ),  # fmt: skip
    materials=_electrical,
    safety=("electrical",),
    professional=lambda a: True,
)


# --- Furniture installation / repair -----------------------------------------------------------------


def _furniture(a: dict) -> list[Need]:
    job = a["job"]
    if job == "wall_mount":
        return _drilling(a)
    needs = [
        Need("screwdriver", t("Screwdriver set", "पेचकस सेट"), ("screwdriver set", "screwdriver"), 1, "pcs",
             t("For assembly screws and hinges.", "जोड़ने वाले स्क्रू और कब्ज़ों के लिए।", "Assembly screws aur hinges ke liye."), estimate=False),
        Need("screws", t("Wood screws", "लकड़ी के स्क्रू"), ("wood screws", "screws"), 20, "pcs",
             t("Spare screws for loose or missing ones.", "ढीले या गायब स्क्रू के बदले।", "Dheele ya gayab screws ke badle."), optional=job == "assemble"),
    ]  # fmt: skip
    if job == "repair":
        needs += [
            Need("wood_adhesive", t("Wood adhesive", "लकड़ी का गोंद"), ("wood adhesive",), 1, "pcs",
                 t("Re-glues loose joints.", "ढीले जोड़ दोबारा चिपकाने के लिए।", "Dheele joints dobara chipkane ke liye."), estimate=False),
            Need("sandpaper", t("Sandpaper", "रेगमाल"), ("sandpaper",), 5, "pcs", t("Cleans the joint before gluing.", "चिपकाने से पहले जोड़ साफ़ करने के लिए।", "Chipkane se pehle joint saaf karne ke liye."), optional=True, estimate=False),
        ]  # fmt: skip
    needs.append(Need("hammer", t("Hammer", "हथौड़ा"), ("claw hammer", "hammer"), 1, "pcs", t("For dowels and nails.", "डॉवेल और कीलों के लिए।", "Dowel aur keelon ke liye."), optional=True, estimate=False))
    return needs


FURNITURE = ProjectTemplate(
    key="furniture_repair",
    name=t("Furniture installation / repair", "फ़र्नीचर लगाना / मरम्मत", "Furniture fitting / repair"),
    patterns=(r"furniture", r"cupboard", r"almirah", r"wardrobe", r"\btable\b", r"chair", r"\bbed\b", r"drawer", r"hinge", r"assembl", r"फ़र्नीचर", r"फर्नीचर", r"अलमारी", r"कुर्सी"),
    summary=t("Furniture jobs need a good screwdriver, spare screws and wood glue for loose joints; wall-mounted pieces also need plugs and the right drill bit.",
              "फ़र्नीचर के काम के लिए अच्छा पेचकस, अतिरिक्त स्क्रू और ढीले जोड़ों के लिए गोंद; दीवार पर लगने वाले सामान के लिए प्लग और सही ड्रिल बिट भी।",
              "Furniture ke kaam ke liye achha pechkas, extra screws aur dheele joints ke liye gond; deewar par lagne wale saamaan ke liye plug aur sahi drill bit bhi."),
    questions=(
        Question(
            "job", "choice", t("What do you want to do?", "क्या करना है?", "Kya karna hai?"),
            choices=(
                Choice("assemble", t("Assemble new furniture", "नया फ़र्नीचर जोड़ना", "Naya furniture jodna"), (r"assembl", r"new\s+(furniture|table|bed|wardrobe)", r"jodna")),
                Choice("repair", t("Repair loose / broken furniture", "ढीला / टूटा फ़र्नीचर ठीक करना", "Dheela / toota furniture theek karna"), (r"repair", r"loose", r"broken", r"wobbl", r"theek", r"ठीक", r"टूट")),
                Choice("wall_mount", t("Fix it to a wall", "दीवार पर लगाना", "Deewar par lagana"), (r"(on|to)\s+(the\s+)?wall", r"wall\s+mount", r"deewar\s+par", r"दीवार\s+पर")),
            ),
        ),
        Question(WALL_TYPE.key, WALL_TYPE.kind, WALL_TYPE.text, WALL_TYPE.choices, when=lambda a: a.get("job") == "wall_mount"),
        Question("holes", "number", t("How many holes do you need?", "कितने छेद चाहिए?", "Kitne chhed chahiye?"), unit="holes", maximum=500,
                 count_words=("holes", "hole", "chhed", "छेद"), when=lambda a: a.get("job") == "wall_mount"),
        Question(HAVE_DRILL.key, HAVE_DRILL.kind, HAVE_DRILL.text, HAVE_DRILL.choices, when=lambda a: a.get("job") == "wall_mount"),
    ),  # fmt: skip
    materials=_furniture,
)


# --- Basic construction and plastering ---------------------------------------------------------------

PLASTER_RATIO = Question(
    "ratio", "choice", t("Mortar mix (cement : sand)", "मसाले का अनुपात (सीमेंट : रेत)", "Masale ka ratio (cement : ret)"),
    choices=(Choice("1:4", t("1:4 (ceilings, outside walls)", "1:4 (छत, बाहर की दीवार)", "1:4 (chhat, bahar ki deewar)"), (r"1\s*:\s*4",)),
             Choice("1:5", t("1:5 (inside walls)", "1:5 (अंदर की दीवार)", "1:5 (andar ki deewar)"), (r"1\s*:\s*5",)),
             Choice("1:6", t("1:6 (rough / brick walls)", "1:6 (खुरदरी / ईंट की दीवार)", "1:6 (khurdari / eent ki deewar)"), (r"1\s*:\s*6",))),
    default="1:5",
)
THICKNESS = Question("thickness_mm", "number", t("Plaster thickness (mm)", "प्लास्टर की मोटाई (मिमी)", "Plaster ki motai (mm)"), unit="mm", minimum=6, maximum=40, default=12)


def _wastage(default: float) -> Question:
    return Question("wastage", "number", t("Extra for wastage (%)", "बर्बादी के लिए अतिरिक्त (%)", "Wastage ke liye extra (%)"), unit="%", minimum=0, maximum=30, default=default)


def _plaster_needs(a: dict) -> list[Need]:
    cement, sand = F.plaster(float(a["area"]), float(a.get("thickness_mm") or 12), a.get("ratio") or "1:5", float(a.get("wastage", 5)))
    return [
        Need("cement", t("Cement (50 kg bags)", "सीमेंट (50 किलो बोरी)"), ("ppc cement", "cement"), cement.amount, "pcs",
             t("PPC cement suits plastering.", "प्लास्टर के लिए PPC सीमेंट अच्छा है।", "Plaster ke liye PPC cement achha hai."), hint="50 kg", steps=tuple(cement.steps)),
        Need("sand", t("Plastering sand", "प्लास्टर की रेत", "Plaster ki ret"), ("plaster sand", "river sand", "sand"), sand.amount, "cft",
             t("Fine sand for the mortar.", "मसाले के लिए बारीक रेत।", "Masale ke liye baarik ret."), steps=tuple(sand.steps)),
    ]


def _construction(a: dict) -> list[Need]:
    work, area = a["work"], float(a["area"])
    if work == "plastering":
        needs = _plaster_needs(a)
    else:
        cement = F.masonry_cement(area, work)
        needs = [
            Need("cement", t("Cement (50 kg bags)", "सीमेंट (50 किलो बोरी)"), ("ppc cement", "cement"), max(1, cement.amount), "pcs",
                 t("PPC cement suits plastering and masonry." if work != "repair" else "For patching cracks and small repairs.",
                   "प्लास्टर और चिनाई के लिए PPC सीमेंट अच्छा है।" if work != "repair" else "दरारें और छोटी मरम्मत के लिए।"),
                 hint="50 kg", steps=tuple(cement.steps)),
        ]
    if work == "repair":
        needs.append(Need("crack_filler", t("Crack filler", "क्रैक फ़िलर"), ("crack filler",), 1, "pcs", t("For hairline cracks.", "बारीक दरारों के लिए।", "Baarik daraaron ke liye."), estimate=False))
    needs += [
        Need("gloves", t("Work gloves", "दस्ताने"), ("gloves",), 1, "pcs", t("Cement is harsh on skin.", "सीमेंट त्वचा के लिए हानिकारक है।", "Cement skin ke liye harsh hai."), estimate=False),
        Need("goggles", t("Safety goggles", "सुरक्षा चश्मा"), ("safety goggles", "goggles"), 1, "pcs", t("Protects eyes from splashes.", "छींटों से आँखें बचाता है।", "Chheenton se aankhein bachata hai."), optional=True, estimate=False),
        Need("helmet", t("Safety helmet", "हेलमेट"), ("helmet",), 1, "pcs", t("For work at height or under scaffolding.", "ऊँचाई या मचान के नीचे काम के लिए।", "Unchai ya machaan ke neeche kaam ke liye."), optional=True, estimate=False),
    ]
    return needs


CONSTRUCTION = ProjectTemplate(
    key="construction",
    name=t("Basic construction", "छोटा निर्माण कार्य", "Basic construction"),
    patterns=(r"plaster", r"brick\s*work", r"masonry", r"construct", r"build\s+a\s+wall", r"deewar\s+banan", r"प्लास्टर", r"चिनाई", r"\bcement\b", r"सीमेंट", r"chunai"),
    summary=t("Plastering and brickwork need cement (plus sand and bricks from a builders' merchant), water, and protective gear.",
              "प्लास्टर और चिनाई के लिए सीमेंट (साथ में रेत और ईंट), पानी और सुरक्षा उपकरण चाहिए।",
              "Plaster aur chinai ke liye cement (saath mein ret aur eent), paani aur safety gear chahiye."),
    questions=(
        Question(
            "work", "choice", t("What kind of work?", "किस तरह का काम?", "Kis tarah ka kaam?"),
            choices=(
                Choice("plastering", t("Plastering", "प्लास्टर", "Plaster"), (r"plaster", r"प्लास्टर")),
                Choice("brickwork", t("Brickwork (building a wall)", "चिनाई (दीवार बनाना)", "Chinai (deewar banana)"), (r"brick\s*work", r"build\s+a\s+wall", r"masonry", r"chinai", r"चिनाई", r"deewar\s+banan")),
                Choice("repair", t("Small repairs / cracks", "छोटी मरम्मत / दरारें", "Chhoti repair / daraarein"), (r"repair", r"crack", r"patch", r"दरार", r"मरम्मत")),
            ),
        ),
        _area(t("How big is the wall area (sq ft)?", "दीवार का क्षेत्रफल कितना है (वर्ग फ़ुट)?", "Deewar ka area kitna hai (sq ft)?")),
        Question(THICKNESS.key, "number", THICKNESS.text, unit="mm", minimum=6, maximum=40, default=12, when=lambda a: a.get("work") == "plastering"),
        Question(PLASTER_RATIO.key, "choice", PLASTER_RATIO.text, PLASTER_RATIO.choices, default="1:5", when=lambda a: a.get("work") == "plastering"),
    ),
    materials=_construction,
    safety=("structural",),
    professional=lambda a: a.get("work") == "brickwork",
    not_sold=t("Sand, bricks and aggregate are not sold here.", "रेत, ईंट और गिट्टी यहाँ नहीं मिलती।", "Ret, eent aur gitti yahan nahi milti."),
    risky=True,
)


def _plastering(a: dict) -> list[Need]:
    return [*_plaster_needs(a),
            Need("gloves", t("Work gloves", "दस्ताने"), ("gloves",), 1, "pcs", t("Cement is harsh on skin.", "सीमेंट त्वचा के लिए हानिकारक है।", "Cement skin ke liye harsh hai."), optional=True, estimate=False)]


PLASTERING = ProjectTemplate(
    key="plastering",
    name=t("Plastering", "प्लास्टर", "Plaster"),
    patterns=(r"plaster", r"प्लास्टर"),
    summary=t("Cement plaster: cement and sand mixed with water, laid about 12 mm thick on the wall.",
              "सीमेंट प्लास्टर: सीमेंट और रेत पानी के साथ, दीवार पर लगभग 12 मिमी मोटा।",
              "Cement plaster: cement aur ret paani ke saath, deewar par lagbhag 12 mm mota."),
    questions=(
        _area(t("How big is the area to plaster (sq ft)?", "कितने क्षेत्र में प्लास्टर करना है (वर्ग फ़ुट)?", "Kitne area mein plaster karna hai (sq ft)?")),
        THICKNESS, PLASTER_RATIO, _wastage(5),
    ),
    materials=_plastering,
    safety=("structural",),
    not_sold=t("Sand may not be sold here; the amount is shown so you can buy it locally.", "रेत शायद यहाँ न मिले; मात्रा दिखाई गई है ताकि आप पास से ले सकें।", "Ret shayad yahan na mile; quantity dikhayi gayi hai taaki aap paas se le sakein."),
    title=lambda a, lang: say(t("Plastering · {a} sq ft", "प्लास्टर · {a} वर्ग फ़ुट", "Plaster · {a} sq ft"), lang, a=_n(a.get("area"))),
    risky=True,
    examples=("I need materials for 500 sq ft plastering", "Mujhe 500 sq ft ke liye plastering ka saman chahiye", "50 kg cement for plastering 300 sq ft"),
)


# --- Waterproofing -----------------------------------------------------------------------------------


def _waterproofing(a: dict) -> list[Need]:
    area = float(a["area"])
    coating = F.waterproofing_litres(area)
    needs = [
        Need("coating", t("Waterproofing coating", "वॉटरप्रूफ़िंग कोटिंग"), ("waterproofing coating", "waterproofing"), coating.amount, "l",
             t(f"Two coats at about {F.WATERPROOF_SQFT_PER_L} sq ft per litre.", f"दो कोट, लगभग {F.WATERPROOF_SQFT_PER_L} वर्ग फ़ुट प्रति लीटर।", f"Do coat, lagbhag {F.WATERPROOF_SQFT_PER_L} sq ft per litre."),
             steps=tuple(coating.steps)),
    ]
    if a.get("cracks") == "yes":
        filler = F.crack_filler_kg(area)
        needs.append(Need("crack_filler", t("Crack filler", "क्रैक फ़िलर"), ("crack filler",), filler.amount, "kg",
                          t("Recommended because you said there are cracks: fill them before coating.", "आपने दरारें बताईं: कोटिंग से पहले भरें।", "Aapne daraarein batayi: coating se pehle bharein."),
                          steps=tuple(filler.steps)))
    needs += [
        Need("roller", t("Paint roller", "पेंट रोलर"), ("paint roller", "roller"), 1, "pcs", t("Spreads the coating evenly.", "कोटिंग बराबर फैलाता है।", "Coating barabar failata hai."), estimate=False),
        Need("brush", t("Brushes", "ब्रश"), ("paint brush", "brush"), 1, "pcs", t("For corners and joints.", "कोनों और जोड़ों के लिए।", "Konon aur joints ke liye."), estimate=False),
        Need("gloves", t("Work gloves", "दस्ताने"), ("gloves",), 1, "pcs", t("Keeps the coating off your hands.", "हाथों को कोटिंग से बचाता है।", "Haathon ko coating se bachata hai."), optional=True, estimate=False),
    ]
    return needs


WATERPROOFING = ProjectTemplate(
    key="waterproofing",
    name=t("Waterproofing", "वॉटरप्रूफ़िंग", "Waterproofing"),
    patterns=(r"waterproof", r"seepage", r"seelan", r"सीलन", r"damp", r"नमी", r"roof\s+leak", r"terrace", r"chhat", r"छत", r"leak\w*\s+(roof|ceiling)"),
    summary=t("Clean the surface, fill cracks, then apply two coats of waterproofing coating, letting the first dry fully.",
              "सतह साफ़ करें, दरारें भरें, फिर वॉटरप्रूफ़िंग के दो कोट लगाएँ; पहला कोट पूरा सूखने दें।",
              "Surface saaf karein, daraarein bharein, phir waterproofing ke do coat lagayein; pehla coat poora sookhne dein."),
    questions=(
        Question("location", "choice", t("Where is the waterproofing needed?", "वॉटरप्रूफ़िंग कहाँ करनी है?", "Waterproofing kahan karni hai?"),
                 choices=(Choice("roof", t("Roof / terrace", "छत", "Chhat / terrace"), (r"roof", r"terrace", r"chhat", r"छत")),
                          Choice("bathroom", t("Bathroom floor / walls", "बाथरूम", "Bathroom"), (r"bathroom", r"washroom", r"बाथरूम")),
                          Choice("wall", t("A damp wall", "सीलन वाली दीवार", "Seelan wali deewar"), (r"wall", r"deewar", r"दीवार", r"seelan", r"सीलन")))),
        _area(t("How big is the area (sq ft)?", "जगह कितनी बड़ी है (वर्ग फ़ुट)?", "Area kitna bada hai (sq ft)?")),
        Question("cracks", "choice", t("Are there visible cracks?", "क्या दरारें दिखती हैं?", "Kya daraarein dikhti hain?"),
                 choices=(Choice("yes", YES.label, (r"crack", r"daraar", r"दरार")), Choice("no", NO.label, (r"no\s+cracks",)))),
    ),
    materials=_waterproofing,
    safety=("heights",),
    professional=lambda a: a.get("location") == "roof" and float(a.get("area") or 0) > 500,
    risky=True,
    title=lambda a, lang: say(t("Waterproofing · {a} sq ft", "वॉटरप्रूफ़िंग · {a} वर्ग फ़ुट", "Waterproofing · {a} sq ft"), lang, a=_n(a.get("area"))),
    examples=("Waterproofing for a 300 sq ft terrace with cracks",),
)


# --- Tiling and flooring -----------------------------------------------------------------------------

# value → (sq ft per tile, label). The patterns read "2x2 tiles", "600x600 mm", "60 x 60 cm".
TILE_SIZES = {
    "1x1": (1.0, "1 × 1 ft (300 × 300 mm)"),
    "16x16": (1.78, "16 × 16 in (400 × 400 mm)"),
    "2x2": (4.0, "2 × 2 ft (600 × 600 mm)"),
    "32x32": (6.89, "800 × 800 mm"),
    "2x4": (8.0, "2 × 4 ft (600 × 1200 mm)"),
}
TILE_SIZE = Question(
    "tile_size", "choice", t("Tile size", "टाइल का साइज़", "Tile size"),
    choices=(
        Choice("1x1", t(TILE_SIZES["1x1"][1], TILE_SIZES["1x1"][1]), (r"\b1\s*x\s*1\s*(ft|feet|foot)?\s*til", r"\b12\s*x\s*12\s*(in|inch)", r"\b300\s*x\s*300\b", r"\b30\s*x\s*30\s*cm")),
        Choice("16x16", t(TILE_SIZES["16x16"][1], TILE_SIZES["16x16"][1]), (r"\b16\s*x\s*16\b", r"\b400\s*x\s*400\b", r"\b40\s*x\s*40\s*cm")),
        Choice("2x2", t(TILE_SIZES["2x2"][1], TILE_SIZES["2x2"][1]), (r"\b2\s*x\s*2\s*(ft|feet|foot)?\s*til", r"\b24\s*x\s*24\s*(in|inch)", r"\b600\s*x\s*600\b", r"\b60\s*x\s*60\s*cm")),
        Choice("32x32", t(TILE_SIZES["32x32"][1], TILE_SIZES["32x32"][1]), (r"\b800\s*x\s*800\b", r"\b80\s*x\s*80\s*cm")),
        Choice("2x4", t(TILE_SIZES["2x4"][1], TILE_SIZES["2x4"][1]), (r"\b2\s*x\s*4\s*(ft|feet|foot)?\s*til", r"\b600\s*x\s*1200\b", r"\b60\s*x\s*120\s*cm")),
    ),
    default="2x2",
)


def _floor_size_questions(what: dict) -> tuple[Question, ...]:
    """The area when the customer gave one ("300 sq ft"), else length × width."""
    no_area = lambda a: not a.get("area")  # noqa: E731
    return (
        Question("area", "number", what, unit="sq ft", maximum=50_000, role="area", when=lambda a: bool(a.get("area"))),
        _length(t("How long is it (feet)?", "कितनी लंबी है (फ़ुट)?", "Kitni lambi hai (feet)?"), when=no_area),
        _width(t("How wide is it (feet)?", "कितनी चौड़ी है (फ़ुट)?", "Kitni chaudi hai (feet)?"), when=no_area),
    )


def _tiling(a: dict) -> list[Need]:
    floor = F.floor_area(a)
    area = floor.amount
    size_sqft, size_label = TILE_SIZES[a.get("tile_size") or "2x2"]
    count = F.tiles(area, size_sqft, size_label, float(a.get("wastage", 10)))
    adhesive, grout, spacer = F.tile_adhesive_bags(area), F.grout_kg(area), F.spacers(int(count.amount))
    return [
        Need("tiles", t(f"Tiles, {size_label}", f"टाइल, {size_label}"), ("floor tiles", "wall tiles", "tiles"), count.amount, "pcs",
             t("Tiles to cover the area, with extra for cuts and breakage.", "क्षेत्र भरने के लिए टाइल, कटाई और टूट-फूट के लिए अतिरिक्त।", "Area bharne ke liye tiles, cutting aur toot-phoot ke liye extra."),
             steps=tuple(floor.steps + count.steps), avoid=("adhesive", "grout", "spacer", "spacers", "cutter", "cleaner")),
        Need("adhesive", t("Tile adhesive (20 kg bags)", "टाइल एडहेसिव (20 किलो बोरी)"), ("tile adhesive",), adhesive.amount, "pcs",
             t("Fixes the tiles (3-4 mm bed).", "टाइल चिपकाने के लिए (3-4 मिमी)।", "Tiles chipkane ke liye (3-4 mm)."), steps=tuple(floor.steps + adhesive.steps)),
        Need("grout", t("Tile grout", "टाइल ग्राउट"), ("tile grout", "grout"), grout.amount, "kg",
             t("Fills the joints.", "जोड़ भरने के लिए।", "Joints bharne ke liye."), steps=tuple(floor.steps + grout.steps)),
        Need("spacers", t("Tile spacers", "टाइल स्पेसर"), ("tile spacers", "spacer"), spacer.amount, "pcs",
             t("Keep the joints even.", "जोड़ बराबर रखते हैं।", "Joints barabar rakhte hain."), steps=tuple(spacer.steps)),
        Need("measuring_tape", t("Measuring tape", "मापने का टेप"), ("measuring tape",), 1, "pcs", t("For layout lines.", "लेआउट के निशान के लिए।", "Layout ke nishaan ke liye."), optional=True, estimate=False),
        Need("gloves", t("Work gloves", "दस्ताने"), ("gloves",), 1, "pcs", t("Adhesive and grout are harsh on skin.", "एडहेसिव और ग्राउट त्वचा के लिए हानिकारक हैं।", "Adhesive aur grout skin ke liye harsh hain."), optional=True, estimate=False),
    ]


def _area_title(name: dict):
    def title(a: dict, lang: str) -> str:
        if a.get("area"):
            return f"{say(name, lang)} · {_n(a['area'])} sq ft"
        return f"{say(name, lang)} · {_n(a.get('length'))} × {_n(a.get('width'))} ft"

    return title


TILING = ProjectTemplate(
    key="tiling",
    name=t("Tiling", "टाइल लगाना", "Tiling"),
    patterns=(r"\btil(e|es|ing)\b", r"टाइल"),
    summary=t("Tiles are fixed with tile adhesive, kept even with spacers, and the joints are filled with grout the next day.",
              "टाइल एडहेसिव से लगाई जाती हैं, स्पेसर से जोड़ बराबर रखे जाते हैं और अगले दिन जोड़ों में ग्राउट भरा जाता है।",
              "Tiles adhesive se lagti hain, spacer se joints barabar rehte hain aur agle din joints mein grout bhara jata hai."),
    questions=(*_floor_size_questions(t("Area to tile (sq ft)", "टाइल वाला क्षेत्र (वर्ग फ़ुट)", "Tile wala area (sq ft)")), TILE_SIZE, _wastage(10)),
    materials=_tiling,
    not_sold=t("Tiles may not be sold here; the count is shown so you can buy them locally.", "टाइलें शायद यहाँ न मिलें; गिनती दिखाई गई है ताकि आप पास से ले सकें।", "Tiles shayad yahan na milein; ginti dikhayi gayi hai taaki aap paas se le sakein."),
    title=_area_title(t("Tiling", "टाइल", "Tiling")),
    examples=("How many tiles do I need for 300 sq ft?", "Tiling a 10x12 room with 600x600 mm tiles"),
)

FLOORING_KIND = Question(
    "kind", "choice", t("What kind of flooring?", "कौन सी फ़्लोरिंग?", "Kaunsi flooring?"),
    choices=(Choice("laminate", t("Laminate", "लैमिनेट"), (r"laminat", r"लैमिनेट")),
             Choice("vinyl", t("Vinyl / SPC", "विनाइल / SPC"), (r"vinyl", r"\bspc\b", r"\blvt\b", r"विनाइल")),
             Choice("wooden", t("Engineered wood", "लकड़ी की फ़्लोरिंग", "Lakdi ki flooring"), (r"wood(en)?\s+floor", r"engineered", r"लकड़ी"))),
)


def _flooring(a: dict) -> list[Need]:
    floor = F.floor_area(a)
    kind = a["kind"]
    total = F.flooring_sqft(floor.amount, float(a.get("wastage", 10)))
    needs = [
        Need("flooring", t(f"{kind.title()} flooring", f"{kind} फ़्लोरिंग", f"{kind.title()} flooring"), (f"{kind} flooring", "flooring"), total.amount, "sqft",
             t("Boxes are bought by the area they cover.", "डिब्बे उनके कवर किए क्षेत्र के हिसाब से लिए जाते हैं।", "Dibbe unke cover kiye area ke hisaab se liye jaate hain."),
             steps=tuple(floor.steps + total.steps)),
    ]
    if kind in ("laminate", "wooden"):
        needs.append(Need("underlay", t("Flooring underlay", "फ़्लोरिंग अंडरले"), ("flooring underlay", "underlay"), floor.amount, "sqft",
                          t("A foam layer under laminate and wood floors.", "लैमिनेट और लकड़ी की फ़्लोरिंग के नीचे फ़ोम की परत।", "Laminate aur lakdi ki flooring ke neeche foam ki parat."), steps=tuple(floor.steps)))
    if a.get("length") and a.get("width") and not a.get("area"):
        metres = 2 * (float(a["length"]) + float(a["width"])) * 0.3048
        needs.append(Need("skirting", t("Skirting", "स्कर्टिंग"), ("flooring skirting", "skirting"), metres, "m",
                          t("Covers the edge gap along the walls.", "दीवार के किनारे का गैप ढकती है।", "Deewar ke kinare ka gap dhakti hai."), optional=True,
                          steps=((t("Room perimeter", "कमरे की परिधि", "Kamre ki paridhi"), f"2 × ({_n(a['length'])} + {_n(a['width'])}) ft = {U.fmt(metres)} m"),)))
    return needs


FLOORING = ProjectTemplate(
    key="flooring",
    name=t("Flooring", "फ़्लोरिंग", "Flooring"),
    patterns=(r"flooring", r"laminat", r"vinyl", r"\bspc\b", r"wood(en)?\s+floor", r"फ़्लोरिंग", r"फ्लोरिंग"),
    summary=t("Click-fit floors are sold in boxes that cover a set area; buy about 10 % extra for cuts.",
              "क्लिक-फ़िट फ़्लोरिंग डिब्बों में आती है जो तय क्षेत्र ढकते हैं; कटाई के लिए लगभग 10 % ज़्यादा लें।",
              "Click-fit flooring dibbon mein aati hai jo tay area dhakte hain; cutting ke liye lagbhag 10 % zyada lein."),
    questions=(*_floor_size_questions(t("Floor area (sq ft)", "फ़र्श का क्षेत्रफल (वर्ग फ़ुट)", "Farsh ka area (sq ft)")), FLOORING_KIND, _wastage(10)),
    materials=_flooring,
    title=_area_title(t("Flooring", "फ़्लोरिंग", "Flooring")),
    examples=("Laminate flooring for a 12x14 bedroom",),
)


# --- Wiring, pipes, fasteners (quantity calculators) --------------------------------------------------

CROSS_SECTION = Question(
    "cross_section", "choice", t("What is the wire for? (decides its thickness)", "तार किस काम के लिए है? (मोटाई इसी से तय होती है)", "Wire kis kaam ke liye hai? (motai isi se tay hoti hai)"),
    choices=(
        Choice("1.0", t("1.0 sq mm: lights only", "1.0 sq mm: सिर्फ़ लाइट", "1.0 sq mm: sirf light"), (r"\b1(\.0)?\s*sq\.?\s*mm",)),
        Choice("1.5", t("1.5 sq mm: lights, fans, 6 A sockets", "1.5 sq mm: लाइट, पंखे, 6 A सॉकेट", "1.5 sq mm: light, pankhe, 6 A socket"), (r"\b1\.5\s*(sq|mm)", r"\blights?\b", r"\bfans?\b", r"pankh", r"लाइट", r"पंख")),
        Choice("2.5", t("2.5 sq mm: 16 A power sockets", "2.5 sq mm: 16 A पावर सॉकेट", "2.5 sq mm: 16 A power socket"), (r"\b2\.5\s*(sq|mm)", r"power\s+sockets?", r"\b16\s*a\b", r"fridge", r"washing")),
        Choice("4.0", t("4.0 sq mm: AC, geyser, heavy loads", "4.0 sq mm: AC, गीज़र, भारी लोड", "4.0 sq mm: AC, geyser, bhaari load"), (r"\b4(\.0)?\s*sq\.?\s*mm", r"\bac\b", r"air\s*condition", r"geyser", r"गीज़र", r"heater")),
    ),
)
RUNS = Question(
    "runs", "choice", t("Is that the total wire, or the distance to cover?", "यह कुल तार है या दूरी?", "Ye total wire hai ya doori?"),
    choices=(Choice("total", t("Total wire length", "कुल तार की लंबाई", "Total wire ki lambai"), (r"of\s+wire", r"wire\s+length", r"\bcoils?\b")),
             Choice("route", t("Distance to cover (phase + neutral doubled)", "दूरी (फ़ेज़ + न्यूट्रल, दोगुना)", "Doori (phase + neutral, double)"), (r"distance", r"\broute\b", r"\baway\b"))),
    default="total",
)


def _wiring(a: dict) -> list[Need]:
    size = a["cross_section"]
    wire = F.wire_metres(float(a["metres"]), a.get("runs") or "total")
    return [
        Need("wire", t(f"{size} sq mm copper wire", f"{size} sq mm तांबे का तार"), (f"{size} sq mm wire", "copper wire", "wire"), wire.amount, "m",
             t("The size for the load you named; an electrician confirms it.", "आपके बताए लोड का साइज़; इलेक्ट्रीशियन पक्का करें।", "Aapke bataye load ka size; electrician confirm karein."),
             hint=f"{size} sq mm", steps=tuple(wire.steps)),
        Need("insulation_tape", t("Insulation tape", "इंसुलेशन टेप"), ("insulation tape",), 1, "pcs", t("Covers bare joints.", "खुले जोड़ ढकने के लिए।", "Khule joints dhakne ke liye."), optional=True, estimate=False),
    ]


WIRING = ProjectTemplate(
    key="wiring",
    name=t("Wire length", "तार की लंबाई", "Wire length"),
    patterns=(r"\bwires?\b", r"wiring", r"cable", r"तार", r"\btaar\b", r"वायर"),
    summary=t("House wire comes in 90 m coils; the thickness depends on the load.", "घर का तार 90 मीटर के बंडल में आता है; मोटाई लोड पर निर्भर है।", "Ghar ka wire 90 m ke coil mein aata hai; motai load par depend karti hai."),
    questions=(
        Question("metres", "number", t("How much wire (metres)?", "कितना तार (मीटर)?", "Kitna wire (metre)?"), unit="m", minimum=0.5, maximum=5000, role="metres"),
        CROSS_SECTION, RUNS,
    ),
    materials=_wiring,
    safety=("electrical",),
    professional=lambda a: True,
    risky=True,
    title=lambda a, lang: f"{say(t('Wire', 'तार', 'Wire'), lang)} · {_n(a.get('metres'))} m",
    examples=("I need 100 feet of wire for lights", "30 m 2.5 sq mm wire for power sockets"),
)


def _pipes(a: dict) -> list[Need]:
    kind, size = a.get("pipe_kind") or "cpvc", a.get("pipe_size") or "1/2"
    pipe = F.pipe_metres(float(a["length_m"]))
    elbows, tees = int(a.get("elbows") or 0), int(a.get("tees") or 0)
    lengths = math.ceil(round(pipe.amount / PIPE_LENGTH_M, 6))
    needs = [Need("pipe", t(f"{kind.upper()} pipe", f"{kind.upper()} पाइप"), (f"{kind} pipe", "pipe"), pipe.amount, "m",
                  t("CPVC takes hot and cold water." if kind == "cpvc" else "UPVC is for cold water lines.",
                    "CPVC गर्म और ठंडे पानी दोनों के लिए है।" if kind == "cpvc" else "UPVC ठंडे पानी की लाइन के लिए है।"),
                  hint=size, steps=tuple(pipe.steps))]
    if elbows:
        needs.append(Need("elbows", t(f"{kind.upper()} elbows", "एल्बो (मोड़)"), (f"{kind} elbow", "elbow"), elbows, "pcs",
                          t("One per bend.", "हर मोड़ के लिए एक।", "Har mod ke liye ek."), estimate=False, hint=size))
    if tees:
        needs.append(Need("tees", t(f"{kind.upper()} tees", "टी (तीन रास्ते)"), (f"{kind} tee", "tee"), tees, "pcs",
                          t("One per branch.", "हर शाखा के लिए एक।", "Har branch ke liye ek."), estimate=False, hint=size))
    solvent = F.solvent_tins(elbows, tees, lengths)
    needs.append(Need("solvent", t("Solvent cement", "सॉल्वेंट सीमेंट"), (f"{kind} solvent cement", "solvent cement"), solvent.amount, "pcs",
                      t("Glues the pipe into the fittings.", "पाइप को फ़िटिंग में जोड़ता है।", "Pipe ko fitting mein jodta hai."), steps=tuple(solvent.steps)))
    return needs


PIPE_KIND = next(q for q in PLUMBING.questions if q.key == "pipe_kind")
PIPE_SIZE = next(q for q in PLUMBING.questions if q.key == "pipe_size")

PIPES = ProjectTemplate(
    key="pipes",
    name=t("Pipe length", "पाइप की लंबाई", "Pipe length"),
    patterns=(r"\bpipes?\b", r"पाइप", r"\bpaip\b", r"pipeline"),
    summary=t("Pipes come in 3 m lengths; fittings are counted from the bends and branches.", "पाइप 3 मीटर की लंबाई में आते हैं; फ़िटिंग मोड़ और शाखाओं से गिनी जाती है।",
              "Pipe 3 m ki lambai mein aate hain; fitting mod aur branch se gini jaati hai."),
    questions=(
        Question("length_m", "number", t("How many metres of pipe?", "कितने मीटर पाइप?", "Kitne metre pipe?"), unit="m", minimum=0.5, maximum=1000, role="metres"),
        Question(PIPE_KIND.key, "choice", PIPE_KIND.text, PIPE_KIND.choices),
        Question(PIPE_SIZE.key, "choice", PIPE_SIZE.text, PIPE_SIZE.choices, default="1/2"),
        Question("elbows", "number", t("How many bends (elbows)?", "कितने मोड़ (एल्बो)?", "Kitne mod (elbow)?"), unit="elbows", minimum=0, maximum=200, default=0,
                 count_words=("elbows", "elbow", "bends", "bend", "मोड़")),
        Question("tees", "number", t("How many branches (tees)?", "कितनी शाखाएँ (टी)?", "Kitni branch (tee)?"), unit="tees", minimum=0, maximum=200, default=0,
                 count_words=("tees", "tee", "branches")),
    ),
    materials=_pipes,
    risky=True,
    title=lambda a, lang: f"{say(t('Pipe', 'पाइप', 'Pipe'), lang)} · {_n(a.get('length_m'))} m",
    examples=("20 m CPVC pipe with 6 elbows", "UPVC pipe for 15 metres"),
)

FASTENERS = ProjectTemplate(
    key="fasteners",
    name=t("Screws and wall plugs", "स्क्रू और वॉल प्लग", "Screw aur wall plug"),
    patterns=(r"\bscrews?\b", r"wall\s+plugs?", r"fasteners?", r"\banchors?\b", r"स्क्रू", r"\bpech\b"),
    summary=t("One screw and one wall plug per hole, a few spare; the wall decides the plug and the drill bit.", "हर छेद में एक स्क्रू और एक प्लग, कुछ अतिरिक्त; दीवार से प्लग और ड्रिल बिट तय होता है।",
              "Har chhed mein ek screw aur ek plug, kuch extra; deewar se plug aur drill bit tay hota hai."),
    questions=(
        Question("holes", "number", t("How many holes / screws?", "कितने छेद / स्क्रू?", "Kitne chhed / screw?"), unit="holes", maximum=2000,
                 count_words=("holes", "hole", "screws", "screw", "plugs", "chhed", "छेद", "स्क्रू")),
        WALL_TYPE,
    ),
    materials=_drilling,
    title=lambda a, lang: f"{say(t('Screws and plugs', 'स्क्रू और प्लग', 'Screw aur plug'), lang)} · {_n(a.get('holes'))}",
    examples=("Screws and plugs for 12 holes in a brick wall",),
)


# --- Carpentry and door hardware: kitchens, wardrobes, doors, glass, replacements -----------------------------
# Products come from the shop's hinge / channel / handle / board / lock / glass-hardware departments. Every
# "fit" below is the customer's size handed to the compatibility engine (apps.catalog.compatibility): only a
# variant that the listing says fits is chosen, and the line shows the engine's verdict.

MM_PER_FT = 304.8


def _mm_choice(value: str) -> Choice:
    return Choice(value, t(f"{value} mm", f"{value} मिमी", f"{value} mm"), (rf"(?<![\d.]){value}\s*(mm|मिमी)",))


BOARD = Question(
    "board", "choice", t("Which board for the cabinets and shutters?", "कैबिनेट और शटर किस बोर्ड से?", "Cabinet aur shutter kis board se?"),
    choices=(
        Choice("plywood", t("Plywood", "प्लाईवुड", "Plywood / ply"), (r"\bply\w*\b", r"\bplai\b", r"\bplaai\b", r"प्लाई", r"\bbwp\b", r"marine")),
        Choice("hdhmr", t("HDHMR board", "HDHMR बोर्ड", "HDHMR board"), (r"\bhdhmr\b",)),
        Choice("mdf", t("MDF board", "MDF बोर्ड", "MDF board"), (r"\bmdf\b",)),
    ),
    default="plywood",
)
BOARD_MM = Question(
    "board_mm", "choice", t("Board thickness", "बोर्ड की मोटाई", "Board ki motai"),
    choices=tuple(_mm_choice(v) for v in ("18", "12", "16", "19", "25")), default="18",
)
BOARD_SEARCH = {
    "plywood": {"kitchen": ("bwp plywood", "marine plywood", "plywood"), "wardrobe": ("commercial plywood", "mr plywood", "plywood")},
    "hdhmr": {"kitchen": ("hdhmr board", "hdhmr"), "wardrobe": ("hdhmr board", "hdhmr")},
    "mdf": {"kitchen": ("mdf board", "mdf"), "wardrobe": ("mdf board", "mdf")},
}
DRAWERS = Question("drawers", "number", t("How many drawers?", "कितनी दराज़ें?", "Kitni daraz?"), unit="drawers", minimum=0, maximum=100, default=0,
                   count_words=("drawers", "drawer", "daraz", "daraaz", "दराज़", "दराज"))
SHUTTER_WORDS = ("shutters", "shutter", "doors", "door", "palle", "palla", "शटर", "दरवाज़े", "दरवाजे")


def _board_needs(a: dict, use: str, area, wastage: float, *, back_area=None) -> list[Need]:
    board, thickness = a.get("board") or "plywood", str(a.get("board_mm") or "18")
    sheets = F.board_sheets(area.amount, wastage)
    label = {"plywood": t("Plywood sheets (8 × 4 ft)", "प्लाईवुड शीट (8 × 4 फ़ुट)", "Plywood sheet (8 × 4 ft)"),
             "hdhmr": t("HDHMR boards (8 × 4 ft)", "HDHMR बोर्ड (8 × 4 फ़ुट)", "HDHMR board (8 × 4 ft)"),
             "mdf": t("MDF boards (8 × 4 ft)", "MDF बोर्ड (8 × 4 फ़ुट)", "MDF board (8 × 4 ft)")}[board]
    reason = (t("BWP (boiling-water-proof) ply is the usual choice near a sink and stove.", "सिंक और चूल्हे के पास BWP (पानी-रोधी) प्लाई सही रहती है।", "Sink aur chulhe ke paas BWP (paani-rodhi) ply sahi rehti hai.")
              if use == "kitchen" and board == "plywood" else
              t("Cut into side panels, shelves and shutters.", "साइड पैनल, शेल्फ और शटर इसी से कटेंगे।", "Side panel, shelf aur shutter isi se katenge."))
    needs = [Need("board", label, BOARD_SEARCH[board][use], sheets.amount, "pcs", reason, hint=f"{thickness} mm", steps=tuple(area.steps + sheets.steps))]
    if back_area is not None:
        backs = F.board_sheets(back_area.amount, wastage)
        needs.append(Need("back_panel", t("6 mm ply for the back panels", "पीछे के पैनल के लिए 6 मिमी प्लाई", "Peeche ke panel ke liye 6 mm ply"),
                          ("plywood",), backs.amount, "pcs", t("Thin sheet that closes the back of each cabinet.", "हर कैबिनेट का पिछला हिस्सा बंद करने के लिए पतली शीट।", "Har cabinet ka peecha band karne ke liye patli sheet."),
                          optional=True, hint="6 mm", steps=tuple(back_area.steps + backs.steps)))
    return needs


def _hinge_needs(shutters: int, height_mm: float, board_mm: float, *, hint: str = "") -> list[Need]:
    hinges = F.hinges(shutters, height_mm)
    return [Need("hinges", t("Concealed (auto) hinges", "कंसील्ड (ऑटो) कब्ज़े", "Concealed (auto) kabze"), ("concealed hinge", "soft close hinge", "hinge"), hinges.amount, "pcs",
                 t("Chosen for your shutter thickness; the number per shutter goes by its height.", "शटर की मोटाई के हिसाब से; हर शटर पर संख्या उसकी ऊँचाई से तय।", "Shutter ki motai ke hisaab se; har shutter par ginti uski unchai se tay."),
                 hint=hint, steps=tuple(hinges.steps), fit=(("board_mm", board_mm),), avoid=("glass", "butt"))]


def _channel_needs(drawers: int, depth_mm: float) -> list[Need]:
    if drawers <= 0:
        return []
    pairs = F.channels(drawers)
    return [Need("channels", t("Telescopic drawer channels", "टेलीस्कोपिक दराज़ चैनल", "Telescopic daraz channel"), ("telescopic channel", "drawer channel"), pairs.amount, "pcs",
                 t("One pair per drawer, the longest length that fits the cabinet depth.", "हर दराज़ के लिए एक जोड़ी, कैबिनेट की गहराई में आने वाली सबसे लंबी।", "Har daraz ke liye ek jodi, cabinet ki gehrai mein aane wali sabse lambi."),
                 steps=tuple(pairs.steps), fit=(("depth_mm", depth_mm),))]


def _handle_need(shutters: int, drawers: int) -> Need:
    count = F.handles(shutters, drawers)
    return Need("handles", t("Cabinet handles", "कैबिनेट हैंडल", "Cabinet handle"), ("cabinet handle", "handle"), count.amount, "pcs",
                t("One per shutter and drawer.", "हर शटर और दराज़ पर एक।", "Har shutter aur daraz par ek."), estimate=False, steps=tuple(count.steps),
                avoid=("lock", "glass", "hammer", "door"))


def _screw_need(parts: list) -> Need:
    total = sum(int(p.amount) for p in parts)
    steps = tuple(step for p in parts for step in p.steps) + ((t("Screws", "स्क्रू", "Screw"), f"{total}"),)
    return Need("screws", t("Wood screws", "लकड़ी के स्क्रू", "Wood screw (pench)"), ("wood screws", "screws"), total, "pcs",
                t("For the carcass joints, hinges and channels; the hinge plates take short screws that stay inside the board.", "ढांचे के जोड़, कब्ज़ों और चैनल के लिए; कब्ज़े की प्लेट में छोटे स्क्रू लगते हैं जो बोर्ड से बाहर न निकलें।",
                  "Dhaanche ke jod, kabze aur channel ke liye; kabze ki plate mein chhote screw lagte hain jo board se bahar na niklein."), steps=steps)


def _finishing_needs(edge) -> list[Need]:
    return [
        Need("edge_band", t("Edge band tape", "एज बैंड टेप", "Edge band tape"), ("edge band", "edge banding tape"), edge.amount, "m",
             t("Covers the cut edges of shutters and panels.", "शटर और पैनल के कटे किनारे ढकने के लिए।", "Shutter aur panel ke kate kinare dhakne ke liye."), steps=tuple(edge.steps)),
        Need("wood_adhesive", t("Wood adhesive (Fevicol)", "लकड़ी का गोंद (फेविकोल)", "Wood adhesive (Fevicol)"), ("wood adhesive",), 1, "pcs",
             t("For the joints and the edge band.", "जोड़ और एज बैंड के लिए।", "Jod aur edge band ke liye."), estimate=False),
    ]


def _kitchen(a: dict) -> list[Need]:
    cabinets, shutters, drawers = int(a["cabinets"]), int(a["shutters"]), int(a.get("drawers") or 0)
    width, height, depth = F.KITCHEN_CABINET_MM
    shutter_h = float(a.get("shutter_height") or height)
    board_mm = float(a.get("board_mm") or 18)
    shutter_w = cabinets * width / max(1, shutters)
    pieces = [
        ("Side panels", 2 * cabinets, depth, height), ("Top and bottom", 2 * cabinets, width, depth), ("Shelves", cabinets, width, depth),
        ("Shutters", shutters, shutter_w, shutter_h), ("Drawer fronts", drawers, width, 180), ("Drawer boxes", 2 * drawers, depth + width, 150),
    ]  # fmt: skip
    area = F.panel_area(pieces)
    backs = F.panel_area([("Back panels", cabinets, width, height)])
    edge = F.edge_band([("Shutters", shutters, shutter_w, shutter_h), ("Drawer fronts", drawers, width, 180)])
    carcass_edge = F.edge_band([("Front edges", 2 * cabinets, height, 0), ("Front edges", 3 * cabinets, width, 0)], all_sides=False)
    edge = F.Estimate(edge.amount + carcass_edge.amount, "m", edge.steps + carcass_edge.steps)
    hinge_count = int(F.hinges(shutters, shutter_h).amount)
    needs = _board_needs(a, "kitchen", area, float(a.get("wastage", F.BOARD_WASTAGE_PCT)), back_area=backs)
    needs += _hinge_needs(shutters, shutter_h, board_mm)
    needs += _channel_needs(drawers, float(a.get("cabinet_depth") or depth - 20))
    needs.append(_handle_need(shutters, drawers))
    needs.append(_screw_need([F.carcass_screws(cabinets), F.hinge_screws(hinge_count), F.channel_screws(drawers)]))
    needs += _finishing_needs(edge)
    needs.append(Need("basket", t("Cutlery basket", "कटलरी बास्केट", "Cutlery basket"), ("cutlery basket", "kitchen basket"), 1, "pcs",
                      t("Fits a drawer cabinet; pick the size of your cabinet.", "दराज़ वाले कैबिनेट में; अपने कैबिनेट का साइज़ चुनें।", "Daraz wale cabinet mein; apne cabinet ka size chunein."), optional=True, estimate=False))
    return needs


KITCHEN = ProjectTemplate(
    key="modular_kitchen",
    name=t("Modular kitchen (carcass)", "मॉड्यूलर किचन (ढांचा)", "Modular kitchen (dhaancha)"),
    patterns=(r"modular\s+kitchen", r"kitchen\s+(cabinets?|shutters?|carcass|units?|trolley|banan|banwa)", r"\bcarcass", r"kitchen.*\b(ply\w*|plai|hdhmr|hinges?|kabz\w*|channels?)\b",
              r"मॉड्यूलर\s+किचन", r"किचन\s+(कैबिनेट|शटर)", r"\bkitchen\b"),
    summary=t("Boards by the sheet from the panel areas, hinges by shutter height, a pair of channels per drawer, a handle per shutter and drawer, and screws for all of it.",
              "पैनल के क्षेत्रफल से शीट, शटर की ऊँचाई से कब्ज़े, हर दराज़ पर चैनल की जोड़ी, हर शटर और दराज़ पर हैंडल, और सबके स्क्रू।",
              "Panel ke area se sheet, shutter ki unchai se kabze, har daraz par channel ki jodi, har shutter aur daraz par handle, aur sabke screw."),
    questions=(
        Question("cabinets", "number", t("How many cabinets (boxes)?", "कितने कैबिनेट (डिब्बे)?", "Kitne cabinet (dabbe)?"), unit="cabinets", maximum=60,
                 count_words=("cabinets", "cabinet", "units", "unit", "boxes", "box", "carcass", "कैबिनेट")),
        Question("shutters", "number", t("How many shutters (doors)?", "कितने शटर (दरवाज़े)?", "Kitne shutter (palle)?"), unit="shutters", maximum=120, count_words=SHUTTER_WORDS),
        DRAWERS,
        Question("shutter_height", "number", t("Shutter height (mm)", "शटर की ऊँचाई (मिमी)", "Shutter ki unchai (mm)"), unit="mm", minimum=200, maximum=2400, default=720),
        Question("cabinet_depth", "number", t("Inside depth of the drawer cabinets (mm)", "दराज़ वाले कैबिनेट की अंदर की गहराई (मिमी)", "Daraz wale cabinet ki andar ki gehrai (mm)"),
                 unit="mm", minimum=250, maximum=800, default=540, when=lambda a: float(a.get("drawers") or 0) > 0),
        BOARD, BOARD_MM, _wastage(F.BOARD_WASTAGE_PCT),
    ),  # fmt: skip
    materials=_kitchen,
    caution=t("Cabinet sizes are taken as standard 600 × 720 × 560 mm boxes; a carpenter's cutting list is more exact.", "कैबिनेट का साइज़ 600 × 720 × 560 मिमी माना गया है; कारपेंटर की कटिंग लिस्ट ज़्यादा सटीक होगी।",
              "Cabinet ka size 600 × 720 × 560 mm maana gaya hai; carpenter ki cutting list zyada sahi hogi."),
    title=lambda a, lang: f"{say(t('Kitchen', 'किचन', 'Kitchen'), lang)} · {_n(a.get('cabinets'))} × {_n(a.get('shutters'))}",
    examples=("Modular kitchen with 6 cabinets, 8 shutters and 3 drawers", "kitchen ke 5 cabinet 18 mm plai se banane hain"),
)


def _wardrobe(a: dict) -> list[Need]:
    width, height, depth = float(a["width"]) * MM_PER_FT, float(a.get("height") or 7) * MM_PER_FT, float(a.get("depth") or 2) * MM_PER_FT
    shutters, drawers, shelves = int(a["shutters"]), int(a.get("drawers") or 0), int(a.get("shelves") or 0)
    board_mm, sliding = float(a.get("board_mm") or 18), a.get("door_type") == "sliding"
    shutter_w = width / max(1, shutters)
    pieces = [("Side panels", 2, depth, height), ("Top and bottom", 2, width, depth), ("Shelves", shelves, width, depth),
              ("Shutters", shutters, shutter_w, height), ("Drawer fronts", drawers, width / 2, 200)]  # fmt: skip
    area = F.panel_area(pieces)
    edge = F.edge_band([("Shutters", shutters, shutter_w, height), ("Drawer fronts", drawers, width / 2, 200)])
    needs = _board_needs(a, "wardrobe", area, float(a.get("wastage", F.BOARD_WASTAGE_PCT)), back_area=F.panel_area([("Back panel", 1, width, height)]))
    screws = [F.carcass_screws(1), F.channel_screws(drawers)]
    if sliding:
        needs.append(Need("sliding_set", t("Sliding door fitting set", "स्लाइडिंग दरवाज़े का फ़िटिंग सेट", "Sliding door fitting set"), ("sliding wardrobe door fitting", "sliding fitting"),
                          math.ceil(shutters / 2), "pcs", t("One set runs two sliding shutters.", "एक सेट दो स्लाइडिंग शटर चलाता है।", "Ek set do sliding shutter chalata hai."), estimate=False))
    else:
        needs += _hinge_needs(shutters, height, board_mm)
        screws.append(F.hinge_screws(int(F.hinges(shutters, height).amount)))
    rails = F.wardrobe_rails(width)
    needs.append(Need("rail", t("Hanging rail", "कपड़े टांगने की रॉड", "Kapde taangne ki rod"), ("wardrobe rail", "hanger rod"), rails.amount, "pcs",
                      t("One per 4 ft of width.", "हर 4 फ़ुट चौड़ाई पर एक।", "Har 4 ft chaudai par ek."), steps=tuple(rails.steps)))
    needs += _channel_needs(drawers, depth - 2 * board_mm)
    needs.append(_handle_need(shutters, drawers))
    needs.append(_screw_need(screws))
    needs += _finishing_needs(edge)
    return needs


WARDROBE = ProjectTemplate(
    key="wardrobe",
    name=t("Wardrobe", "अलमारी (वॉर्डरोब)", "Wardrobe / almari"),
    patterns=(r"wardrobe", r"\balmari\b", r"\balmaari\b", r"\balmirah\b", r"\balmira\b", r"अलमारी", r"\bcloset\b", r"sliding\s+(door|shutter)s?", r"\bshutters?\b", r"hanging\s+rail"),
    summary=t("Boards by the sheet from the panel areas, hinges by shutter height (or a sliding set), a hanging rail per 4 ft, channels per drawer and a handle per shutter.",
              "पैनल के क्षेत्रफल से शीट, शटर की ऊँचाई से कब्ज़े (या स्लाइडिंग सेट), हर 4 फ़ुट पर रॉड, हर दराज़ पर चैनल और हर शटर पर हैंडल।",
              "Panel ke area se sheet, shutter ki unchai se kabze (ya sliding set), har 4 ft par rod, har daraz par channel aur har shutter par handle."),
    questions=(
        Question("width", "number", t("How wide is the wardrobe (feet)?", "अलमारी कितनी चौड़ी है (फ़ुट)?", "Almari kitni chaudi hai (feet)?"), unit="ft", maximum=20,
                 count_words=("ft wide", "feet wide", "foot wide", "ft", "feet", "foot", "फ़ुट", "फुट")),
        Question("height", "number", t("Height (feet)", "ऊँचाई (फ़ुट)", "Unchai (feet)"), unit="ft", minimum=2, maximum=10, default=7),
        Question("depth", "number", t("Depth (feet)", "गहराई (फ़ुट)", "Gehrai (feet)"), unit="ft", minimum=1, maximum=4, default=2),
        Question("shutters", "number", t("How many shutters (doors)?", "कितने शटर (दरवाज़े)?", "Kitne shutter (palle)?"), unit="shutters", maximum=12, count_words=SHUTTER_WORDS),
        Question("door_type", "choice", t("Hinged or sliding shutters?", "कब्ज़े वाले या स्लाइडिंग शटर?", "Kabze wale ya sliding shutter?"),
                 choices=(Choice("hinged", t("Hinged", "कब्ज़े वाले", "Kabze wale"), (r"hinged", r"\bkabz", r"\bkabj")), Choice("sliding", t("Sliding", "स्लाइडिंग", "Sliding"), (r"slid",))), default="hinged"),
        Question("shelves", "number", t("How many shelves?", "कितनी शेल्फ?", "Kitni shelf?"), unit="shelves", minimum=0, maximum=30, default=4, count_words=("shelves", "shelf", "khane", "खाने")),
        DRAWERS, BOARD, BOARD_MM, _wastage(F.BOARD_WASTAGE_PCT),
    ),  # fmt: skip
    materials=_wardrobe,
    title=lambda a, lang: f"{say(t('Wardrobe', 'अलमारी', 'Wardrobe'), lang)} · {_n(a.get('width'))} ft",
    examples=("6 ft wardrobe with 3 shutters and 2 drawers", "4 feet ki almari, 2 palle, sliding"),
)


def _door(a: dict) -> list[Need]:
    doors, door_mm = int(a.get("doors") or 1), float(a.get("door_mm") or 35)
    lock = a["lock_type"]
    search = ("mortise lock", "door lock") if lock == "mortise" else ("knob lock", "cylindrical lock", "door lock")
    needs = [Need("lock", t("Mortise lock with handles" if lock == "mortise" else "Knob lock", "मॉर्टिस ताला हैंडल के साथ" if lock == "mortise" else "नॉब ताला",
                            "Mortise taala handle ke saath" if lock == "mortise" else "Knob taala"), search, doors, "pcs",
                  t("One per door, chosen for your door's thickness.", "हर दरवाज़े पर एक, दरवाज़े की मोटाई के हिसाब से।", "Har darwaze par ek, darwaze ki motai ke hisaab se."),
                  estimate=False, fit=(("door_mm", door_mm),), avoid=("glass", "padlock"))]
    if a.get("job") == "door":
        height = float(a.get("door_height") or 2100)
        hinges = F.hinges(doors, height)
        screws = F.hinge_screws(int(hinges.amount), F.SCREWS_PER_BUTT_HINGE)
        needs += [
            Need("hinges", t("Butt hinges", "दरवाज़े के कब्ज़े (बट हिंज)", "Darwaze ke kabze (butt hinge)"), ("butt hinge", "door hinge"), hinges.amount, "pcs",
                 t("The number per door goes by its height.", "हर दरवाज़े पर संख्या उसकी ऊँचाई से।", "Har darwaze par ginti uski unchai se."), steps=tuple(hinges.steps), avoid=("glass", "concealed")),
            Need("screws", t("Wood screws", "लकड़ी के स्क्रू", "Wood screw (pench)"), ("wood screws", "screws"), screws.amount, "pcs",
                 t("Three per hinge leaf, into the frame and the door.", "हर पत्ती में तीन, चौखट और दरवाज़े में।", "Har patti mein teen, chaukhat aur darwaze mein."), steps=tuple(screws.steps)),
        ]
    needs += [
        Need("tower_bolt", t("Tower bolt", "चिटकनी (टावर बोल्ट)", "Chitkani (tower bolt)"), ("tower bolt",), doors, "pcs",
             t("Bolts the door from inside.", "अंदर से दरवाज़ा बंद करने के लिए।", "Andar se darwaza band karne ke liye."), optional=True, estimate=False),
        Need("closer", t("Door closer", "डोर क्लोज़र", "Door closer"), ("door closer",), doors, "pcs",
             t("Closes the door gently by itself.", "दरवाज़ा अपने आप धीरे से बंद करता है।", "Darwaza apne aap dheere se band karta hai."), optional=True, estimate=False, avoid=("glass", "floor")),
    ]
    return needs


DOOR = ProjectTemplate(
    key="door_lock",
    name=t("Door and lock fitting", "दरवाज़ा और ताला फ़िटिंग", "Darwaza aur taala fitting"),
    patterns=(r"\blocks?\b", r"mortise", r"\btaala\b", r"\btala\b", r"ताला", r"\bdoor\b", r"darwaz", r"दरवाज़", r"दरवाज", r"chitkani|tower\s+bolt", r"door\s+closer"),
    summary=t("A lock per door that suits the door's thickness; a new door also needs hinges by its height and their screws.",
              "हर दरवाज़े पर उसकी मोटाई के हिसाब से ताला; नए दरवाज़े पर ऊँचाई के हिसाब से कब्ज़े और उनके स्क्रू भी।",
              "Har darwaze par uski motai ke hisaab se taala; naye darwaze par unchai ke hisaab se kabze aur unke screw bhi."),
    questions=(
        Question("job", "choice", t("What do you want to fit?", "क्या लगाना है?", "Kya lagana hai?"),
                 choices=(Choice("lock", t("A lock on an existing door", "पुराने दरवाज़े पर ताला", "Purane darwaze par taala"), (r"\b(change|replace|new)\s+(the\s+)?lock", r"\bfit\w*\s+(an?\s+)?(\w+\s+)?lock", r"lock\s+(change|badal)", r"taala\s+(badal|lagana)")),
                          Choice("door", t("Hang a new door with hinges and a lock", "नया दरवाज़ा कब्ज़ों और ताले के साथ", "Naya darwaza kabze aur taale ke saath"), (r"new\s+door", r"hang\w*\s+(a\s+)?door", r"naya\s+darwaza", r"नया\s+दरवाज़ा")))),
        Question("doors", "number", t("How many doors?", "कितने दरवाज़े?", "Kitne darwaze?"), unit="doors", maximum=50, default=1, count_words=("doors", "door", "darwaze", "darwaza", "दरवाज़े")),
        Question("lock_type", "choice", t("Which lock?", "कौन सा ताला?", "Kaun sa taala?"),
                 choices=(Choice("mortise", t("Mortise lock with handles (main door)", "मॉर्टिस ताला हैंडल के साथ (मुख्य दरवाज़ा)", "Mortise taala handle ke saath (main door)"), (r"mortise", r"mortice", r"main\s+door", r"lever")),
                          Choice("knob", t("Knob lock (bedroom, bathroom)", "नॉब ताला (बेडरूम, बाथरूम)", "Knob taala (bedroom, bathroom)"), (r"\bknob", r"bedroom", r"bathroom", r"cylindrical")))),
        Question("door_mm", "number", t("Door thickness (mm)", "दरवाज़े की मोटाई (मिमी)", "Darwaze ki motai (mm)"), unit="mm", minimum=20, maximum=80, default=35),
        Question("door_height", "number", t("Door height (mm)", "दरवाज़े की ऊँचाई (मिमी)", "Darwaze ki unchai (mm)"), unit="mm", minimum=600, maximum=3000, default=2100, when=lambda a: a.get("job") == "door"),
    ),  # fmt: skip
    materials=_door,
    not_sold=t("Door shutters and frames are made to size by a carpenter or door supplier; we sell the hardware.", "दरवाज़े और चौखट कारपेंटर या डोर सप्लायर नाप से बनाते हैं; हम हार्डवेयर बेचते हैं।",
               "Darwaze aur chaukhat carpenter ya door supplier naap se banate hain; hum hardware bechte hain."),
    title=lambda a, lang: f"{say(t('Door', 'दरवाज़ा', 'Darwaza'), lang)} · {_n(a.get('doors'))}",
    examples=("Fit a mortise lock on 2 doors", "naya darwaza lagana hai, taala aur kabze chahiye"),
)


def _glass_door(a: dict) -> list[Need]:
    doors, panels, glass_mm = int(a.get("doors") or 0), int(a.get("panels") or 0), float(a["glass_mm"])
    fit = (("glass_mm", glass_mm),)
    needs = []
    if doors:
        needs += [
            Need("patch", t("Patch fitting set", "पैच फ़िटिंग सेट", "Patch fitting set"), ("patch fitting",), doors, "pcs",
                 t("Top and bottom patches hold the glass door; chosen for your glass thickness.", "ऊपर-नीचे के पैच कांच का दरवाज़ा पकड़ते हैं; कांच की मोटाई के हिसाब से।", "Upar-neeche ke patch kaanch ka darwaza pakadte hain; kaanch ki motai ke hisaab se."), estimate=False, fit=fit),
            Need("floor_spring", t("Floor spring", "फ़्लोर स्प्रिंग", "Floor spring"), ("floor spring",), doors, "pcs",
                 t("Carries the door and closes it; check it is rated for the door's weight.", "दरवाज़े का वज़न उठाता और बंद करता है; वज़न की क्षमता देख लें।", "Darwaze ka wazan uthata aur band karta hai; wazan ki capacity dekh lein."), estimate=False, fit=fit),
            Need("pull_handle", t("Glass door pull handle", "कांच के दरवाज़े का हैंडल", "Kaanch ke darwaze ka handle"), ("glass door handle", "pull handle"), doors, "pcs",
                 t("Back-to-back handle through the glass.", "कांच के आर-पार दोनों तरफ़ का हैंडल।", "Kaanch ke aar-paar dono taraf ka handle."), estimate=False, fit=fit),
        ]
    if panels:
        clamps = F.glass_clamps(panels)
        needs.append(Need("clamps", t("Glass clamps", "ग्लास क्लैंप", "Glass clamp"), ("glass clamp", "glass connector"), clamps.amount, "pcs",
                          t("Hold the fixed panels to the floor and wall.", "स्थिर पैनल को फ़र्श और दीवार से पकड़ते हैं।", "Fixed panel ko farsh aur deewar se pakadte hain."), steps=tuple(clamps.steps), fit=fit))
    tubes = F.sealant_tubes(doors + panels)
    needs.append(Need("sealant", t("Clear silicone sealant", "पारदर्शी सिलिकॉन सीलेंट", "Clear silicone sealant"), ("silicone sealant", "sealant"), tubes.amount, "pcs",
                      t("Seals the edges of the fixed glass.", "स्थिर कांच के किनारे सील करता है।", "Fixed kaanch ke kinare seal karta hai."), optional=not panels, steps=tuple(tubes.steps)))
    return needs


GLASS_DOOR = ProjectTemplate(
    key="glass_door",
    name=t("Glass door / partition", "कांच का दरवाज़ा / पार्टीशन", "Kaanch ka darwaza / partition"),
    patterns=(r"glass\s+(door|partition|cabin|enclosure)", r"\b(kanch|kaanch)\b", r"काँच|कांच", r"patch\s+fitting", r"floor\s+spring", r"toughened", r"shower\s+(partition|enclosure)"),
    summary=t("Per glass door a patch fitting set, a floor spring and a pull handle that take your glass thickness; fixed panels need clamps and sealant.",
              "हर कांच के दरवाज़े पर पैच फ़िटिंग सेट, फ़्लोर स्प्रिंग और हैंडल जो आपके कांच की मोटाई लें; स्थिर पैनल पर क्लैंप और सीलेंट।",
              "Har kaanch ke darwaze par patch fitting set, floor spring aur handle jo aapke kaanch ki motai lein; fixed panel par clamp aur sealant."),
    questions=(
        Question("doors", "number", t("How many glass doors (that open)?", "कितने खुलने वाले कांच के दरवाज़े?", "Kitne khulne wale kaanch ke darwaze?"), unit="doors", minimum=0, maximum=20, default=1,
                 count_words=("doors", "door", "darwaze", "darwaza", "दरवाज़े")),
        Question("panels", "number", t("How many fixed glass panels?", "कितने स्थिर कांच पैनल?", "Kitne fixed kaanch panel?"), unit="panels", minimum=0, maximum=40, default=0, count_words=("panels", "panel", "fixed")),
        Question("glass_mm", "choice", t("Glass thickness", "कांच की मोटाई", "Kaanch ki motai"), choices=tuple(_mm_choice(v) for v in ("12", "10", "8"))),
    ),  # fmt: skip
    materials=_glass_door,
    not_sold=t("Toughened glass is cut and toughened to size by a glass supplier; we sell the fittings.", "टफ़न कांच ग्लास सप्लायर नाप से काटकर बनाते हैं; हम फ़िटिंग बेचते हैं।",
               "Toughened kaanch glass supplier naap se kaat kar banate hain; hum fitting bechte hain."),
    caution=t("Toughened glass can't be cut or drilled after toughening: give the fitting positions to the glass supplier first.", "टफ़न होने के बाद कांच न काटा जा सकता है न छेदा: फ़िटिंग की जगह पहले ग्लास सप्लायर को बताएँ।",
              "Toughen hone ke baad kaanch na kaata ja sakta hai na chheda: fitting ki jagah pehle glass supplier ko batayein."),
    professional=lambda a: True,
    risky=True,
    title=lambda a, lang: f"{say(t('Glass door', 'कांच का दरवाज़ा', 'Glass door'), lang)} · {_n(a.get('glass_mm'))} mm",
    examples=("Glass door with 10 mm toughened glass", "office glass partition: 1 door and 2 fixed panels, 12 mm"),
)


def _infer_replacement(answers: dict, text: str) -> None:
    """ "18 inch channel" / "450 mm" → the old channel's length (converted by the question); "160 mm handle" → the
    handles' hole distance. Only a size written next to its unit counts."""
    import re

    size = re.search(r"(\d+(?:\.\d+)?)\s*(mm|inch(?:es)?|in\b|\"|”|इंच|मिमी)", text, re.IGNORECASE)
    if not size:
        return
    unit = {"\"": "inch", "”": "inch", "in": "inch", "इंच": "inch", "मिमी": "mm"}.get(size.group(2).lower(), size.group(2).lower())
    value = {"value": float(size.group(1)), "unit": "inch" if unit.startswith("inch") else unit}
    if answers.get("part") == "channel":
        answers.setdefault("channel_length", value)
    elif answers.get("part") == "handle" and value["unit"] == "mm":
        answers.setdefault("cc_mm", value)


def _replacement(a: dict) -> list[Need]:
    part, count = a["part"], int(a["count"])
    if part == "hinge":
        overlay = a.get("overlay") or "full"
        steps = ((t("Hinges", "कब्ज़े", "Kabze"), f"{count}"),)
        return [
            Need("hinges", t(f"Concealed hinges, {overlay} overlay", f"कंसील्ड कब्ज़े, {overlay} ओवरले", f"Concealed kabze, {overlay} overlay"), ("concealed hinge", "hinge"), count, "pcs",
                 t("Same overlay as the old ones, for your shutter thickness.", "पुराने जैसा ओवरले, आपके शटर की मोटाई के हिसाब से।", "Purane jaisa overlay, aapke shutter ki motai ke hisaab se."),
                 estimate=False, hint=f"{overlay} overlay", steps=steps, fit=(("board_mm", float(a.get("board_mm") or 18)),), avoid=("glass", "butt")),
            Need("screws", t("Wood screws", "लकड़ी के स्क्रू", "Wood screw (pench)"), ("wood screws", "screws"), count * F.SCREWS_PER_CONCEALED_HINGE, "pcs",
                 t("If the old screws are worn.", "अगर पुराने स्क्रू घिस गए हों।", "Agar purane screw ghis gaye hon."), optional=True, estimate=False),
        ]
    if part == "channel":
        length = float(a["channel_length"])
        return [Need("channels", t("Telescopic drawer channels", "टेलीस्कोपिक दराज़ चैनल", "Telescopic daraz channel"), ("telescopic channel", "drawer channel"), count * 2, "pcs",
                     t("The same length as the old pair.", "पुरानी जोड़ी जितनी लंबाई।", "Purani jodi jitni lambai."), estimate=False,
                     steps=((t("Pairs", "जोड़ी", "Jodi"), f"{count} × 2 = {count * 2} channels"),), fit=(("depth_mm", length + CHANNEL_REAR_CLEARANCE_MM),))]
    cc = a.get("cc_mm")
    return [Need("handles", t("Cabinet handles", "कैबिनेट हैंडल", "Cabinet handle"), ("cabinet handle", "handle"), count, "pcs",
                 t("The same centre-to-centre distance uses the old holes.", "वही सेंटर-टू-सेंटर दूरी हो तो पुराने छेद काम आते हैं।", "Wahi centre-to-centre doori ho to purane chhed kaam aate hain."),
                 estimate=False, hint=f"{_n(cc)} mm" if cc else "", avoid=("lock", "glass", "hammer", "door"))]


REPLACEMENT = ProjectTemplate(
    key="hinge_replacement",
    name=t("Hinge, channel or handle replacement", "कब्ज़ा, चैनल या हैंडल बदलना", "Kabza, channel ya handle badalna"),
    patterns=(r"(replac\w*|badal\w*|change|kharab|toot\w*|broken|loose|dheel\w*|ढीले|टूट|बदल).*\b(hinges?|kabz\w*|kabj\w*|channels?|handles?|handal)\b",
              r"\b(hinges?|kabz\w*|kabj\w*|channels?|handles?|handal)\b.*(replac\w*|badal\w*|change|kharab|toot\w*|broken|loose|dheel\w*|ढीले|टूट|बदल)",
              r"\b(hinges?|kabz\w*|kabj\w*)\b", r"कब्ज़?", r"\b(drawer|telescopic)\s+channels?\b|\bdaraa?z\b"),
    summary=t("A replacement fits the old holes: hinges with the same overlay, channels of the same length, handles with the same centre-to-centre distance.",
              "नया पुराने छेदों में बैठे: वही ओवरले वाले कब्ज़े, उतनी ही लंबाई के चैनल, उतनी ही सेंटर-टू-सेंटर दूरी वाले हैंडल।",
              "Naya purane chhedon mein baithe: wahi overlay wale kabze, utni hi lambai ke channel, utni hi centre-to-centre doori wale handle."),
    questions=(
        Question("part", "choice", t("What needs replacing?", "क्या बदलना है?", "Kya badalna hai?"),
                 choices=(Choice("hinge", t("Hinges", "कब्ज़े", "Kabze"), (r"hinge", r"kabz", r"kabj", r"कब्ज")),
                          Choice("channel", t("Drawer channels", "दराज़ चैनल", "Daraz channel"), (r"channel", r"slide", r"daraa?z", r"drawer", r"दराज")),
                          Choice("handle", t("Handles", "हैंडल", "Handle"), (r"handle", r"handal", r"hendal", r"knob", r"हैंडल")))),
        Question("count", "number", t("How many (hinges / channel pairs / handles)?", "कितने (कब्ज़े / चैनल की जोड़ी / हैंडल)?", "Kitne (kabze / channel ki jodi / handle)?"), unit="pcs", maximum=200,
                 count_words=("hinges", "hinge", "kabze", "kabza", "kabje", "kabja", "pairs", "pair", "jodi", "channels", "channel", "handles", "handle", "pcs", "pieces", "कब्ज़े")),
        Question("overlay", "choice", t("How does the shutter sit on the cabinet side?", "शटर कैबिनेट की साइड पर कैसे बैठता है?", "Shutter cabinet ki side par kaise baithta hai?"),
                 choices=(Choice("full", t("Full overlay: covers the whole side", "फ़ुल ओवरले: पूरी साइड ढकता है", "Full overlay: poori side dhakta hai"), (r"full\s+overlay", r"\bfull\b")),
                          Choice("half", t("Half overlay: two shutters share a side", "हाफ़ ओवरले: दो शटर एक साइड पर", "Half overlay: do shutter ek side par"), (r"half\s+overlay", r"\bhalf\b")),
                          Choice("inset", t("Inset: sits inside the opening", "इनसेट: खुले हिस्से के अंदर", "Inset: andar baithta hai"), (r"\binset\b",))),
                 when=lambda a: a.get("part") == "hinge"),
        Question(BOARD_MM.key, BOARD_MM.kind, t("Shutter thickness", "शटर की मोटाई", "Shutter ki motai"), BOARD_MM.choices, default="18", when=lambda a: a.get("part") == "hinge"),
        Question("channel_length", "number", t("Length of the old channel (mm or inch)", "पुराने चैनल की लंबाई (मिमी या इंच)", "Purane channel ki lambai (mm ya inch)"), unit="mm", minimum=150, maximum=1000,
                 when=lambda a: a.get("part") == "channel"),
        Question("cc_mm", "number", t("Distance between the old handle's two holes (mm)", "पुराने हैंडल के दो छेदों की दूरी (मिमी)", "Purane handle ke do chhedon ki doori (mm)"), unit="mm", minimum=16, maximum=1200,
                 when=lambda a: a.get("part") == "handle"),
    ),  # fmt: skip
    materials=_replacement,
    infer=_infer_replacement,
    title=lambda a, lang: f"{say(t('Replacement', 'बदलना', 'Replacement'), lang)} · {_n(a.get('count'))} {a.get('part') or ''}".strip(),
    examples=("Replace 4 soft close hinges, full overlay", "2 jodi daraz channel badalne hain, 18 inch"),
)


def _n(value) -> str:
    if value is None:
        return "?"
    value = float(value)
    return str(int(value)) if value == int(value) else f"{value:g}"


# Order matters for ties: more specific jobs first.
TEMPLATES: dict[str, ProjectTemplate] = {
    tpl.key: tpl
    for tpl in (WATERPROOFING, TILING, PAINTING, ELECTRICAL, PLUMBING, BATHROOM, WALL_DRILLING, KITCHEN, GLASS_DOOR, REPLACEMENT,
                FURNITURE, WARDROBE, DOOR, CONSTRUCTION)
}  # fmt: skip
# Quantity AI (Phase 20): calculators for one requirement ("500 sq ft plastering", "100 feet of wire").
# Painting, tiling and waterproofing are the same templates as the project builder's.
CALCULATORS: dict[str, ProjectTemplate] = {
    tpl.key: tpl
    for tpl in (WATERPROOFING, FLOORING, TILING, PLASTERING, PAINTING, WIRING, PIPES, FASTENERS)
}
ALL_TEMPLATES: dict[str, ProjectTemplate] = {**TEMPLATES, **CALCULATORS}
