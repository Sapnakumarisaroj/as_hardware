# ruff: noqa: E501 — pattern tables read better on one line
"""Customer words → catalogue words.

"machine for drilling concrete" contains no product name, but it *means* a drill and masonry bits.
Two sources, both plain data (no model, no network), so this also works when the AI parts are off:

- the assistant's vocabulary (English, Hindi in Devanagari, Hinglish phrases and jobs), reused as is;
- SYNONYMS below: everyday descriptions of what a product does.

The result is only a list of *words to search the catalogue with*. Which products exist, their prices
and their stock are decided by the database, never by these tables.
"""

import difflib
import re
from dataclasses import dataclass, field

from apps.ai.services import vocabulary as V

# (pattern, catalogue words). Patterns are matched against the lower-cased query.
SYNONYMS: list[tuple[str, tuple[str, ...]]] = [
    # drilling and fixing to walls
    (r"\b(hole|holes|drill\w*|bore|boring|chhed|ched|barma)\b|छेद|सुराख़?|ड्रिल", ("drill", "drill bit")),
    (
        r"\b(concrete|masonry|brick|cement wall|diwar|deewar|deevar|dewar|wall)\b.*\b(hole|drill\w*|karne|karna|bore)\b|\b(hole|drill\w*)\b.*\b(concrete|masonry|brick|wall|diwar|deewar)\b|दीवार.*(छेद|ड्रिल|होल)",
        ("impact drill", "masonry drill bit", "wall plug"),
    ),
    (r"\bmachine\b.*\b(drill|hole)", ("drill",)),
    (
        r"\b(hang|hanging|mount|fix|fitting|put up|lagana|latkana)\b.*\b(shelf|shelves|rack|frame|mirror|tv|picture)\b|\b(shelf|shelves|rack)\b.*\b(wall|hang|fix|mount)\b|\bwall\b.*\b(shelf|rack|bracket)\b",
        ("wall plug", "screw", "anchor", "drill"),
    ),
    (r"\b(nail|nails|kil|keel|keelein|kill)\b|कील", ("nails", "hammer")),
    (r"\b(screw|screws|tight|tighten|loosen|screwing)\b|\b(pech|pench)\b|पेंच", ("screw", "screwdriver")),
    (r"\b(bolt|bolts|nut|nuts)\b", ("bolt", "nut")),
    # water, leaks, plumbing
    (
        r"\b(leak|leaks|leaking|leakage|leaky|seep\w*|drip\w*|tapak\w*|risa\w*|paani\s+leak)\b|रिसाव|टपक",
        ("ptfe tape", "sealant", "silicone", "tap"),
    ),
    (r"\b(water\s*proof\w*|waterproof\w*|seal\w*|gap|gaps|crack|cracks)\b", ("sealant", "silicone")),
    (r"\b(water\s+pipe|pani\s+ka\s+pipe|plumbing|plumber)\b", ("pipe", "cpvc", "upvc", "valve")),
    (r"\b(hot\s+water|geyser|garam\s+pani)\b", ("cpvc",)),
    (r"\b(tap|taps|faucet|nal|nalka|basin)\b|नल", ("tap",)),
    (
        r"\b(bathroom|washroom|toilet|shower|bath)\b.*\b(repair|fix|items|kit|saman|samaan)\b|\b(repair|fix)\b.*\b(bathroom|washroom)\b",
        ("tap", "ptfe tape", "silicone", "connector", "valve"),
    ),
    (r"\b(stop|shut|shutoff|shut off|control)\b.*\bwater\b", ("valve",)),
    (r"\b(hose|flexible)\b", ("connector",)),
    (r"\b(pipe\s+tool|open pipe|grip pipe|pipe grip)\b|\bwrench\b", ("pipe wrench", "spanner")),
    # electrical
    (r"\b(wire|wires|wiring|cable|cables|taar|tar)\b|तार", ("wire", "cable", "copper")),
    (r"\b(ac|a/c|air\s*condition\w*|geyser|heavy\s+load)\b", ("wire", "copper", "mcb")),
    (r"\b(switch|switches|button|on\s*off)\b", ("switch",)),
    (r"\b(plug|socket|sockets|outlet|point|charger\s+point)\b", ("socket",)),
    (r"\b(fuse|mcb|breaker|trip\w*|overload)\b", ("mcb",)),
    (r"\b(bulb|bulbs|light|lights|lighting|lamp|led|roshni|bijli\s+ka\s+bulb)\b|बल्ब", ("led", "bulb", "batten")),
    (r"\b(tube\s*light|tubelight|batten)\b", ("batten",)),
    (r"\b(fan|fans|pankha|ceiling fan|cooling)\b|पंखा", ("fan",)),
    (
        r"\b(tester|voltage|current|check\s+(the\s+)?(power|electric|current)|multimeter|volt)\b",
        ("multimeter", "tester"),
    ),
    (r"\b(insulat\w*|electric\w*\s+tape|joint\s+cover)\b", ("insulation tape",)),
    # tools
    (r"\b(hammer|hit|smash|break|hathoda|hathauda|hathodi)\b|हथौड़ा", ("hammer",)),
    (r"\b(cut|cutting|saw|hacksaw|blade)\b|\bkaatna\b|\bkatna\b", ("hacksaw",)),
    (r"\b(measure|measuring|length|tape\s*measure|nap|naap)\b|\bnaapna\b", ("measuring tape",)),
    (
        r"\b(spanner|open\s*end|nut\s+tighten\w*)\b|\btighten\w*\b.*\b(nut|nuts|bolt|bolts)\b|\b(nut|nuts|bolt|bolts)\b.*\btighten\w*",
        ("spanner", "wrench"),
    ),
    (r"\b(screwdriver|driver|pechkas|pechkash)\b", ("screwdriver",)),
    (r"\b(cordless|battery\s+drill|drill\s+machine)\b", ("cordless", "drill")),
    # building and gluing
    (r"\b(cement|concrete\s+work|plaster|construction|building\s+work)\b|सीमेंट", ("cement",)),
    (r"\b(tile|tiles|tiling|flooring)\b|\btiles?\b", ("tile adhesive",)),
    (r"\b(glue|stick|sticking|bond|fevicol|gum|adhesive|jod\w*)\b", ("adhesive", "glue")),
    (r"\b(wood|wooden|furniture|carpentry|lakdi)\b|लकड़ी", ("wood", "screw", "adhesive")),
    # boards and furniture hardware (approved categories, 2026-10-07)
    (r"\b(ply|plywood|plyboard|plai|plaai|marine\s+ply|bwp)\b|प्लाई", ("plywood",)),
    (r"\b(mdf|hdhmr|particle\s*board|board|boards)\b", ("mdf", "hdhmr", "plywood")),
    (
        r"\b(laminate|sunmica|sunmika|veneer)\b.*\b(glue|adhesive|stick\w*)\b|\bcontact\s+adhesive\b",
        ("contact adhesive",),
    ),
    (r"\b(hinge|hinges|kab[jz][aeo]\w*|soft\s*close)\b|कब्ज़?[ाे]", ("hinge",)),
    (r"\b(drawer|drawers|channel|channels|telescopic|daraa?z)\b", ("drawer channel",)),
    (r"\b(handle|handles|knob|knobs|handal|hendal|hendle|mutthi|muthi)\b|हैंडल", ("handle",)),
    (
        r"\b(modular\s+kitchen|kitchen\s+(basket|fitting|cabinet|drawer)s?|cutlery|thali|pantry)\b",
        ("kitchen basket", "pantry unit"),
    ),
    (r"\b(wardrobe|almirah|almari|almaari|almira|cupboard|hanger\s+rod)\b|अलमारी", ("wardrobe",)),
    (r"\b(storage\s+bed|hydraulic\s+bed|bed\s+fitting\w*)\b", ("bed fitting", "hydraulic bed")),
    (r"\b(lock|locks|taala|tala|taale|chabi|chaabi|latch)\b|ताला", ("lock", "door lock")),
    (r"\b(door\s+closer|closer|stopper)\b", ("door closer",)),
    (r"\b(tower\s+bolt|aldrop|aldrap|chitkani|chatkani|chitkini|sitkani|kunda|kundi)\b", ("tower bolt",)),
    (
        r"\b(glass\s+door|toughened\s+glass|patch\s+fitting|floor\s+spring|ka+nch\s+ka\s+darwaz\w*|ka+nch)\b",
        ("glass door", "patch fitting", "floor spring"),
    ),
    (r"\b(grinder|grinding|angle\s+grinder|cutting\s+disc)\b", ("angle grinder",)),
    (r"\b(vest|reflective|hi\s*vis|workwear)\b", ("safety vest",)),
    # safety
    (r"\b(safety|protect\w*|ppe|hand\s+protect\w*|cut\s+resist\w*)\b", ("gloves", "goggles", "helmet", "mask")),
    (r"\b(glove|gloves|hands|dastane|dastana|dastaane)\b|दस्ताने", ("gloves",)),
    (r"\b(dust|mask|breath\w*|cement\s+dust|sanding)\b", ("mask",)),
    (r"\b(eye|eyes|goggle|goggles|splash|chashma|chasma)\b", ("goggles",)),
    (r"\b(head|helmet|hard\s*hat|site\s+safety)\b", ("helmet",)),
    (r"\b(shoe|shoes|boots|foot|feet|joote|joota)\b", ("safety shoes",)),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), terms) for p, terms in SYNONYMS]
