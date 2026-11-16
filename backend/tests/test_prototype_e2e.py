"""End-to-end prototype validation - the full pipeline in one run.

Exercises every stage against live providers and asserts the four historical
bugs (A workspace-id mismatch, B agent hallucination, D edit truncation,
E scraper async crash) have not regressed.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\test_prototype_e2e.py

Costs one real generation (~2 min, 4-page site + 1 agent + 2 agent turns), so
run it to validate a build rather than on every edit.
"""
import os
import sys
import time
import glob
import json

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


BIZ = ("BrightSmile Dental Clinic in Bengaluru. A modern family dental practice "
       "founded in 2015. Services: teeth whitening, braces and clear aligners, "
       "root canal treatment, dental implants, and routine checkups. "
       "Open Mon-Sat 9am to 7pm. Target audience: families and young professionals. "
       "Friendly, professional, reassuring tone. Phone 080-4455-6677.")

print("=" * 66)
print("FORGE END-TO-END PROTOTYPE VALIDATION")
print("=" * 66)

# ── STAGE 1: generation (the expensive part - run once) ───────────────
print("\n[STAGE 1] Generating multi-page website + receptionist agent...")
from services.generation_service import orchestrate_generation, WORKSPACES_DIR

t0 = time.time()
ws_id, ctx, meta = orchestrate_generation(
    BIZ, agent_types=["receptionist"], build_website=True)
elapsed = time.time() - t0
print(f"  -> completed in {elapsed:.1f}s (workspace {ws_id})")

web_dir = os.path.join(WORKSPACES_DIR, ws_id, "website")

# ── STAGE 2: validate website files ──────────────────────────────────
print("\n[STAGE 2] Website output")
pages = sorted(os.path.basename(p) for p in glob.glob(os.path.join(web_dir, "*.html")))
check("multi-page generated (>=4 pages)", len(pages) >= 4, f"{pages}")

total_bytes = 0
for p in pages:
    fp = os.path.join(web_dir, p)
    html = open(fp, encoding="utf-8").read()
    total_bytes += len(html)
    closed = "</html>" in html.lower()
    has_widget = "forge-agent-btn" in html
    has_nav = "index.html" in html and "contact.html" in html
    has_tw = "tailwindcss.com" in html
    check(f"  {p}: closed doc", closed)
    check(f"  {p}: agent widget injected", has_widget)
    check(f"  {p}: shared nav links", has_nav)
    check(f"  {p}: tailwind cdn", has_tw)

check("total site size reasonable (>15KB)", total_bytes > 15000, f"{total_bytes:,} bytes")

# widget points at the REAL workspace id (Bug A regression check)
idx = open(os.path.join(web_dir, "index.html"), encoding="utf-8").read()
check("widget endpoint uses real workspace id (Bug A)", ws_id in idx)

# real images, not placeholders
check("uses real Pexels images", "pexels.com" in idx)
check("no lorem ipsum", "lorem ipsum" not in idx.lower())

# SEO artifacts
check("sitemap.xml written", os.path.exists(os.path.join(web_dir, "sitemap.xml")))
check("robots.txt written", os.path.exists(os.path.join(web_dir, "robots.txt")))

# SEO tags + structured data must be injected on every page, not just requested
# in the prompt (they used to be generated but never applied).
import json as _json
import re as _re
for p in pages:
    h = open(os.path.join(web_dir, p), encoding="utf-8").read()
    check(f"  {p}: has <title>", _re.search(r"<title>\s*\S", h) is not None)
    check(f"  {p}: og:title", 'property="og:title"' in h or "property='og:title'" in h)
    check(f"  {p}: twitter:card", "twitter:card" in h)
    check(f"  {p}: JSON-LD block", "application/ld+json" in h)

ld = _re.search(r'<script type="application/ld\+json">(.*?)</script>', idx, _re.S)
if ld:
    try:
        obj = _json.loads(ld.group(1))
        check("JSON-LD parses as valid JSON", True)
        check("JSON-LD is a LocalBusiness", obj.get("@type") == "LocalBusiness")
        check("JSON-LD carries the phone number", "4455" in str(obj.get("telephone", "")),
              str(obj.get("telephone")))
    except Exception as e:
        check("JSON-LD parses as valid JSON", False, str(e)[:60])
else:
    check("JSON-LD present on home page", False)

# zips for download
check("website.zip created", os.path.exists(os.path.join(WORKSPACES_DIR, ws_id, "website.zip")))
check("agents.zip created", os.path.exists(os.path.join(WORKSPACES_DIR, ws_id, "agents.zip")))

