"""Sentences in English, Hindi (Devanagari) and Hinglish, shared by Quantity AI and the project builder."""


def t(en: str, hi: str, hinglish: str = "") -> dict[str, str]:
    return {"en": en, "hi": hi, "hinglish": hinglish or en}


def say(texts: dict[str, str], language: str, **values) -> str:
    return (texts.get(language) or texts["en"]).format(**values)