MAX_EXPANDED = 10
FILLER = {
    "for",
    "the",
    "a",
    "an",
    "of",
    "to",
    "on",
    "in",
    "me",
    "my",
    "i",
    "need",
    "want",
    "something",
    "thing",
    "things",
    "items",
    "item",
    "material",
    "saman",
    "samaan",
}


@dataclass
class Expansion:
    terms: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)  # catalogue word -> what in the query led to it
    counts: dict[str, int] = field(default_factory=dict)  # catalogue word -> how many parts of the query point to it
    typos: dict[str, str] = field(default_factory=dict)  # misspelt word -> catalogue word

    def __bool__(self) -> bool:
        return bool(self.terms)


def _add(expansion: Expansion, term: str, source: str, query: str) -> None:
    term = term.strip().lower()
    if term in expansion.counts:
        expansion.counts[term] += 1  # several parts of the query point to the same product word
    elif term and len(expansion.terms) < MAX_EXPANDED:
        expansion.terms.append(term)
        expansion.sources[term] = source
        expansion.counts[term] = 1


TYPO_CUTOFF = 0.8
MIN_TYPO_LENGTH = 4


def _known(word: str) -> bool:
    return word in FILLER or any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", phrase) for phrase in V.WORDS)


def expand(query: str, vocabulary: set[str] | frozenset[str] | None = None) -> Expansion:
    """Catalogue words for `query`, most specific first; empty when the query needs none.

    `vocabulary` (the words the catalogue really uses) switches on typo correction: a word that is
    not in it but is one or two letters away from a word that is ("hamer" → "hammer") is corrected.
    """
    lowered = " ".join(query.lower().split())
    result = Expansion()
    if not lowered:
        return result
    covered = [False] * len(lowered)
    # 1. The assistant's phrase list: longest phrases first (e.g. "nal tapak" before "nal").
    for phrase in sorted(V.WORDS, key=len, reverse=True):
        for match in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered):
            start, end = match.span()
            if any(covered[start:end]):
                continue
            for i in range(start, end):
                covered[i] = True
            for term in V.WORDS[phrase]:
                _add(result, term, phrase, lowered)
    # 2. Known jobs (a leaking tap, drilling into concrete …): the words of a typical kit.
    for topic in V.TOPICS.values():
        for pattern in topic.patterns:
            found = re.search(pattern, lowered)
            if found:
                for term in topic.terms:
                    _add(result, term, found.group(0).strip(), lowered)
                break
    # 0. Typos, against the words the catalogue really uses.
    if vocabulary:
        pool = sorted(vocabulary)
        for word in dict.fromkeys(re.findall(r"[a-z]+", lowered)):
            if len(word) < MIN_TYPO_LENGTH or word in vocabulary or _known(word):
                continue
            # Same first letter: real typos keep it ("drll", "hamer"), while an ordinary word that merely
            # looks alike does not ("head" is not a typo of "thread").
            same_start = [w for w in pool if w[0] == word[0]]
            close = difflib.get_close_matches(word, same_start, n=1, cutoff=TYPO_CUTOFF)
            if close:
                result.typos[word] = close[0]
                _add(result, close[0], f"{word} (typo)", lowered)
    # 3. Everyday descriptions.
    for pattern, terms in _COMPILED:
        found = pattern.search(lowered)
        if found:
            source = " ".join(found.group(0).split())[:40]
            for term in terms:
                _add(result, term, source, lowered)
    return result
