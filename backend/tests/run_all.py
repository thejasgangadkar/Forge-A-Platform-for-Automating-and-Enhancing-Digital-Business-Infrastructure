"""Run every Forge verification suite and summarise the result.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\run_all.py            # fast: no LLM spend
    .\\venv\\Scripts\\python.exe tests\\run_all.py --live      # adds live model calls
    .\\venv\\Scripts\\python.exe tests\\run_all.py --full      # adds a real generation (~3 min)

Default mode deliberately skips anything that spends tokens, so it can be run
after every change. The backend must be running on port 8000 for the suites that
exercise HTTP endpoints.
"""
import os
import re
import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND)

PYTHON = os.path.join(BACKEND, "venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable

LIVE = "--live" in sys.argv
FULL = "--full" in sys.argv

# (script, extra args, description, cost tier)
SUITES = [
    ("check_providers.py", [], "API keys and provider reachability", "cheap"),
    ("check_fallback_chain.py", ["--live"] if LIVE else [],
     "Multi-provider fallback chain", "free"),
    ("check_config_and_fixes.py", [], "Config tuning and defensive fixes", "free"),
    ("check_prd_features.py", ["--live"] if LIVE else [],
     "PRD functional requirements", "free"),
    ("check_channels.py", ["--live"] if LIVE else [],
     "Channel adapter layer", "free"),
    ("check_vision.py", ["--live"] if LIVE else [],
     "Vision analysis of screenshots", "free"),
    ("check_multilanguage.py", ["--live"] if LIVE else [],
     "Multi-language input, output and voice", "free"),
    ("check_rate_limit.py", [], "Public endpoint rate limiting", "free"),
    ("check_demo_flow.py", [], "Customer-facing surfaces over HTTP", "cheap"),
]

if FULL:
    SUITES.append(("test_prototype_e2e.py", [], "Full generation pipeline", "expensive"))

RESULT_RE = re.compile(r"RESULT:\s*(\d+)\s*passed,\s*(\d+)\s*failed(?:,\s*(\d+)\s*skipped)?")
SUMMARY_RE = re.compile(r"(ALL PROVIDERS LIVE|NEEDS ATTENTION:.*)")


def run(script: str, args: list[str]) -> tuple[int, int, int, str]:
    """Run one suite. Returns (passed, failed, skipped, tail_output)."""
    path = os.path.join("tests", script)
    if not os.path.exists(path):
        return 0, 0, 0, "script missing"
    try:
        proc = subprocess.run(
            [PYTHON, path, *args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=900,
        )
    except subprocess.TimeoutExpired:
        return 0, 1, 0, "TIMED OUT"

    out = (proc.stdout or "") + (proc.stderr or "")
    m = RESULT_RE.search(out)
    if m:
        return (int(m.group(1)), int(m.group(2)),
                int(m.group(3) or 0), _failures(out))

    # check_providers reports differently
    s = SUMMARY_RE.search(out)
    if s:
        text = s.group(1)
        live = len(re.findall(r"^\[LIVE\]", out, re.M))
        fail = len(re.findall(r"^\[FAIL\]", out, re.M))
        return live, fail, 0, "" if text.startswith("ALL") else text

    return 0, 1, 0, f"no parsable result (exit {proc.returncode})"


def _failures(out: str) -> str:
    """Extract failing check names.

    Matches only the explicit failure markers the suites emit. An earlier version
    also matched any line starting with "- ", which picked up agent reply text and
    reported passing suites as if they had failures.
    """
    names = re.findall(r"^\s*(?:FAILED:\s*|\[FAIL\]\s*)(.+)$", out, re.M)
    uniq, seen = [], set()
    for n in names:
        n = n.strip()
        if n and n not in seen:
            seen.add(n)
            uniq.append(n)
    return "; ".join(uniq[:6])


mode = "FULL (real generation)" if FULL else "LIVE (model calls)" if LIVE else "FAST (no token spend)"
print("=" * 78)
print(f"FORGE VERIFICATION SUITE  -  mode: {mode}")
print("=" * 78)

rows, t_start = [], time.time()
for script, args, desc, tier in SUITES:
    label = f"{desc}"
    print(f"\n>>> {label}  ({script}{' ' + ' '.join(args) if args else ''})")
    t0 = time.time()
    passed, failed, skipped, detail = run(script, args)
    dt = time.time() - t0
    ok = failed == 0 and passed > 0
    rows.append((ok, label, passed, failed, skipped, dt, detail))
    status = "OK" if ok else "FAIL"
    extra = f", {skipped} skipped" if skipped else ""
    print(f"    [{status}] {passed} passed, {failed} failed{extra}  ({dt:.1f}s)")
    if detail:
        print(f"    -> {detail}")

total_p = sum(r[2] for r in rows)
total_f = sum(r[3] for r in rows)
total_s = sum(r[4] for r in rows)

print("\n" + "=" * 78)
print("SUMMARY")
print("=" * 78)
print(f"{'SUITE':<42}{'PASS':>6}{'FAIL':>6}{'SKIP':>6}{'TIME':>9}")
print("-" * 78)
for ok, label, p, f, s, dt, _ in rows:
    print(f"{label[:42]:<42}{p:>6}{f:>6}{s:>6}{dt:>8.1f}s")
print("-" * 78)
print(f"{'TOTAL':<42}{total_p:>6}{total_f:>6}{total_s:>6}{time.time() - t_start:>8.1f}s")
print("=" * 78)

if total_f:
    print("\nFAILING SUITES:")
    for ok, label, p, f, s, dt, detail in rows:
        if not ok:
            print(f"  - {label}: {detail or f'{f} failed'}")
    print()
    sys.exit(1)

print("\nAll suites green.")
if not FULL:
    print("Note: the full generation pipeline was not exercised. "
          "Run with --full before a demo or submission.")
sys.exit(0)
