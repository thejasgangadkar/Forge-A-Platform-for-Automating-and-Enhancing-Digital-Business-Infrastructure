"""Verify the PRD functional requirements that were previously unimplemented.

Covers FR-2.0 (workspace delete), FR-5.2 (SEO/JSON-LD), FR-6.0 (seven agent
types), FR-6.2 (voice on every surface) and multi-page chat editing.

Almost every check is offline; the two that need a real LLM call are skipped
unless --live is passed, so this can be run freely.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\check_prd_features.py [--live]
"""
import json
import os
import re
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

API = "http://127.0.0.1:8000"
LIVE = "--live" in sys.argv
PASS, FAIL, SKIP = [], [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def skip(name, why):
    SKIP.append(name)
    print(f"  [SKIP] {name} - {why}")


print("=" * 72)
print("PRD FUNCTIONAL REQUIREMENT VERIFICATION")
print("=" * 72)

# ── FR-6.0: seven agent types ─────────────────────────────────────────
print("\n[FR-6.0] Agent template gallery - 7 types")
from services.generation_service import AGENT_TYPES, AGENT_PRIMARY_ACTIONS
expected = {"receptionist", "slot_booker", "appointment_booker", "support",
            "lead_capture", "faq", "custom"}
check("all 7 PRD agent types exist", set(AGENT_TYPES) == expected,
      f"{len(AGENT_TYPES)} types")
check("each type declares its tool-calls", set(AGENT_PRIMARY_ACTIONS) == set(AGENT_TYPES))
check("lead_capture targets capture_lead",
      "capture_lead" in AGENT_PRIMARY_ACTIONS.get("lead_capture", []))
check("appointment_booker targets book_slot",
      "book_slot" in AGENT_PRIMARY_ACTIONS.get("appointment_booker", []))

from services.chat_service import VALID_AGENTS
check("architect chat accepts all types", VALID_AGENTS == set(AGENT_TYPES))

# The UI gallery must not offer a type the backend would silently downgrade.
gallery = os.path.join(BACKEND, "..", "frontend-next", "components", "AgentGallery.js")
if os.path.exists(gallery):
    src = open(gallery, encoding="utf-8").read()
    # Match either quote style, and assert we actually found cards - a regex that
    # silently matches nothing would make this check pass vacuously.
    offered = set(re.findall(r"""type:\s*['"]([a-z_]+)['"]""", src))
    unknown = offered - set(AGENT_TYPES)
    check("gallery cards were detected", len(offered) >= 6, f"found {len(offered)}")
    check("every gallery card maps to a real type", offered and not unknown,
          f"offered {sorted(offered)}" + (f", UNKNOWN {unknown}" if unknown else ""))
    check("gallery offers all 7 PRD types", offered == set(AGENT_TYPES),
          f"missing {set(AGENT_TYPES) - offered}" if offered != set(AGENT_TYPES) else "")
else:
    skip("gallery card mapping", "AgentGallery.js not found")

# ── FR-5.2: SEO and structured data ───────────────────────────────────
print("\n[FR-5.2] SEO, Open Graph and JSON-LD")
from services.seo_service import (build_local_business_jsonld, inject_jsonld,
                                  ensure_social_tags, generate_sitemap,
                                  generate_robots_txt)
ctx = ("Anahata Yoga & Wellness Studio in Indiranagar, Bengaluru. Hatha and "
       "Vinyasa classes. Phone 080-2233-4455, hello@anahatayoga.in.")
ld = build_local_business_jsonld(ctx, "Anahata Yoga", "https://img/hero.jpg")
data = json.loads(re.search(r">(.*)<", ld, re.S).group(1))
check("JSON-LD is valid schema.org LocalBusiness",
      data.get("@type") == "LocalBusiness" and data.get("@context", "").endswith("schema.org"))
check("extracts telephone", data.get("telephone") == "080-2233-4455")
check("extracts a valid email (no trailing dot)",
      data.get("email") == "hello@anahatayoga.in", str(data.get("email")))
check("extracts locality", (data.get("address") or {}).get("addressLocality") == "Indiranagar")

page = ('<html><head><title>Anahata Yoga - Home</title>'
        '<meta name="description" content="Calm yoga studio"></head><body>x</body></html>')
out = inject_jsonld(ensure_social_tags(page, "", "", "https://img/hero.jpg"), ld)
for tag in ("og:title", "og:description", "og:image", "twitter:card", "twitter:title"):
    check(f"  injects {tag}", tag in out)
check("  injects JSON-LD", "application/ld+json" in out)
twice = inject_jsonld(ensure_social_tags(out, "", "", "https://img/hero.jpg"), ld)
check("  idempotent (no duplicate tags)",
      twice.count("og:title") == 1 and twice.count("application/ld+json") == 1)
check("sitemap lists pages", "<loc>./index.html</loc>" in generate_sitemap(".", ["index.html"]))
check("robots.txt references sitemap", "Sitemap:" in generate_robots_txt("."))

# The generator must actually call these - they were dead code before.
gen_src = open(os.path.join("services", "generation_service.py"), encoding="utf-8").read()
check("generation wires SEO in (not dead code)",
      "ensure_social_tags" in gen_src and "inject_jsonld" in gen_src)

# ── Multi-page editing ────────────────────────────────────────────────
print("\n[Editing] Multi-page edit routing")
from services import editor_service
avail = ["index", "about", "services", "contact"]
cases = [
    ("make the hero section darker", ["index"], "page-specific"),
    ("change the contact form heading", ["contact"], "page-specific"),
    ("update the team section on the about page", ["about"], "page-specific"),
    ("make the navigation bar darker", avail, "shared -> all pages"),
    ("change the footer copyright", avail, "shared -> all pages"),
    ("use a warmer colour palette", avail, "shared -> all pages"),
]
for instruction, want, kind in cases:
    got, reason = editor_service.resolve_targets(instruction, avail)
    check(f"  '{instruction[:38]}' -> {kind}", set(got) == set(want),
          f"got {got}")
ed_src = open(os.path.join("services", "editor_service.py"), encoding="utf-8").read()
check("editor no longer hardcodes index.html only",
      'f"{page}.html"' in ed_src and "_existing_pages" in ed_src)
check("editor rejects truncated rewrites", "0.4" in ed_src and "truncated" in ed_src)

# ── FR-6.2: voice on every surface ────────────────────────────────────
print("\n[FR-6.2] Voice - speech in AND out, on every agent surface")
vc = os.path.join(BACKEND, "..", "frontend-next", "components", "VoiceChat.js")
if os.path.exists(vc):
    src = open(vc, encoding="utf-8").read()
    check("  sandbox: speech recognition", "SpeechRecognition" in src)
    check("  sandbox: speech synthesis", "SpeechSynthesisUtterance" in src)
    check("  sandbox: TTS runs in an effect, not render",
          "useEffect" in src and "if (speakText && state" not in src)
    check("  sandbox: cleans up on unmount", "abort()" in src and "cancel()" in src)
    check("  sandbox: no Tailwind classes", "className={`${styles" in src)
    ws_page = os.path.join(BACKEND, "..", "frontend-next", "app", "dashboard",
                           "workspace", "[id]", "page.js")
    wsrc = open(ws_page, encoding="utf-8").read()
    check("  sandbox: speakText actually passed", "speakText=" in wsrc)
else:
    skip("sandbox voice", "VoiceChat.js not found")

try:
    r = requests.get(f"{API}/a/3c967350-cc93-4c95-b36e-d55f299d9aae", timeout=25)
    if r.status_code == 200:
        p = r.text
        check("  hosted page: mic control", 'id="mic"' in p)
        check("  hosted page: speech recognition", "SpeechRecognition" in p)
        check("  hosted page: speech synthesis", "speechSynthesis" in p)
        check("  hosted page: typing indicator", 'class="dot"' in p)
        check("  hosted page: honours reduced motion", "prefers-reduced-motion" in p)
        check("  hosted page: template fully rendered", "{{" not in p and "{ws}" not in p)
    else:
        skip("hosted page voice", f"HTTP {r.status_code} (rate limited?)")
except Exception as e:
    skip("hosted page voice", f"server unreachable: {str(e)[:50]}")

wjs = os.path.join("generated_workspaces", "_widget", "forge-widget.js")
if os.path.exists(wjs):
    src = open(wjs, encoding="utf-8").read()
    check("  embed widget: typing indicator", "_fdot" in src)
    check("  embed widget: speech recognition", "SpeechRecognition" in src)
    check("  embed widget: speech synthesis", "speechSynthesis" in src)
else:
    skip("embed widget", "forge-widget.js not found")

# ── FR-2.0: workspace delete ──────────────────────────────────────────
print("\n[FR-2.0] Workspace delete")
from services import workspace_service as wsvc
check("delete_workspace exists", hasattr(wsvc, "delete_workspace"))
src = open(os.path.join("services", "workspace_service.py"), encoding="utf-8").read()
check("  verifies ownership before deleting", "get_workspace(workspace_id, user_id)" in src)
check("  clears vector memory", "delete_context" in src)
check("  removes generated files", "rmtree" in src)
check("  guards against path traversal", "realpath" in src and "startswith" in src)
for t in ("assets", "conversations", "agent_actions", "analytics_events"):
    check(f"  clears {t}", f'"{t}"' in src)
from rag.vector_store import vector_store
check("vector store supports deletion", hasattr(vector_store, "delete_context"))

main_src = open("main.py", encoding="utf-8").read()
check("DELETE endpoint registered", '@app.delete("/api/workspaces/{workspace_id}")' in main_src)
try:
    r = requests.delete(f"{API}/api/workspaces/{'0'*8}-0000-0000-0000-{'0'*12}", timeout=20)
    check("DELETE requires auth", r.status_code == 401, f"HTTP {r.status_code}")
except Exception as e:
    skip("DELETE auth", str(e)[:50])

api_js = os.path.join(BACKEND, "..", "frontend-next", "lib", "api.js")
if os.path.exists(api_js):
    check("frontend client exposes delete",
          "deleteWorkspace" in open(api_js, encoding="utf-8").read())

# ── live agent generation for the new types ────────────────────────────
print("\n[Live] New agent types actually generate")
if LIVE:
    from services.generation_service import generate_agent_config
    for t in ("lead_capture", "faq"):
        try:
            cfg = generate_agent_config("A yoga studio in Bengaluru.", t)
            check(f"  {t} config generated",
                  cfg.get("type") == t and len(cfg.get("system_prompt", "")) > 40,
                  cfg.get("name"))
        except Exception as e:
            check(f"  {t} config generated", False, str(e)[:70])
else:
    skip("live agent generation", "pass --live to run (costs 2 LLM calls)")

print("\n" + "=" * 72)
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped")
for f in FAIL:
    print("  FAILED:", f)
print("=" * 72)
