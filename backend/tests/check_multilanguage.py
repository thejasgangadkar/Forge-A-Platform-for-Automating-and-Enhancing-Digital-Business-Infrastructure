"""Multi-language support verification.

Covers the three things users actually asked for:
  1. Prompting in their own language and script
  2. Prompting in their language typed with ENGLISH letters (romanized)
  3. Speaking instead of typing, in that language

Default run is OFFLINE and spends no tokens: it asserts the wiring, the prompt
directives, the locale plumbing and the free fast paths. Pass --live to also
exercise real detection and translation, which does cost a few cheap calls.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\check_multilanguage.py
    .\\venv\\Scripts\\python.exe tests\\check_multilanguage.py --live
"""
import inspect
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from dotenv import load_dotenv
load_dotenv()
load_dotenv("forge.config.env", override=True)

LIVE = "--live" in sys.argv

from services import language_service as L
from services import generation_service as G
from services import workspace_assistant as W
from services import agent_runtime as A
from channels import base as ch_base
from channels.web import WebChannelAdapter
import main

PASS, FAIL, SKIP = [], [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def skip(name, why):
    SKIP.append(name)
    print(f"  [SKIP] {name} - {why}")


print("=" * 70)
print("MULTI-LANGUAGE VERIFICATION" + ("  (--live: real model calls)" if LIVE else "  (offline)"))
print("=" * 70)

# ── 1. language catalogue ─────────────────────────────────────────────
print("\n[1] Language catalogue")
langs = L.supported_list()
codes = {l["code"] for l in langs}
check("multiple languages offered", len(langs) >= 20, f"{len(langs)} languages")
check("English is the first option", langs[0]["code"] == "en")
check("major Indian languages present",
      {"hi", "kn", "ta", "te", "ml", "mr", "bn", "gu", "pa", "ur"} <= codes)
check("every entry has a BCP-47 locale for speech",
      all("-" in l["locale"] for l in langs),
      "needed by SpeechRecognition.lang / utterance.lang")
check("every entry has a native name", all(l["native_name"] for l in langs))
check("unknown code degrades to English rather than raising",
      L.info("zz")["code"] == "en" and L.info(None)["code"] == "en")
check("locale is accepted where a code is expected", L.info("kn-IN")["code"] == "kn")

# ── 2. cost control: English must be free ─────────────────────────────
print("\n[2] Cost control (English must not cost a model call)")
r = L.analyze("build me a website for my salon")
check("obvious English skips detection entirely", r["detected"] is False,
      "no LLM call, so the common case stays free")
check("English gloss is the original text", r["english"] == "build me a website for my salon")
check("empty input is free and safe", L.analyze("")["code"] == "en")
check("English reply directive is empty",
      L.reply_directive("en") == "" and L.content_directive("en") == "",
      "keeps existing English prompts byte-identical")
check("localize() is a no-op for English",
      L.localize("Your website is ready.", "en") == "Your website is ready.")

# ── 3. script detection without a model ───────────────────────────────
print("\n[3] Native-script detection (free, no model call)")
for code, sample in (("hi", "मेरा सैलून है"), ("kn", "ನನ್ನ ಹೋಟೆಲ್"),
                     ("ta", "என் கடை"), ("te", "నా వ్యాపారం"),
                     ("ml", "എന്റെ കട"), ("bn", "আমার দোকান"),
                     ("gu", "મારી દુકાન"), ("ru", "мой бизнес")):
    hint = L._script_hint(sample)
    check(f"{code}: script recognised from characters", hint == code, f"hint={hint}")

check("Latin text yields no script hint", L._script_hint("mera salon hai") is None,
      "this is exactly why romanized input needs the model")

# ── 4. prompt directives ──────────────────────────────────────────────
print("\n[4] Prompt directives")
hi = L.info("hi")
d = L.reply_directive(hi)
check("reply directive names the language and script",
      "Hindi" in d and "Devanagari" in d)
check("reply directive forbids announcing the translation", "Never mention" in d)

roman = dict(hi, romanized=True)
dr = L.reply_directive(roman)
check("romanized input is answered in Latin letters",
      "Latin" in dr and "Do NOT use Devanagari" in dr,
      "someone typing romanized cannot necessarily read the native script")

c = L.content_directive(hi)
check("website copy directive demands the NATIVE script",
      "Devanagari" in c and "Latin" not in c,
      "a public business page in romanized Hindi would look unprofessional")
check("website copy directive keeps code in English",
      "class names" in c and "JavaScript" in c)
check("website copy directive sets the html lang attribute", 'lang="hi"' in c)

# ── 5. signatures are threaded end to end ─────────────────────────────
print("\n[5] Language is threaded through every layer")
sigs = {
    "workspace_assistant.handle": W.handle,
    "agent_runtime.run_agent": A.run_agent,
    "generation_service.orchestrate_generation": G.orchestrate_generation,
    "generation_service.generate_multipage_website": G.generate_multipage_website,
    "generation_service.generate_website": G.generate_website,
    "generation_service.generate_agent_config": G.generate_agent_config,
    "generation_service.generate_agents": G.generate_agents,
    "generation_service.inject_agent_widget": G.inject_agent_widget,
}
for label, fn in sigs.items():
    params = inspect.signature(fn).parameters
    check(f"{label} accepts a language", "language" in params)

check("InboundMessage carries a language hint",
      "language" in inspect.signature(ch_base.InboundMessage).parameters)
check("friendly_action_reply can be localised",
      "language" in inspect.signature(ch_base.friendly_action_reply).parameters,
      "otherwise a booking confirmation reverts to English mid-conversation")
check("language is optional everywhere (English default preserved)",
      all(inspect.signature(fn).parameters["language"].default is None
          for fn in sigs.values()))

# ── 6. request models and routes ──────────────────────────────────────
print("\n[6] API surface")
check("AssistRequest accepts a language", "language" in main.AssistRequest.model_fields)
check("GenerateRequest accepts a language", "language" in main.GenerateRequest.model_fields)
for f in ("language", "locale"):
    check(f"AgentChatRequest accepts '{f}'", f in main.AgentChatRequest.model_fields)
routes = {getattr(r, "path", "") for r in main.app.routes}
check("/api/languages is exposed for the UI picker", "/api/languages" in routes)

adapter = WebChannelAdapter()
inbound = adapter.parse_inbound({
    "workspace_id": "w", "message": "hola", "history": [], "locale": "es-ES"})
check("web adapter reads the browser locale off the payload",
      inbound.language == "es-ES")

# ── 7. generated surfaces ─────────────────────────────────────────────
print("\n[7] Generated + served surfaces")
p = G.MULTIPAGE_ONESHOT_PROMPT.format(
    ctx="c", images="i", index_c="1", about_c="2", services_c="3", contact_c="4",
    html_lang=L.html_lang("ta"), lang_block=L.content_directive("ta"))
check("multipage prompt carries the language", 'lang="ta"' in p and "Tamil" in p)
en_p = G.MULTIPAGE_ONESHOT_PROMPT.format(
    ctx="c", images="i", index_c="1", about_c="2", services_c="3", contact_c="4",
    html_lang=L.html_lang("en"), lang_block=L.content_directive("en"))
check("English multipage prompt gains no language block",
      "LANGUAGE OF THE WEBSITE" not in en_p and 'lang="en"' in en_p)
check("per-page prompt carries the language",
      "Kannada" in G._single_page_prompt("c", "about", "i", "kn"))

snippet = G._agent_widget_snippet("ws-1", "en")
check("embed widget now has a microphone", "forge-agent-mic" in snippet,
      "voice was previously missing from this surface entirely")
check("embed widget speaks with an explicit lang", "u.lang=LOCALE" in snippet)
check("embed widget picks a matching voice", "getVoices" in snippet,
      "else non-English text is read by an English voice")
check("embed widget sends its locale to the backend", "locale:LOCALE" in snippet)

page = main._PUBLIC_CHAT_HTML.format(
    biz="B", agent="A", greeting="hi", ws="w", api="x",
    lang="hi", locale="hi-IN", t_placeholder="p", t_fast="f", t_err="e")
check("hosted page sets its html lang", 'lang="hi"' in page)
check("hosted page recognises speech in the right language", "rec.lang=LOCALE" in page)
check("hosted page speaks in the right language", "u.lang = LOCALE" in page)
check("hosted page no longer hardcodes en-US", "en-US" not in page)

# ── 8. frontend wiring ────────────────────────────────────────────────
print("\n[8] Frontend wiring")
FE = os.path.join(os.path.dirname(BACKEND), "frontend-next")


def read(*parts):
    path = os.path.join(FE, *parts)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read()


voice = read("components", "VoiceChat.js")
if voice is None:
    skip("VoiceChat wiring", "component not found")
else:
    check("VoiceChat takes a locale prop", "locale = 'en-US'" in voice)
    check("VoiceChat recognises speech in that locale",
          "recognition.lang = locale" in voice)
    check("VoiceChat speaks in that locale", "utterance.lang = locale" in voice)
    check("VoiceChat selects a matching voice", "utterance.voice = match" in voice)
    check("VoiceChat waits for the async voice list", "voiceschanged" in voice,
          "getVoices() is empty on first call in most browsers")
    check("VoiceChat no longer hardcodes en-US", "= 'en-US';" not in voice)

picker = read("components", "LanguagePicker.js")
if picker is None:
    skip("LanguagePicker", "component not found")
else:
    check("picker exists and exports a shared hook", "export function useLanguages" in picker)
    check("picker remembers the choice across visits", "localStorage" in picker)
    check("picker survives the list request failing", "FALLBACK" in picker)
    css = read("components", "LanguagePicker.module.css")
    check("picker is styled with a CSS module, not Tailwind", bool(css),
          "Tailwind is not a dependency of this project")

page_js = read("app", "dashboard", "workspace", "[id]", "page.js")
if page_js is None:
    skip("workspace page wiring", "page not found")
else:
    check("builder prompt box now has voice input",
          page_js.count("<VoiceChat") >= 2,
          "previously voice existed only on the customer-facing agent surfaces")
    check("assistant sends the chosen language", "api.assist(id, c, code)" in page_js)
    check("agent sandbox sends its locale",
          "api.agentChat(id, c, hist, agent.id, locale)" in page_js)
    check("both voice controls receive the locale",
          page_js.count("locale={locale}") >= 2)
    check("UI follows a language the backend detected",
          "r.language && r.language !== code" in page_js,
          "covers romanized input typed while the picker still said English")

api_js = read("lib", "api.js")
if api_js is None:
    skip("api client", "not found")
else:
    check("api client exposes the language list", "languages: ()" in api_js)
    check("assist() forwards a language", "assist: (id, message, language" in api_js)

# ── 9. live detection ─────────────────────────────────────────────────
print("\n[9] Live detection and translation" + ("" if LIVE else " (skipped)"))
if not LIVE:
    skip("romanized detection", "needs --live")
    skip("native-script detection", "needs --live")
    skip("UI string translation", "needs --live")
else:
    cases = [
        ("mera salon hai, mujhe website chahiye", "hi", True),
        ("nanna hotel ide, website beku", "kn", True),
        ("मेरा सैलून है, मुझे वेबसाइट चाहिए", "hi", False),
        ("necesito un sitio web para mi tienda", "es", None),
    ]
    for text, want, want_roman in cases:
        got = L.analyze(text)
        check(f"detects {want} in {'Latin letters' if want_roman else 'its own script'}",
              got["code"] == want, f"got {got['code']} (romanized={got['romanized']})")
        if want_roman is not None and got["code"] == want:
            check(f"{want}: romanized flag is {want_roman}",
                  bool(got["romanized"]) == want_roman)
        if got["code"] != "en":
            check(f"{want}: produced an English gloss for routing",
                  bool(got["english"]) and got["english"] != text,
                  (got["english"] or "")[:60])

    # The gloss is what makes the existing English routing keywords work.
    g = L.analyze("mujhe ek website banao")
    check("gloss contains a routing keyword the router relies on",
          any(k in (g["english"] or "").lower()
              for k in ("website", "build", "create", "make")),
          f"gloss={g['english']!r}")

    t = L.localize("Your website is ready.", L.info("hi"))
    check("UI string is translated", t != "Your website is ready.", t[:60])
    check("translation is cached (second call is free)",
          L.localize("Your website is ready.", L.info("hi")) == t)

# ── summary ───────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped")
for f in FAIL:
    print(f"  FAILED: {f}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
