"""Multi-language support: detection, romanized input, and prompt directives.

WHAT PROBLEM THIS SOLVES
------------------------
Forge's users are small business owners, and many of them do not think in
English. Three distinct things have to work:

  1. They type in their own language and script  ("मेरा सैलून है")
  2. They type their language in ENGLISH LETTERS  ("mera salon hai")
     This is how most people actually type on a phone without an Indic keyboard,
     and it is the case naive language detection gets wrong: the characters are
     all ASCII, so a script-based detector calls it English.
  3. They speak instead of typing, in that same language.

THE KEY DESIGN DECISION
-----------------------
Detection returns BOTH the language AND an English gloss of the message.

The gloss matters because the routing logic elsewhere in Forge makes English
substring checks ("build", "website", "create") that override the intent model.
Localising every one of those keyword lists into every language would be endless
and fragile. Translating the message into English once, and letting the existing
English logic run against the gloss, makes every downstream heuristic
language-agnostic for free. The user's original text is what gets sent to the
model for the actual reply, so nothing is lost in translation.

SCRIPT MIRRORING
----------------
A reply mirrors the script the user wrote in: someone typing romanized Hindi
probably cannot read Devanagari comfortably on that device, or they would have
typed it. Website COPY is the exception and always uses the native script, since
a public business page written in romanized Hindi looks unprofessional.

COST
----
Detection is one call on the cheap chat model, and it is skipped entirely when
the caller already knows the language (the UI language picker and the speech
locale both supply it) or when the text is obviously English.
"""
from __future__ import annotations

import hashlib
import re
from collections import OrderedDict

from services.llm_service import call_json

DEFAULT_LANG = "en"

# code -> (English name, native name, BCP-47 locale for Web Speech, native script)
# The locale drives SpeechRecognition.lang and SpeechSynthesisUtterance.lang in
# the browser, so it must be a real BCP-47 tag, not just the language code.
LANGUAGES: dict[str, tuple[str, str, str, str]] = {
    "en": ("English", "English", "en-US", "Latin"),
    # India — the primary target market.
    "hi": ("Hindi", "हिन्दी", "hi-IN", "Devanagari"),
    "kn": ("Kannada", "ಕನ್ನಡ", "kn-IN", "Kannada"),
    "ta": ("Tamil", "தமிழ்", "ta-IN", "Tamil"),
    "te": ("Telugu", "తెలుగు", "te-IN", "Telugu"),
    "ml": ("Malayalam", "മലയാളം", "ml-IN", "Malayalam"),
    "mr": ("Marathi", "मराठी", "mr-IN", "Devanagari"),
    "bn": ("Bengali", "বাংলা", "bn-IN", "Bengali"),
    "gu": ("Gujarati", "ગુજરાતી", "gu-IN", "Gujarati"),
    "pa": ("Punjabi", "ਪੰਜਾਬੀ", "pa-IN", "Gurmukhi"),
    "ur": ("Urdu", "اردو", "ur-IN", "Arabic"),
    "or": ("Odia", "ଓଡ଼ିଆ", "or-IN", "Odia"),
    "as": ("Assamese", "অসমীয়া", "as-IN", "Bengali"),
    # Wider world.
    "es": ("Spanish", "Español", "es-ES", "Latin"),
    "fr": ("French", "Français", "fr-FR", "Latin"),
    "de": ("German", "Deutsch", "de-DE", "Latin"),
    "pt": ("Portuguese", "Português", "pt-BR", "Latin"),
    "it": ("Italian", "Italiano", "it-IT", "Latin"),
    "nl": ("Dutch", "Nederlands", "nl-NL", "Latin"),
    "ru": ("Russian", "Русский", "ru-RU", "Cyrillic"),
    "ar": ("Arabic", "العربية", "ar-SA", "Arabic"),
    "fa": ("Persian", "فارسی", "fa-IR", "Arabic"),
    "tr": ("Turkish", "Türkçe", "tr-TR", "Latin"),
    "zh": ("Chinese", "中文", "zh-CN", "Han"),
    "ja": ("Japanese", "日本語", "ja-JP", "Japanese"),
    "ko": ("Korean", "한국어", "ko-KR", "Hangul"),
    "id": ("Indonesian", "Bahasa Indonesia", "id-ID", "Latin"),
    "vi": ("Vietnamese", "Tiếng Việt", "vi-VN", "Latin"),
    "th": ("Thai", "ไทย", "th-TH", "Thai"),
    "sw": ("Swahili", "Kiswahili", "sw-KE", "Latin"),
}

