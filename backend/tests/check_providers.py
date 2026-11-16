"""Provider / API-key health check.

Run this whenever generation starts failing or after a long break - free-tier
model names get retired regularly, and this pinpoints exactly which provider or
key needs attention instead of guessing.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\check_providers.py

Token-efficient by design: uses free metadata endpoints where available and
only makes a tiny completion call where a provider offers no metadata route.
"""
import os
import sys
import json

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from dotenv import load_dotenv
load_dotenv()
load_dotenv("forge.config.env", override=True)

import requests
from openai import OpenAI

results = {}


def mark(name, ok, detail=""):
    results[name] = {"ok": ok, "detail": detail}
    status = "LIVE" if ok else "FAIL"
    print(f"[{status:4}] {name}: {detail}")


# ── 1. GROQ (free metadata call, then 1 tiny completion) ──────────────
key = os.getenv("GROQ_API_KEY", "")
if not key:
    mark("groq", False, "no key set")
else:
    try:
        c = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
        ids = sorted(m.id for m in c.models.list().data)
        # Check the models configured FOR GROQ, not CHAT_MODEL/BUILD_MODEL.
        # Those name the primary provider (now OpenRouter), so testing them here
        # reported a false failure the moment the primary stopped being Groq.
        # Each provider must be validated against its own configured models.
        want = [os.getenv("CHAT_GROQ_MODEL"), os.getenv("BUILD_GROQ_MODEL")]
        missing = [m for m in want if m and m not in ids]
        if missing:
            mark("groq", False, f"configured Groq fallback model(s) missing: {missing}")
        else:
            # Metadata only. The model list already proves the key works, so
            # there is no reason to spend completion tokens confirming it.
            mark("groq", True, f"key valid, {len(ids)} models, configured fallbacks present")
        print(f"         available: {', '.join(ids[:14])}")
    except Exception as e:
        mark("groq", False, str(e)[:160])


# ── 2. NVIDIA NIM (metadata only - completions are slow on free tier) ─
key = os.getenv("NVIDIA_API_KEY", "")
if not key:
    mark("nvidia", False, "no key set")
else:
    try:
        r = requests.get(
            "https://integrate.api.nvidia.com/v1/models",
            headers={"Authorization": f"Bearer {key}"}, timeout=20)
        if r.status_code == 200:
            ids = sorted(m["id"] for m in r.json().get("data", []))
            want = [os.getenv("CHAT_NVIDIA_MODEL"), os.getenv("BUILD_NVIDIA_MODEL")]
            missing = [m for m in want if m and m not in ids]
            if missing:
                mark("nvidia", False, f"key valid BUT configured fallback model(s) missing: {missing}")
            else:
                mark("nvidia", True, f"key valid, {len(ids)} models, configured fallbacks present")
        elif r.status_code in (401, 403):
            mark("nvidia", False, f"key rejected ({r.status_code}) - needs replacing")
        else:
            mark("nvidia", False, f"HTTP {r.status_code}")
    except Exception as e:
        mark("nvidia", False, str(e)[:160])


# ── 3. OPENROUTER (free credits endpoint - zero tokens) ───────────────
key = os.getenv("OPENROUTER_API_KEY", "")
if not key:
    mark("openrouter", False, "no key set")
