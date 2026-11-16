"""List the models actually available to this project's keys, per provider.

Free-tier model names get retired often, and vendor blog posts go stale fast, so
this queries each provider's live catalogue instead of trusting documentation.
Uses only free metadata endpoints - no tokens spent.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\list_model_options.py
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

import requests

INTEREST = ("kimi", "deepseek", "glm", "qwen", "minimax", "codestral",
            "gpt-oss", "llama-3.3", "nemotron", "starcoder")


def hr(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# ── GROQ ──────────────────────────────────────────────────────────────
hr("GROQ  (current CHAT + BUILD provider)")
try:
    from openai import OpenAI
    c = OpenAI(api_key=os.getenv("GROQ_API_KEY"),
               base_url="https://api.groq.com/openai/v1")
    ids = sorted(m.id for m in c.models.list().data)
    text_ids = [i for i in ids if not any(
        s in i.lower() for s in ("whisper", "orpheus", "guard", "tts"))]
    print(f"{len(ids)} models total; text-generation candidates:")
    for i in text_ids:
        cur = []
        if i == os.getenv("CHAT_MODEL"):
            cur.append("<- CHAT")
        if i == os.getenv("BUILD_MODEL"):
            cur.append("<- BUILD")
        print(f"   {i:<44} {' '.join(cur)}")
except Exception as e:
    print("  failed:", str(e)[:150])


# ── NVIDIA NIM ────────────────────────────────────────────────────────
hr("NVIDIA NIM  (fallback provider, free tier, slower)")
try:
    r = requests.get("https://integrate.api.nvidia.com/v1/models",
                     headers={"Authorization": f"Bearer {os.getenv('NVIDIA_API_KEY')}"},
                     timeout=30)
    ids = sorted(m["id"] for m in r.json().get("data", []))
    print(f"{len(ids)} models total; relevant to build/chat:")
    for i in ids:
        if any(w in i.lower() for w in INTEREST):
            cur = []
            if i == os.getenv("BUILD_NVIDIA_MODEL"):
                cur.append("<- BUILD fallback")
            if i == os.getenv("CHAT_NVIDIA_MODEL"):
                cur.append("<- CHAT fallback")
            print(f"   {i:<50} {' '.join(cur)}")
except Exception as e:
    print("  failed:", str(e)[:150])


# ── OPENROUTER ────────────────────────────────────────────────────────
hr("OPENROUTER  (optional premium build path - you have credits)")
try:
    r = requests.get("https://openrouter.ai/api/v1/models", timeout=30)
    ms = r.json().get("data", [])
    rows = []
    for m in ms:
        mid = m.get("id", "")
        if not any(w in mid.lower() for w in ("kimi", "deepseek", "glm", "qwen3", "minimax")):
            continue
        p = m.get("pricing", {}) or {}
        pin = float(p.get("prompt") or 0) * 1_000_000
        pout = float(p.get("completion") or 0) * 1_000_000
        rows.append((pin + pout, mid, pin, pout, m.get("context_length") or 0))
    rows.sort()
    print(f"{len(ms)} models total; strong open-weight coders "
          f"(price per 1M tokens, USD):\n")
    print(f"   {'MODEL':<46}{'IN':>8}{'OUT':>9}{'CONTEXT':>11}")
    print("   " + "-" * 72)
    for tot, mid, pin, pout, ctx in rows[:22]:
        tag = "  FREE" if tot == 0 else ""
        print(f"   {mid:<46}{pin:>8.2f}{pout:>9.2f}{ctx:>11,}{tag}")
except Exception as e:
    print("  failed:", str(e)[:150])

print("\n" + "=" * 78)
print("Current config -> CHAT_MODEL=%s | BUILD_MODEL=%s" %
      (os.getenv("CHAT_MODEL"), os.getenv("BUILD_MODEL")))
print("Swap models by editing forge.config.env, then restart the backend.")
print("=" * 78)