# Unicode ranges that identify a language by script alone. When text contains
# these characters no model call is needed, which makes native-script input both
# free and instant. Romanized input is the case this cannot catch.
_SCRIPT_RANGES: list[tuple[str, str]] = [
    ("kn", r"[\u0C80-\u0CFF]"),
    ("ta", r"[\u0B80-\u0BFF]"),
    ("te", r"[\u0C00-\u0C7F]"),
    ("ml", r"[\u0D00-\u0D7F]"),
    ("gu", r"[\u0A80-\u0AFF]"),
    ("pa", r"[\u0A00-\u0A7F]"),
    ("or", r"[\u0B00-\u0B7F]"),
    ("bn", r"[\u0980-\u09FF]"),   # Bengali/Assamese share a script
    ("hi", r"[\u0900-\u097F]"),   # Devanagari: Hindi/Marathi, disambiguated by model
    ("th", r"[\u0E00-\u0E7F]"),
    ("ko", r"[\uAC00-\uD7AF]"),
    ("ja", r"[\u3040-\u30FF]"),
    ("zh", r"[\u4E00-\u9FFF]"),
    ("ru", r"[\u0400-\u04FF]"),
    ("ar", r"[\u0600-\u06FF]"),
]

# Very common English words. Two or more of these in ASCII-only text is a strong
# enough signal to skip detection. Deliberately excludes words that are also
# frequent in romanized Indic text.
_EN_MARKERS = {
    "the", "and", "for", "with", "you", "your", "please", "want", "need",
    "make", "build", "create", "website", "site", "agent", "business", "add",
    "change", "update", "can", "would", "should", "have", "this", "that",
    "about", "from", "there", "what", "when", "where", "how", "some", "more",
}

_CACHE: OrderedDict[str, dict] = OrderedDict()
_CACHE_MAX = 512


def is_supported(code: str) -> bool:
    return code in LANGUAGES


def info(code: str) -> dict:
    """Everything the rest of the app needs about a language code."""
    code = (code or DEFAULT_LANG).lower().split("-")[0]
    if code not in LANGUAGES:
        code = DEFAULT_LANG
    name, native, locale, script = LANGUAGES[code]
    return {"code": code, "name": name, "native_name": native,
            "locale": locale, "script": script}


def supported_list() -> list[dict]:
    """For the UI language picker. English first, then alphabetical by name."""
    items = [info(c) for c in LANGUAGES]
    items.sort(key=lambda i: (i["code"] != DEFAULT_LANG, i["name"]))
    return items


def html_lang(code: str) -> str:
    """Value for the <html lang="..."> attribute of a generated page."""
    return info(code)["code"]


# ─── detection ──────────────────────────────────────────────────────
def _script_hint(text: str) -> str | None:
    for code, pattern in _SCRIPT_RANGES:
        if re.search(pattern, text):
            return code
    return None


def _looks_english(text: str) -> bool:
    """True when ASCII-only text carries enough English markers to be certain."""
    if not text.isascii():
        return False
    words = re.findall(r"[a-z']+", text.lower())
    if not words:
        return True  # digits/punctuation only: nothing to translate
    hits = sum(1 for w in words if w in _EN_MARKERS)
    # Short messages need proportionally fewer hits ("build me a website" -> 3).
    return hits >= 2 or (len(words) <= 3 and hits >= 1)


def _cache_get(text: str) -> dict | None:
    key = hashlib.sha1(text.strip().lower().encode("utf-8")).hexdigest()
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
    return hit


def _cache_put(text: str, value: dict) -> None:
    key = hashlib.sha1(text.strip().lower().encode("utf-8")).hexdigest()
    _CACHE[key] = value
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


def _english_result(text: str) -> dict:
    base = info(DEFAULT_LANG)
    base.update({"romanized": False, "english": text, "detected": False})
    return base


def analyze(text: str, declared: str | None = None) -> dict:
    """Identify the language of `text` and provide an English gloss.

    Returns: {code, name, native_name, locale, script, romanized, english, detected}

    `romanized` is True when the user wrote a non-English language using Latin
    letters, which is what tells the reply which script to mirror.
    `english` is an English rendering used for the routing heuristics; it equals
    the input when the input is already English.

    `declared` short-circuits detection: the UI language picker and the speech
    locale already know the language, so there is no reason to pay for a call.
    Even then a gloss is still needed for routing when the language is not
    English, so only the language-identification half is skipped.

    Never raises. On any failure it degrades to treating the text as English,
    because a detection problem must not block someone from building a website.
    """
    text = (text or "").strip()
    if not text:
        return _english_result("")

    declared_code = info(declared)["code"] if declared and is_supported(
        (declared or "").lower().split("-")[0]) else None

    # Fast, free paths.
    if declared_code == DEFAULT_LANG or (declared_code is None and _looks_english(text)):
        if _script_hint(text) is None:
            return _english_result(text)

    cached = _cache_get(text)
    if cached and (declared_code is None or cached["code"] == declared_code):
        return dict(cached)

    hint = declared_code or _script_hint(text)
    hint_line = (
        f"\nThe language is most likely '{hint}'. Confirm or correct it."
        if hint else ""
    )

    data = {}
    try:
        data = call_json(
            "You are a language identifier for a business website builder.\n"
            "Users often type their own language using ENGLISH letters "
            "(romanized), for example Hindi as \"mera salon hai\" or Kannada as "
            "\"nanna hotel ide\". Treat that as that language, NOT as English.\n"
            f"{hint_line}\n\n"
            f'MESSAGE: """{text[:600]}"""\n\n'
            "Return ONLY JSON:\n"
            "{\n"
            '  "code": "ISO 639-1 two-letter code, e.g. en, hi, kn, ta, es",\n'
            '  "romanized": true if a non-English language was written in Latin '
            'letters, else false,\n'
            '  "english": "a faithful English translation of the message; '
            'if it is already English, repeat it unchanged"\n'
            "}",
            role="chat", max_tokens=500, temperature=0.0,
        )
    except Exception as e:
        print(f"[lang] detection unavailable, assuming English: {str(e)[:120]}")
        return _english_result(text)

    if not isinstance(data, dict):
        return _english_result(text)

    code = str(data.get("code") or "").lower().split("-")[0]
    if not is_supported(code):
        # An unsupported or hallucinated code falls back to the script hint,
        # then to English. Guessing a language we cannot speak is worse than
        # defaulting.
        code = hint if hint and is_supported(hint) else DEFAULT_LANG

    result = info(code)
    english = str(data.get("english") or "").strip() or text
    result.update({
        "romanized": bool(data.get("romanized")) and code != DEFAULT_LANG,
        "english": text if code == DEFAULT_LANG else english,
        "detected": True,
    })
    _cache_put(text, result)
    return result