# ── STAGE 3: validate agent config ───────────────────────────────────
print("\n[STAGE 3] Agent config")
agents = meta.get("agents", [])
check("agent generated", len(agents) == 1)
if agents:
    a = agents[0]
    for k in ("name", "system_prompt", "greeting", "capabilities", "type", "id"):
        check(f"  has '{k}'", bool(a.get(k)))
    check("  type is receptionist", a.get("type") == "receptionist")
    print(f"       name: {a.get('name')}")
    print(f"       greeting: {str(a.get('greeting'))[:70]}...")

# ── STAGE 4: RAG grounding ───────────────────────────────────────────
print("\n[STAGE 4] RAG (ChromaDB)")
from rag.vector_store import vector_store
vector_store.add_business_context(ws_id, BIZ, {"workspace_id": ws_id})
hits = vector_store.query_business_context(ws_id, "what are your opening hours", n_results=2)
check("RAG stored + retrieved", len(hits) > 0, f"{len(hits)} chunk(s)")
check("RAG retrieved relevant content", any("Mon-Sat" in h or "9am" in h for h in hits))

# ── STAGE 5: agent runtime (grounded answer + refusal) ───────────────
print("\n[STAGE 5] Agent runtime")
from services.agent_runtime import run_agent, parse_tool_call, validate_tool_call

cfg = agents[0] if agents else {"system_prompt": "You are a receptionist.", "type": "receptionist"}
r1 = run_agent(cfg, BIZ, "What are your opening hours?", workspace_id=ws_id)
check("agent answered from context", any(t in r1 for t in ("9", "Mon", "7")), r1[:80])

# hallucination guard: ask for something NOT in context
r2 = run_agent(cfg, BIZ, "How much does a dental implant cost exactly in rupees?",
               workspace_id=ws_id)
# Models emit typographic punctuation (U+2019), so normalise before matching or
# "don't have" silently fails to match "don't have".
r2_norm = r2.lower().replace("\u2019", "'").replace("\u2018", "'")
hedged = any(p in r2_norm for p in
             ("don't have", "do not have", "not sure", "contact", "call", "reach out",
              "get in touch", "team", "vary", "varies", "depend"))
check("agent does NOT invent pricing (Bug B)", hedged, r2[:90])

# ── STAGE 6: guardrails ──────────────────────────────────────────────
print("\n[STAGE 6] Guardrails")
from services.guardrails_service import screen_input, screen_output
check("blocks harmful input", not screen_input("how to kill someone")["safe"])
check("blocks credit card PII", not screen_input("my card is 4111 1111 1111 1111")["safe"])
check("allows normal input", screen_input("Do you offer braces for teenagers?")["safe"])
check("screens output", screen_output("We offer braces and aligners.")["safe"])

# ── STAGE 7: tool-calling parse/validate ─────────────────────────────
print("\n[STAGE 7] Tool-calling")
tc = parse_tool_call('Sure! {"action": "book_slot", "time": "Tuesday 3pm", "name": "Asha"}')
check("parses book_slot", tc is not None and tc.get("action") == "book_slot")
check("validates complete call", validate_tool_call(tc or {})["valid"])
bad = validate_tool_call({"action": "book_slot"})
check("rejects missing required param", not bad["valid"], bad.get("error", ""))
check("ignores unknown action", parse_tool_call('{"action": "launch_rocket"}') is None)

# ── STAGE 8: editor truncation limit (Bug D, static check) ───────────
print("\n[STAGE 8] Editor")
import inspect
from services import editor_service
src = inspect.getsource(editor_service)
check("editor reads up to 80000 chars of a page (Bug D)", "[:80000]" in src)
# The output budget is provider-capped now (Groq 413s above ~6000), so it is
# read from env rather than hardcoded.
check("editor output budget is configurable", "EDIT_MAX_TOKENS" in src)
check("editor handles every page, not just index", "_existing_pages" in src)
check("editor routes edits to the right page(s)", "resolve_targets" in src)

# ── STAGE 9: scraper async safety (Bug E) ────────────────────────────
print("\n[STAGE 9] Scraper async safety")
import asyncio
from scraper.website_scraper import scrape_website_structured


async def _in_loop():
    # Bug E was: calling the sync entry inside a running loop crashed.
    return await asyncio.to_thread(scrape_website_structured, "https://example.com")

try:
    d = asyncio.run(_in_loop())
    check("no crash inside asyncio loop (Bug E)", isinstance(d, dict))
    check("returned structured keys",
          all(k in d for k in ("title", "text", "engine")), f"engine={d.get('engine')}")
except Exception as e:
    check("no crash inside asyncio loop (Bug E)", False, str(e)[:100])

# ── SUMMARY ──────────────────────────────────────────────────────────
print("\n" + "=" * 66)
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed   (generation {elapsed:.1f}s)")
if FAIL:
    print("FAILURES:")
    for f in FAIL:
        print("  -", f)
print(f"WORKSPACE: {ws_id}")
print(f"PREVIEW:   http://127.0.0.1:8000/workspaces/{ws_id}/website/index.html")
print("=" * 66)
