"""Compare NIM vision models on speed and JSON compliance for our real prompt.

The 90B model named in the PRD proved too slow on the free tier for a
user-facing flow, so this measures the smaller alternatives on an actual scraped
screenshot before choosing a default.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\bench_vision_models.py
"""
import glob
import os
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
from services import vision_service as vs

CANDIDATES = [
    "meta/llama-3.2-11b-vision-instruct",
    "nvidia/nemotron-nano-12b-v2-vl",
    "microsoft/phi-3-vision-128k-instruct",
    "meta/llama-3.2-90b-vision-instruct",
]
TIMEOUT = 75

shots = sorted(glob.glob(os.path.join("generated_workspaces", "_scrape_shots", "*.png")),
               key=os.path.getsize, reverse=True)
target = next((s for s in shots if os.path.getsize(s) > 50_000), shots[0] if shots else None)
if not target:
    print("No screenshots on disk to test with.")
    sys.exit(1)

encoded = vs._encode_image(target)
if not encoded:
    print("Could not encode the screenshot.")
    sys.exit(1)
b64, mime = encoded

print("=" * 74)
print("NIM VISION MODEL BENCHMARK")
print(f"image: {os.path.basename(target)} -> {mime}, {len(b64) * 3 // 4:,} bytes")
print("=" * 74)

client = OpenAI(api_key=os.getenv("NVIDIA_API_KEY"),
                base_url="https://integrate.api.nvidia.com/v1",
                timeout=TIMEOUT, max_retries=0)

results = []
for model in CANDIDATES:
    print(f"\n>>> {model}")
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": vs.PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}],
            max_tokens=700, temperature=0.3)
        dt = time.time() - t0
        raw = r.choices[0].message.content or ""
        parsed = vs._safe_json(raw)
        norm = vs._normalise(parsed) if parsed else {}
        useful = bool(norm.get("style") and norm.get("weaknesses"))
        results.append((useful, dt, model, len(raw)))
        print(f"    {dt:5.1f}s | {len(raw):4d} chars | JSON: {'yes' if parsed else 'NO'}"
              f" | usable: {'yes' if useful else 'no'}")
        if parsed:
            print(f"    style: {norm.get('style')}")
            print(f"    palette: {norm.get('palette')}")
            print(f"    weaknesses: {norm.get('weaknesses')}")
        else:
            print(f"    RAW: {raw[:200]!r}")
    except Exception as e:
        dt = time.time() - t0
        results.append((False, dt, model, 0))
        print(f"    FAILED after {dt:.1f}s - {str(e)[:110]}")

print("\n" + "=" * 74)
print("RANKING (usable output first, then speed)")
print("=" * 74)
for useful, dt, model, n in sorted(results, key=lambda r: (not r[0], r[1])):
    print(f"  {'OK  ' if useful else 'BAD '} {dt:6.1f}s  {model}")
print("=" * 74)
