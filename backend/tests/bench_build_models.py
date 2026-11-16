"""Benchmark candidate BUILD models on Forge's real page-generation prompt.

Leaderboards measure general coding ability, which is not the same as producing
one complete, self-contained, well-designed HTML page from our specific prompt.
This runs the actual prompt through each candidate and scores the output on the
things the product depends on.

All candidates are open-weight models.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\bench_build_models.py
"""
import os
import re
import sys
import time

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

from openai import OpenAI
from services.generation_service import _single_page_prompt, _strip_html

TIMEOUT = 100  # per-request ceiling; a build model slower than this is unusable

BASES = {
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
}
KEYS = {
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
}


def complete(provider, model, prompt, max_tokens):
    """Direct call with an explicit timeout (llm_service._complete has none)."""
    kw = {"api_key": os.getenv(KEYS[provider]), "base_url": BASES[provider],
          "timeout": TIMEOUT, "max_retries": 0}
    if provider == "openrouter":
        kw["default_headers"] = {"HTTP-Referer": "http://localhost", "X-Title": "Forge"}
    r = OpenAI(**kw).chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens, temperature=0.6)
    return r.choices[0].message.content or ""

BIZ = ("Anahata Yoga & Wellness Studio in Indiranagar, Bengaluru. Opened 2019. "
       "Hatha and Vinyasa classes, beginner workshops, prenatal yoga, private "
       "one-on-one sessions, monthly meditation retreats. Classes Monday to "
       "Saturday 6am-8pm. Three certified instructors. Members are working "
       "professionals aged 25-45 wanting to de-stress. Calm, warm, welcoming "
       "tone. Phone 080-2233-4455, hello@anahatayoga.in.")

IMAGES = "\n".join(
    f"- https://images.pexels.com/photos/{n}/pexels-photo-{n}.jpeg"
    for n in (3822622, 3820382, 4056723, 2529375, 1051838))

PROMPT = _single_page_prompt(BIZ, "index", IMAGES)

# (label, provider, model)  - all open-weight
CANDIDATES = [
    ("gpt-oss-120b (Groq, current)", "groq", "openai/gpt-oss-120b"),
    ("Qwen3.6 27B (Groq)", "groq", "qwen/qwen3.6-27b"),
    ("Qwen3 Coder Next (OpenRouter)", "openrouter", "qwen/qwen3-coder-next"),
    ("DeepSeek V4 Flash (OpenRouter)", "openrouter", "deepseek/deepseek-v4-flash"),
    ("GLM-4.7 Flash (OpenRouter)", "openrouter", "z-ai/glm-4.7-flash"),
    ("GLM-5.2 free (OpenRouter)", "openrouter", "z-ai/glm-5.2:free"),
    ("Kimi K3 (NVIDIA NIM, free)", "nvidia", "moonshotai/kimi-k3"),
    ("DeepSeek V4 Flash (NIM, free)", "nvidia", "deepseek-ai/deepseek-v4-flash-0731"),
]

MAX_TOKENS = 6000  # Groq's free tier rejects larger single requests with 413


def score(html: str) -> tuple[int, list[str]]:
    """Score generated HTML on what the product actually requires."""
    pts, notes = 0, []

    def add(ok, weight, label):
        nonlocal pts
        if ok:
            pts += weight
        else:
            notes.append(label)

    low = html.lower()
    add("<!doctype" in low, 1, "no doctype")
    add("</html>" in low, 2, "unterminated doc")
    add("cdn.tailwindcss.com" in html, 1, "no tailwind")
    add("<!--FORGE_AGENT_WIDGET-->" in html, 2, "MISSING widget marker")

    navs = sum(1 for p in ("index.html", "about.html", "services.html", "contact.html")
               if p in html)
    add(navs == 4, 2, f"nav links {navs}/4")

    add(len(re.findall(r"--[a-z-]+\s*:", html)) >= 3, 1, "no CSS design tokens")
    add(html.count("pexels.com") >= 2, 1, "few real images")
    add(len(re.findall(r"<section", low)) >= 4, 2, "thin structure (<4 sections)")
    add(len(re.findall(r"<svg", low)) >= 1, 1, "no inline SVG icons")
    add("lorem ipsum" not in low, 2, "LOREM IPSUM present")
    add("anahata" in low, 2, "business name missing")

    biz_terms = sum(1 for t in ("vinyasa", "hatha", "prenatal", "meditation", "retreat")
                    if t in low)
    add(biz_terms >= 3, 2, f"generic copy (only {biz_terms}/5 specifics)")
    add("2233" in html or "anahatayoga" in low, 1, "no contact details")
    add('alt="' in html, 1, "images missing alt text")
    add("@media" in html or "md:" in html or "sm:" in html, 1, "not responsive")
    return pts, notes


MAX_SCORE = 25
results = []

print("=" * 78)
print("BUILD MODEL BENCHMARK - Forge's real page-generation prompt")
print(f"All candidates open-weight | max_tokens={MAX_TOKENS} | scored out of {MAX_SCORE}")
print("=" * 78)

for label, provider, model in CANDIDATES:
    print(f"\n>>> {label}\n    {provider}/{model}")
    t0 = time.time()
    try:
        raw = complete(provider, model, PROMPT, MAX_TOKENS)
        dt = time.time() - t0
        html = _strip_html(raw)
        pts, notes = score(html)
        results.append((pts, dt, len(html), label, notes))
        print(f"    time {dt:6.1f}s | {len(html):6,} chars | SCORE {pts}/{MAX_SCORE}")
        if notes:
            print(f"    issues: {', '.join(notes[:6])}")
        else:
            print("    issues: none")
    except Exception as e:
        dt = time.time() - t0
        msg = str(e)[:150].replace("\n", " ")
        results.append((-1, dt, 0, label, [msg]))
        print(f"    FAILED after {dt:.1f}s: {msg}")

print("\n" + "=" * 78)
print("RANKING (quality first, then speed)")
print("=" * 78)
print(f"{'MODEL':<34}{'SCORE':>7}{'TIME':>9}{'SIZE':>10}")
print("-" * 78)
for pts, dt, size, label, notes in sorted(results, key=lambda r: (-r[0], r[1])):
    s = f"{pts}/{MAX_SCORE}" if pts >= 0 else "FAILED"
    print(f"{label:<34}{s:>7}{dt:>8.1f}s{size:>10,}")
print("=" * 78)