# ─── prompt directives ──────────────────────────────────────────────
def reply_directive(lang: dict | str) -> str:
    """Instruction block telling a model how to answer a user's message.

    Mirrors the user's script, because someone who typed romanized text is
    likely on a device where they cannot comfortably read the native script.
    Returns "" for English so English prompts stay byte-identical to before and
    no existing behaviour shifts.
    """
    li = lang if isinstance(lang, dict) else info(lang)
    if li["code"] == DEFAULT_LANG:
        return ""

    if li.get("romanized"):
        script_rule = (
            f"The user wrote {li['name']} using English (Latin) letters. "
            f"Reply in {li['name']} ALSO written in Latin letters, so they can "
            f"read it on the same keyboard. Do NOT use {li['script']} script."
        )
    else:
        script_rule = f"Reply in {li['name']} using {li['script']} script."

    return (
        f"\n\nLANGUAGE:\n"
        f"The user is speaking {li['name']} ({li['native_name']}). {script_rule}\n"
        "Keep proper nouns, brand names and technical words as they are. "
        "Do not translate the business's own name. Never mention that you "
        "detected a language or that you are translating."
    )


def content_directive(lang: dict | str) -> str:
    """Instruction block for GENERATED WEBSITE COPY.

    Unlike a chat reply this always uses the native script: a public business
    page written in romanized Hindi would look unprofessional to its customers,
    even if the owner typed their request that way.
    """
    li = lang if isinstance(lang, dict) else info(lang)
    if li["code"] == DEFAULT_LANG:
        return ""
    return (
        f"\n\nLANGUAGE OF THE WEBSITE:\n"
        f"Write ALL visible page copy in {li['name']} ({li['native_name']}), "
        f"using {li['script']} script — headings, paragraphs, button labels, "
        f"navigation links, form labels, alt text and the footer.\n"
        f"Keep the business name as given. Keep HTML tags, attributes, CSS "
        f"class names and JavaScript identifiers in English.\n"
        f'Set the document language: <html lang="{li["code"]}">.'
    )


# ─── localising fixed UI strings ─────────────────────────────────────
# The assistant has a small set of canned replies ("Your website is ready.").
# A hand-written table of every string in every supported language would be
# large, permanently out of date, and would cap us at the languages someone
# bothered to translate. Instead these are translated on demand and cached
# forever, so each distinct string costs one call per language for the lifetime
# of the process and nothing after that.
_STRING_CACHE: dict[tuple[str, str, bool], str] = {}


def localize(text: str, lang: dict | str) -> str:
    """Translate a short fixed UI string. Returns `text` unchanged for English.

    Falls back to the English original on any failure: showing English is a
    minor inconvenience, whereas raising here would break the reply entirely.
    """
    li = lang if isinstance(lang, dict) else info(lang)
    if li["code"] == DEFAULT_LANG or not text or not text.strip():
        return text

    key = (text, li["code"], bool(li.get("romanized")))
    if key in _STRING_CACHE:
        return _STRING_CACHE[key]

    if li.get("romanized"):
        how = (f"into {li['name']} but written in English (Latin) letters, "
               f"not {li['script']} script")
    else:
        how = f"into {li['name']} using {li['script']} script"

    try:
        data = call_json(
            f"Translate this short UI message {how}.\n"
            "Keep it equally short and natural. Keep product names, brand names "
            "and placeholders unchanged.\n\n"
            f'MESSAGE: """{text}"""\n\n'
            'Return ONLY JSON: {"text": "<the translation>"}',
            role="chat", max_tokens=400, temperature=0.1,
        )
        out = str((data or {}).get("text") or "").strip()
    except Exception as e:
        print(f"[lang] could not localize a UI string: {str(e)[:100]}")
        out = ""

    out = out or text
    _STRING_CACHE[key] = out
    return out
