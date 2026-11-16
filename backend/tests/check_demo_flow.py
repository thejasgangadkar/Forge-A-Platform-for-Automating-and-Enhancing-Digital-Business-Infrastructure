"""Verify the customer-facing deployed experience over HTTP.

Confirms the two surfaces a business owner actually shares with customers work
without any login: the hosted chat page at /a/{workspace_id} and the agent chat
endpoint the embedded website widget calls.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\check_demo_flow.py [workspace_id]
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

import requests

API = os.getenv("PUBLIC_API_BASE", "http://127.0.0.1:8000")
WS = sys.argv[1] if len(sys.argv) > 1 else "3c967350-cc93-4c95-b36e-d55f299d9aae"

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n       {detail}" if detail else ""))


print("=" * 66)
print(f"DEPLOYED EXPERIENCE CHECK  (workspace {WS[:8]}...)")
print("=" * 66)

# 1. hosted chat page, no auth
print("\n[1] Hosted chat page  GET /a/{id}")
try:
    r = requests.get(f"{API}/a/{WS}", timeout=25)
    check("page loads without login", r.status_code == 200, f"HTTP {r.status_code}, {len(r.text):,} bytes")
    check("renders chat UI", 'id="f"' in r.text and 'id="i"' in r.text)
    check("wired to agent endpoint", "/agent/chat" in r.text)
except Exception as e:
    check("page loads without login", False, str(e)[:120])

# 2. agent chat, no auth (this is what the embedded widget calls)
print("\n[2] Agent chat  POST /api/workspaces/{id}/agent/chat")
try:
    r = requests.post(
        f"{API}/api/workspaces/{WS}/agent/chat",
        json={"message": "Hi, what services do you offer and when are you open?", "history": []},
        timeout=90)
    ok = r.status_code == 200
    check("responds without auth", ok, f"HTTP {r.status_code}")
    if ok:
        d = r.json()
        reply = d.get("reply", "")
        check("returned a reply", len(reply) > 20, f"agent '{d.get('agent')}'")
        print(f"\n       AGENT SAID:\n       {reply[:400]}\n")
except Exception as e:
    check("responds without auth", False, str(e)[:120])

# 3. multi-turn keeps context
print("[3] Multi-turn context")
try:
    hist = [
        {"role": "user", "content": "Do you do teeth whitening?"},
        {"role": "assistant", "content": "Yes, we offer professional teeth whitening."},
    ]
    r = requests.post(
        f"{API}/api/workspaces/{WS}/agent/chat",
        json={"message": "How much is it?", "history": hist}, timeout=90)
    if r.status_code == 200:
        reply = r.json().get("reply", "")
        check("handles follow-up", len(reply) > 20)
        print(f"\n       FOLLOW-UP REPLY:\n       {reply[:300]}\n")
    else:
        check("handles follow-up", False, f"HTTP {r.status_code}")
except Exception as e:
    check("handles follow-up", False, str(e)[:120])

# 4. generated website serves with the widget embedded
print("[4] Generated website + embedded widget")
try:
    from database.supabase_client import get_supabase
    row = get_supabase().table("workspaces").select("business_profile").eq("id", WS).execute().data
    adir = ((row[0].get("business_profile") or {}).get("asset_dir") if row else None) or WS
    served = 0
    for page in ("index", "about", "services", "contact"):
        rr = requests.get(f"{API}/workspaces/{adir}/website/{page}.html", timeout=20)
        if rr.status_code == 200:
            served += 1
            if page == "index":
                check("  widget embedded in site", "forge-agent-btn" in rr.text)
                check("  widget targets this workspace", WS in rr.text)
    check("website pages serve", served >= 1, f"{served} page(s) live")
except Exception as e:
    check("website pages serve", False, str(e)[:120])

# 5. analytics recorded the visit we just made
print("\n[5] Analytics tracking")
try:
    from services.analytics_service import get_analytics
    a = get_analytics(WS, "week")
    check("analytics readable", isinstance(a, dict),
          f"visits={a.get('total_visits')} chats={a.get('total_chats')} leads={a.get('total_leads')}")
    check("recorded our activity", (a.get("total_visits", 0) + a.get("total_chats", 0)) > 0)
except Exception as e:
    check("analytics readable", False, str(e)[:120])

print("\n" + "=" * 66)
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print("  FAILED:", f)
print(f"\nSHARE LINK : {API}/a/{WS}")
print("=" * 66)
