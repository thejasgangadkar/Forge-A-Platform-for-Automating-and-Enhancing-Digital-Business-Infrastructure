"""Verify the multi-provider fallback chain (TRD §4).

The TRD promises "no single point of failure". Testing that properly means
forcing a provider to fail and proving the next one answers — not just checking
that a chain exists on paper.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\check_fallback_chain.py [--live]
"""
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
PASS, FAIL, SKIP = [], [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def skip(name, why):
    SKIP.append(name)
    print(f"  [SKIP] {name} - {why}")


print("=" * 74)
print("MULTI-PROVIDER FALLBACK CHAIN (TRD section 4)")
print("=" * 74)

import services.llm_service as svc

# ── chain composition ─────────────────────────────────────────────────
print("\n[1] Chain composition")
chat_chain = svc.provider_chain("chat")
build_chain = svc.provider_chain("build")
print(f"      chat : {' -> '.join(f'{p}/{m}' for p, m in chat_chain)}")
print(f"      build: {' -> '.join(f'{p}/{m}' for p, m in build_chain)}")

check("chat chain has multiple providers", len(chat_chain) >= 3, f"{len(chat_chain)}")
check("build chain has multiple providers", len(build_chain) >= 3, f"{len(build_chain)}")
check("no single point of failure (TRD claim)",
      len({p for p, _ in chat_chain}) >= 3 and len({p for p, _ in build_chain}) >= 3)
check("gemini is in the chat chain", any(p == "gemini" for p, _ in chat_chain))
check("gemini is in the build chain", any(p == "gemini" for p, _ in build_chain))
check("nvidia is in both chains",
      any(p == "nvidia" for p, _ in chat_chain) and any(p == "nvidia" for p, _ in build_chain))
check("no duplicate provider/model pairs",
      len(set(chat_chain)) == len(chat_chain) and len(set(build_chain)) == len(build_chain))
check("primary is first in the chat chain",
      chat_chain[0] == (svc.CHAT_PROVIDER, svc.CHAT_MODEL), str(chat_chain[0]))

# ── providers without keys must be skipped ────────────────────────────
print("\n[2] Unconfigured providers are skipped")
saved = svc._PROVIDER_KEYS.copy()
try:
    svc._PROVIDER_KEYS["gemini"] = ""
    check("no key -> dropped from chain",
          not any(p == "gemini" for p, _ in svc.provider_chain("chat")))
    for name in list(svc._PROVIDER_KEYS):
        svc._PROVIDER_KEYS[name] = ""
    try:
        svc.llm("hi", role="chat")
        check("empty chain raises a clear error", False, "no exception raised")
    except RuntimeError as e:
        check("empty chain raises a clear error", "No provider configured" in str(e))
    except Exception as e:
        check("empty chain raises a clear error", False, type(e).__name__)
finally:
    svc._PROVIDER_KEYS.clear()
    svc._PROVIDER_KEYS.update(saved)
check("keys restored", svc._has_key("groq"))

# ── error classification ──────────────────────────────────────────────
print("\n[3] Error classification")
cases = [
    ("Error code: 404 - model does not exist", "permanent"),
    ("Error code: 410 - end of life", "permanent"),
    ("Error code: 401 - unauthorized", "permanent"),
    ("Error code: 402 - insufficient credit", "permanent"),
    ("Error code: 429 - rate limit reached", "transient"),
    ("Error code: 503 - high demand", "transient"),
    ("Request timed out", "transient"),
    ("Error code: 413 - Request too large", "too_large"),
]
for text, expected in cases:
    low = text.lower()
    kind = ("too_large" if any(s in low for s in svc._TOO_LARGE)
            else "permanent" if any(s in low for s in svc._PERMANENT)
            else "transient" if any(s in low for s in svc._TRANSIENT)
            else "unknown")
    check(f"  '{text[:34]}' -> {expected}", kind == expected, f"got {kind}")

# ── live: does the fallback actually save the call? ───────────────────
print("\n[4] Live behaviour")
if LIVE:
    try:
        out = svc.llm("Reply with exactly: OK", role="chat", max_tokens=200, temperature=0)
        check("chat works through the chain", "ok" in out.lower(), repr(out[:40]))
    except Exception as e:
        check("chat works through the chain", False, str(e)[:90])

    # Force the primary to fail with a retired model name and confirm the chain
    # recovers. This is the actual TRD claim under test.
    print("      forcing the primary chat model to fail...")
    original = svc.CHAT_MODEL
    try:
        svc.CHAT_MODEL = "this-model-does-not-exist-12345"
        out = svc.llm("Reply with exactly: OK", role="chat", max_tokens=200, temperature=0)
        check("recovers when the primary model is dead", "ok" in out.lower(),
              f"fallback answered: {out[:40]!r}")
    except Exception as e:
        check("recovers when the primary model is dead", False, str(e)[:110])
    finally:
        svc.CHAT_MODEL = original

    # Gemini specifically, since it is the newly added provider.
    if svc._has_key("gemini"):
        try:
            out = svc._complete("gemini", svc.CHAT_GEMINI_MODEL,
                                [{"role": "user", "content": "Reply with exactly: OK"}],
                                200, 0, False)
            check("gemini answers directly", "ok" in (out or "").lower(), repr((out or "")[:40]))
        except Exception as e:
            check("gemini answers directly", False, str(e)[:90])
    else:
        skip("gemini direct call", "no GEMINI_API_KEY")

    # JSON extraction must still work after the refactor.
    try:
        data = svc.call_json('Return ONLY JSON: {"ok": true}', role="chat", max_tokens=200)
        check("call_json still parses", isinstance(data, dict) and data.get("ok") is True,
              str(data))
    except Exception as e:
        check("call_json still parses", False, str(e)[:90])
else:
    skip("live behaviour", "pass --live to run (3 small calls)")

# ── docs must match the implementation ────────────────────────────────
print("\n[5] Config documents the chain")
cfg = open("forge.config.env", encoding="utf-8").read()
check("CHAT_GEMINI_MODEL documented", "CHAT_GEMINI_MODEL" in cfg)
check("BUILD_GEMINI_MODEL documented", "BUILD_GEMINI_MODEL" in cfg)
check("fallback order explained", "FALLBACK CHAIN" in cfg)

print("\n" + "=" * 74)
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped")
for f in FAIL:
    print("  FAILED:", f)
print("=" * 74)