else:
    try:
        r = requests.get("https://openrouter.ai/api/v1/key",
                         headers={"Authorization": f"Bearer {key}"}, timeout=20)
        if r.status_code == 200:
            d = r.json().get("data", {})
            used = d.get("usage")
            lim = d.get("limit")
            free_tier = d.get("is_free_tier")

            # OpenRouter is the PRIMARY provider, so its configured models are
            # the ones that must exist. The catalogue endpoint is free.
            want = [m for m in (
                os.getenv("CHAT_MODEL") if os.getenv("CHAT_PROVIDER") == "openrouter" else None,
                os.getenv("BUILD_MODEL") if os.getenv("BUILD_PROVIDER") == "openrouter" else None,
                os.getenv("CHAT_MODEL_FALLBACK"),
                os.getenv("BUILD_MODEL_FALLBACK"),
                os.getenv("VISION_MODEL") if os.getenv("VISION_PROVIDER") == "openrouter" else None,
            ) if m]
            cat = requests.get("https://openrouter.ai/api/v1/models", timeout=20)
            ids = {m["id"] for m in cat.json().get("data", [])} if cat.status_code == 200 else set()
            missing = [m for m in want if ids and m not in ids]

            detail = f"key valid; usage={used} limit={lim}"
            if free_tier:
                # Paid models are what the primaries are; say so plainly rather
                # than letting a later 402 look like a code fault.
                detail += "; FREE TIER (top up credits to use the paid primaries)"
            if missing:
                mark("openrouter", False, f"{detail}; configured model(s) not in catalogue: {missing}")
            else:
                mark("openrouter", True, f"{detail}; {len(want)} configured model(s) present")
        elif r.status_code in (401, 403):
            mark("openrouter", False, f"key rejected ({r.status_code}) - needs replacing")
        else:
            mark("openrouter", False, f"HTTP {r.status_code}")
    except Exception as e:
        mark("openrouter", False, str(e)[:160])


# ── 4. GEMINI (free model-list endpoint - zero tokens) ────────────────
key = os.getenv("GEMINI_API_KEY", "")
if not key:
    mark("gemini", False, "no key set (optional)")
else:
    try:
        r = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
            timeout=20)
        if r.status_code == 200:
            n = len(r.json().get("models", []))
            mark("gemini", True, f"key valid, {n} models (optional fallback)")
        else:
            mark("gemini", False, f"HTTP {r.status_code} - {r.text[:80]}")
    except Exception as e:
        mark("gemini", False, str(e)[:160])


# ── 5. PEXELS (1 cheap search) ────────────────────────────────────────
key = os.getenv("PEXELS_API_KEY", "")
if not key:
    mark("pexels", False, "no key set")
else:
    try:
        r = requests.get("https://api.pexels.com/v1/search",
                         headers={"Authorization": key},
                         params={"query": "office", "per_page": 1}, timeout=15)
        if r.status_code == 200:
            n = len(r.json().get("photos", []))
            rem = r.headers.get("X-Ratelimit-Remaining", "?")
            mark("pexels", n > 0, f"{n} photo(s); quota remaining={rem}")
        elif r.status_code == 401:
            mark("pexels", False, "key rejected - needs replacing")
        else:
            mark("pexels", False, f"HTTP {r.status_code}")
    except Exception as e:
        mark("pexels", False, str(e)[:160])


# ── 6. SUPABASE (free select) ─────────────────────────────────────────
try:
    from supabase import create_client
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    tables = {}
    for t in ("workspaces", "conversations", "assets", "agent_actions", "analytics_events"):
        try:
            res = sb.table(t).select("id", count="exact").limit(1).execute()
            tables[t] = res.count if res.count is not None else 0
        except Exception as e:
            tables[t] = f"ERR {str(e)[:40]}"
    bad = [k for k, v in tables.items() if isinstance(v, str)]
    mark("supabase", not bad, f"tables={tables}")
except Exception as e:
    mark("supabase", False, str(e)[:160])


# ── 7. CHROMA / RAG (local, free) ─────────────────────────────────────
try:
    from rag.vector_store import vector_store
    cnt = vector_store.col.count()
    mark("chromadb", True, f"local store OK, {cnt} chunks")
except Exception as e:
    mark("chromadb", False, str(e)[:160])


print("\n" + "=" * 60)
failed = [k for k, v in results.items() if not v["ok"]]
if failed:
    print("NEEDS ATTENTION:", ", ".join(failed))
else:
    print("ALL PROVIDERS LIVE")
print("=" * 60)
