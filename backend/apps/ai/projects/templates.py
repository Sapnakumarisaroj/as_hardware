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


def _n(value) -> str:
    if value is None:
        return "?"
    value = float(value)
    return str(int(value)) if value == int(value) else f"{value:g}"


# Order matters for ties: more specific jobs first.
TEMPLATES: dict[str, ProjectTemplate] = {
    tpl.key: tpl
    for tpl in (WATERPROOFING, TILING, PAINTING, ELECTRICAL, PLUMBING, BATHROOM, WALL_DRILLING, FURNITURE, CONSTRUCTION)
}
# Quantity AI (Phase 20): calculators for one requirement ("500 sq ft plastering", "100 feet of wire").
# Painting, tiling and waterproofing are the same templates as the project builder's.
CALCULATORS: dict[str, ProjectTemplate] = {
    tpl.key: tpl
    for tpl in (WATERPROOFING, FLOORING, TILING, PLASTERING, PAINTING, WIRING, PIPES, FASTENERS)
}
ALL_TEMPLATES: dict[str, ProjectTemplate] = {**TEMPLATES, **CALCULATORS}
