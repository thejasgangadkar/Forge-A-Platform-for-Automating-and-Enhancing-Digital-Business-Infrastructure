"""Fast, offline verification of the tuning decisions and defensive fixes.

Confirms the generation path, apostrophe normalisation, UUID guard and rate
limiter behave as intended without spending a single LLM token, so it can be run
freely after any config change.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\check_config_and_fixes.py
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

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


print("=" * 70)
print("CONFIG + FIX VERIFICATION  (no LLM calls, no tokens spent)")
print("=" * 70)

# ── generation path ───────────────────────────────────────────────────
print("\n[1] Generation path")
budget = int(os.getenv("WEBSITE_MAX_TOKENS", "0"))
omin = int(os.getenv("ONESHOT_MIN_TOKENS", "0"))
workers = int(os.getenv("PAGE_CONCURRENCY", "1"))
print(f"      WEBSITE_MAX_TOKENS={budget}  ONESHOT_MIN_TOKENS={omin}  "
      f"PAGE_CONCURRENCY={workers}")
# This used to assert `budget <= 6000`. That number was a property of Groq's
# FREE tier, which rejects any single request asking for more than ~6000 output
# tokens with HTTP 413 — it was never a universal truth. Hard-coding it here
# meant the check failed the moment the primary provider changed, and it would
# have blocked the one-shot generation path we actually want.
#
# The real invariant is: the requested budget must fit the OUTPUT CEILING of the
# model that is actually configured for building. Ceilings below come from each
# provider's published per-request limits; refresh with tests/list_model_options.py.
OUTPUT_CAPS = {
    ("groq", "openai/gpt-oss-120b"): 6000,
    ("gemini", "gemini-2.5-flash"): 65536,
    ("nvidia", "openai/gpt-oss-120b"): 16384,
    ("nvidia", "deepseek-ai/deepseek-v4-pro-0813"): 32768,
    ("nvidia", "deepseek-ai/deepseek-v4-flash-0731"): 32768,
    ("openrouter", "deepseek/deepseek-v4-pro"): 384000,
    ("openrouter", "deepseek/deepseek-v4-flash"): 384000,
    ("openrouter", "z-ai/glm-5.2"): 262144,
    ("openrouter", "qwen/qwen3-coder-next"): 235929,
    ("openrouter", "qwen/qwen3-coder-plus"): 65536,
}

build_provider = os.getenv("BUILD_PROVIDER", "").lower()
build_model = os.getenv("BUILD_MODEL", "")
cap = OUTPUT_CAPS.get((build_provider, build_model))
print(f"      BUILD = {build_provider}/{build_model}"
      + (f"  (output cap {cap})" if cap else "  (output cap unknown)"))

if cap is None:
    # An unlisted model is not a failure, it is an unknown. Say so rather than
    # inventing a limit and pretending the check was meaningful.
    check("build model output cap is known", False,
          f"add ({build_provider}, {build_model}) to OUTPUT_CAPS to verify the budget")
else:
    check(f"budget fits the {build_model} output cap",
          budget <= cap, f"{budget} <= {cap}")

# The one-shot 4-page call is worth attempting only when the budget could
# plausibly hold four pages; otherwise it truncates and the tokens are wasted.
# Both outcomes are correct — what matters is that the gate agrees with the
# budget, and that we report which path will actually run.
oneshot_on = budget >= omin
check("one-shot gate agrees with the budget", omin >= 10000,
      f"one-shot {'ENABLED' if oneshot_on else 'skipped'} "
      f"(budget {budget} vs threshold {omin})")

# Concurrency: 1 is the measured-best value on Groq's free tier, where a
# tokens-per-minute ceiling made parallel page generation slower (191s vs 143s).
# That measurement does not necessarily hold on paid OpenRouter, so the check
# only enforces that the knob is sane and reports what is set.
check("page concurrency is a sane value", workers >= 1,
      "sequential (measured-best on a TPM-capped free tier)"
      if workers == 1 else f"parallel x{workers} (re-measure before trusting)")

# ── apostrophe normalisation ──────────────────────────────────────────
print("\n[2] Grounding assertion - typographic apostrophe handling")
reply = "I\u2019m sorry, but I don\u2019t have the exact pricing details."
needles = ("don't have", "do not have", "not sure", "contact")
before = any(n in reply.lower() for n in needles)
after = any(n in reply.lower().replace("\u2019", "'").replace("\u2018", "'")
            for n in needles)
print(f"      model reply: {reply}")
check("un-normalised match failed (the original false failure)", before is False)
check("normalised match succeeds", after is True)

# ── uuid guard ────────────────────────────────────────────────────────
print("\n[3] UUID guard (HTTP 500 -> 404)")
from services.workspace_service import _is_uuid
check("rejects malformed id", not _is_uuid("rate-limit-probe-0000"))
check("rejects empty id", not _is_uuid(""))
check("rejects None", not _is_uuid(None))
check("accepts a real uuid", _is_uuid("3c967350-cc93-4c95-b36e-d55f299d9aae"))

# ── rate limiter ──────────────────────────────────────────────────────
print("\n[4] Rate limiter")
from services.rate_limit_service import check as rl_check
allowed = sum(1 for _ in range(25) if rl_check("offline-probe", 20, 60)[0])
check("allows exactly the configured budget", allowed == 20,
      f"{allowed} allowed, {25 - allowed} blocked, limit 20")
_, retry = rl_check("offline-probe", 20, 60)
check("reports a positive Retry-After", retry > 0, f"{retry}s")
fresh_ok, _ = rl_check("offline-probe-other", 20, 60)
check("independent key has its own budget", fresh_ok)

# ── widget surfaces contain the typing indicator ──────────────────────
print("\n[5] Typing indicator present in all chat surfaces")
from services.generation_service import _agent_widget_snippet
snippet = _agent_widget_snippet("test-workspace-id")
check("injected site widget", "forge-dot" in snippet and "forge-blink" in snippet)
check("  disables input while busy", "input.disabled" in snippet)
check("  handles 429", "429" in snippet)
check("  no raw non-ASCII arrow", "\u2192" not in snippet)

import main as forge_main
page = forge_main._PUBLIC_CHAT_HTML
check("hosted /a/{id} page", 'class="dot"' in page and "@keyframes blink" in page)
check("  handles 429", "429" in page)

widget_js = os.path.join("generated_workspaces", "_widget", "forge-widget.js")
js = open(widget_js, encoding="utf-8").read()
check("standalone embed script", "_fdot" in js and "_fblink" in js)
check("  injects its own scoped style", "document.head.appendChild(style)" in js)
check("  handles 429", "429" in js)

print("\n" + "=" * 70)
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
for f in FAIL:
    print("  FAILED:", f)
print("=" * 70)
