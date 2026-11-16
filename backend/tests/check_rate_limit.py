"""Verify rate limiting on the public, unauthenticated endpoints.

Hits the hosted page endpoint past its configured limit and asserts it starts
returning 429 with a Retry-After header, then confirms a legitimate first
request is still allowed (i.e. the limiter is not simply blocking everything).

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\check_rate_limit.py
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

API = "http://127.0.0.1:8000"
WS = sys.argv[1] if len(sys.argv) > 1 else "3c967350-cc93-4c95-b36e-d55f299d9aae"
PAGE_LIMIT = int(os.getenv("RATE_LIMIT_PAGE", "60"))

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


print("=" * 70)
print("RATE LIMIT CHECK - public endpoints")
print(f"configured: page={PAGE_LIMIT}/window, chat={os.getenv('RATE_LIMIT_CHAT')}/window")
print("=" * 70)

# The limiter is keyed per IP+scope+workspace. Use a throwaway workspace id so
# this test cannot exhaust the budget of a workspace used for demos.
probe_ws = "rate-limit-probe-0000"

print(f"\nSending {PAGE_LIMIT + 8} rapid requests to /a/{{probe}}...")
codes = []
first_429_at = None
retry_after = None
for n in range(PAGE_LIMIT + 8):
    try:
        r = requests.get(f"{API}/a/{probe_ws}", timeout=15)
        codes.append(r.status_code)
        if r.status_code == 429 and first_429_at is None:
            first_429_at = n + 1
            retry_after = r.headers.get("Retry-After")
    except Exception as e:
        codes.append(f"ERR {str(e)[:30]}")

n429 = sum(1 for c in codes if c == 429)
# Requests that got past the limiter reach the handler, which returns 404 for an
# id that does not exist. A 500 here means a malformed id is crashing the
# handler instead of being rejected cleanly.
n_reached = sum(1 for c in codes if c == 404)
n500 = sum(1 for c in codes if c == 500)

check("limiter triggers under flood", n429 > 0, f"{n429} of {len(codes)} got 429")
check("allows traffic before the limit", n_reached > 0,
      f"{n_reached} reached the handler and got a clean 404")
check("unknown id returns 404, not 500", n500 == 0, f"{n500} server errors")
check("blocks at the configured threshold", first_429_at is not None and first_429_at > PAGE_LIMIT,
      f"first 429 on request #{first_429_at} (limit {PAGE_LIMIT})")
check("sends Retry-After header", retry_after is not None, f"Retry-After: {retry_after}")

# A different workspace id must have its own budget - one busy workspace should
# not lock every other business out of the platform.
print("\nConfirming isolation between workspaces...")
try:
    r = requests.get(f"{API}/a/rate-limit-probe-9999", timeout=15)
    check("separate workspace unaffected", r.status_code != 429, f"HTTP {r.status_code}")
    check("  and answers cleanly", r.status_code == 404, f"HTTP {r.status_code}")
except Exception as e:
    check("separate workspace unaffected", False, str(e)[:80])

# The authenticated app surface must not be limited by the public rules.
print("\nConfirming the app's own API is unaffected...")
try:
    r = requests.get(f"{API}/api/health", timeout=15)
    check("health endpoint still open", r.status_code == 200, f"HTTP {r.status_code}")
except Exception as e:
    check("health endpoint still open", False, str(e)[:80])

print("\n" + "=" * 70)
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
for f in FAIL:
    print("  FAILED:", f)
print("=" * 70)
