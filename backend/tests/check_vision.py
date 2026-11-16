"""Verify vision analysis of scraped screenshots (FR-5.1 website enhancement).

Offline checks confirm the graceful-degradation contract and prompt formatting.
Pass --live to run a real screenshot through the vision model.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\check_vision.py [--live]
"""
import glob
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


print("=" * 72)
print("VISION ANALYSIS (FR-5.1 website enhancement)")
print("=" * 72)

from services import vision_service as vs

# ── availability + config ─────────────────────────────────────────────
print("\n[1] Configuration")
check("vision is available", vs.is_available(),
      f"{vs.VISION_PROVIDER}/{vs.VISION_MODEL}")
check("model is env-overridable", os.getenv("VISION_MODEL") is not None)
check("can be switched off", "VISION_ENABLED" in open(
    os.path.join("services", "vision_service.py"), encoding="utf-8").read())

# ── graceful degradation: the important contract ──────────────────────
print("\n[2] Degrades gracefully (never breaks generation)")
check("missing file returns {}", vs.analyze_screenshot("does/not/exist.png") == {})
check("empty path returns {}", vs.analyze_screenshot("") == {})
check("None path returns {}", vs.analyze_screenshot(None) == {})

os.makedirs("_vis_tmp", exist_ok=True)
empty = os.path.join("_vis_tmp", "empty.png")
open(empty, "wb").close()
check("zero-byte file returns {}", vs.analyze_screenshot(empty) == {})

prev = os.environ.get("VISION_ENABLED")
os.environ["VISION_ENABLED"] = "false"
check("disabling VISION_ENABLED turns it off", not vs.is_available())
if prev is None:
    os.environ.pop("VISION_ENABLED", None)
else:
    os.environ["VISION_ENABLED"] = prev

# ── prompt formatting ─────────────────────────────────────────────────
print("\n[3] Prompt formatting")
check("empty analysis yields no prompt text", vs.format_for_prompt({}) == "")
sample = {
    "palette": ["#0a3d62", "#f5f6fa"],
    "layout": "Narrow single column with a small hero",
    "style": "dated corporate",
    "typography": "Times New Roman, cramped",
    "imagery": "low-resolution stock photos",
    "strengths": ["recognisable navy brand colour"],
    "weaknesses": ["tiny text", "no mobile layout"],
    "recommendations": ["full-width hero", "modern sans-serif"],
}
block = vs.format_for_prompt(sample)
for fragment in ("#0a3d62", "dated corporate", "KEEP these strengths",
                 "FIX these problems", "tiny text", "full-width hero"):
    check(f"  block carries '{fragment[:26]}'", fragment in block)
check("  instructs a clear improvement", "BETTER" in block)

# ── normalisation guards against a sloppy model ───────────────────────
print("\n[4] Normalises messy model output")
messy = vs._normalise({
    "palette": ["#fff", "not-a-colour", "#123456", "#abc", "#def", "#999"],
    "layout": "x" * 400,
    "strengths": "a single string not a list",
    "weaknesses": ["a", "", "  ", "b", "c", "d", "e"],
    "recommendations": None,
})
check("drops non-hex colours", all(c.startswith("#") for c in messy["palette"]),
      str(messy["palette"]))
check("caps palette at 4", len(messy["palette"]) <= 4, str(len(messy["palette"])))
check("truncates long text", len(messy["layout"]) <= 200)
check("wraps a bare string into a list", messy["strengths"] == ["a single string not a list"])
check("drops blank entries and caps lists", len(messy["weaknesses"]) <= 4,
      str(messy["weaknesses"]))
check("None becomes an empty list", messy["recommendations"] == [])
check("records which model ran", messy["model"] == vs.VISION_MODEL)

# ── downscaling large screenshots ─────────────────────────────────────
print("\n[5] Large screenshots are downscaled to fit inline")
shots = sorted(glob.glob(os.path.join("generated_workspaces", "_scrape_shots", "*.png")),
               key=os.path.getsize, reverse=True)
if shots:
    biggest = shots[0]
    size = os.path.getsize(biggest)
    print(f"      largest available: {os.path.basename(biggest)} ({size:,} bytes)")
    encoded = vs._encode_image(biggest)
    if size > vs.MAX_IMAGE_BYTES:
        check("oversized screenshot still encodes", encoded is not None,
              "downscaled" if encoded else "skipped")
        if encoded:
            raw_len = len(encoded[0]) * 3 // 4
            check("  fits the size budget", raw_len <= vs.MAX_IMAGE_BYTES,
                  f"{raw_len:,} <= {vs.MAX_IMAGE_BYTES:,}")
            check("  re-encoded as JPEG", encoded[1] == "image/jpeg")
    else:
        check("small screenshot encodes directly", encoded is not None)
else:
    skip("downscaling", "no screenshots on disk")

# ── wiring: must not be dead code ─────────────────────────────────────
print("\n[6] Wired into the enhancement path")
chat_src = open(os.path.join("services", "chat_service.py"), encoding="utf-8").read()
check("scraper output is analysed", "analyze_screenshot" in chat_src)
check("analysis is cached with the scrape", '"vision": vision' in chat_src)
main_src = open("main.py", encoding="utf-8").read()
check("generate reads the cached analysis", "format_for_prompt" in main_src)
check("design notes passed to generation", "design_notes=design_notes" in main_src)
gen_src = open(os.path.join("services", "generation_service.py"), encoding="utf-8").read()
check("orchestrator accepts design notes", 'design_notes: str = ""' in gen_src)
check("notes reach the one-shot prompt", "context[:2500] + notes" in gen_src)
check("notes reach the per-page prompt", "context + notes" in gen_src)

# ── live model call ───────────────────────────────────────────────────
print("\n[7] Live analysis")
if LIVE and shots:
    target = next((s for s in shots if os.path.getsize(s) > 50_000), shots[0])
    print(f"      analysing {os.path.basename(target)}...")
    result = vs.analyze_screenshot(target)
    if result:
        check("returned an analysis", True, f"model {result.get('model')}")
        check("  has a style judgement", bool(result.get("style")), result.get("style"))
        check("  has a layout description", bool(result.get("layout")))
        check("  found weaknesses to fix", len(result.get("weaknesses", [])) > 0)
        check("  produced recommendations", len(result.get("recommendations", [])) > 0)
        print(f"\n       style   : {result.get('style')}")
        print(f"       layout  : {result.get('layout')}")
        print(f"       palette : {result.get('palette')}")
        print(f"       weak    : {result.get('weaknesses')}")
        print(f"       fix     : {result.get('recommendations')}\n")
        check("  formats into a usable prompt block",
              len(vs.format_for_prompt(result)) > 80)
    else:
        check("returned an analysis", False,
              "empty - model unavailable or returned unusable JSON")
elif LIVE:
    skip("live analysis", "no screenshots on disk")
else:
    skip("live analysis", "pass --live to run (1 vision call)")

# cleanup
try:
    os.remove(empty)
    os.rmdir("_vis_tmp")
except Exception:
    pass

print("\n" + "=" * 72)
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped")
for f in FAIL:
    print("  FAILED:", f)
print("=" * 72)
