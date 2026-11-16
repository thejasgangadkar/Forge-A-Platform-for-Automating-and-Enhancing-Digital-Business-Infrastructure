"""Verify the channel-adapter layer is real and in the live request path.

The point of this test is to catch the failure mode where an abstraction exists
but nothing uses it. It asserts the adapter contract, that each Phase-2 channel
genuinely parses its provider's payload shape, and — most importantly — that a
real agent reply still comes back through the adapter.

    cd forge/backend
    .\\venv\\Scripts\\python.exe tests\\check_channels.py [--live]
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
LIVE = "--live" in sys.argv
WS = "3c967350-cc93-4c95-b36e-d55f299d9aae"
PASS, FAIL, SKIP = [], [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def skip(name, why):
    SKIP.append(name)
    print(f"  [SKIP] {name} - {why}")


def raises(fn, exc) -> bool:
    """True when calling fn() raises exc."""
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:
        return False


print("=" * 72)
print("CHANNEL ADAPTER LAYER")
print("=" * 72)

import channels
from channels.base import ChannelAdapter, ChannelNotConfigured, InboundMessage, OutboundMessage

# ── contract ──────────────────────────────────────────────────────────
print("\n[1] Adapter contract")
names = {c["name"] for c in channels.list_channels()}
check("all four channels registered",
      names == {"web", "whatsapp", "telegram", "gmail"}, str(sorted(names)))
for n in sorted(names):
    a = channels.get_adapter(n)
    check(f"  {n} implements the interface",
          isinstance(a, ChannelAdapter)
          and callable(a.parse_inbound) and callable(a.format_outbound))
check("shared pipeline lives on the base class",
      "handle_turn" in ChannelAdapter.__dict__,
      "so channels cannot diverge on agent logic")
check("unknown channel rejected",
      raises(lambda: channels.get_adapter("carrier-pigeon"), KeyError))

# ── readiness reporting ───────────────────────────────────────────────
print("\n[2] Readiness is reported honestly")
web = channels.get_adapter("web")
check("web is enabled and configured", web.enabled and web.is_configured())
check("web is the active channel", channels.enabled_channels() == ["web"],
      str(channels.enabled_channels()))
for n in ("whatsapp", "telegram", "gmail"):
    a = channels.get_adapter(n)
    check(f"  {n} reported as planned, not live", not a.enabled)
    check(f"  {n} refuses to send without credentials",
          raises(lambda adapter=a: adapter.send(OutboundMessage(text="hi"), "someone"),
                 ChannelNotConfigured))

# ── payload translation ───────────────────────────────────────────────
print("\n[3] Each channel parses its provider's real payload shape")
m = web.parse_inbound({
    "workspace_id": "w1", "message": "  hello  ", "agent_id": "a1",
    "history": [{"role": "user", "content": "hi"},
                {"role": "bad"}, "not-a-dict"],
})
check("web: trims text", m.text == "hello")
check("web: drops malformed history turns", len(m.history) == 1, f"{m.history}")
check("web: response shape unchanged for existing clients",
      set(web.format_outbound(OutboundMessage(text="x", agent_name="A"))) ==
      {"reply", "agent", "tool_call"})

wa = channels.get_adapter("whatsapp")
m = wa.parse_inbound({"workspace_id": "w1", "entry": [{"changes": [{"value": {
    "messages": [{"from": "919812345678", "text": {"body": "Do you do braces?"}}]}}]}]})
check("whatsapp: extracts text from nested webhook", m.text == "Do you do braces?")
check("whatsapp: extracts sender", m.sender_id == "919812345678")
check("whatsapp: survives a status-only callback",
      wa.parse_inbound({"entry": [{"changes": [{"value": {"statuses": [{}]}}]}]}).text == "")
os.environ["WHATSAPP_VERIFY_TOKEN"] = "tok"
check("whatsapp: answers Meta's verification handshake",
      wa.verify_webhook({"hub.mode": "subscribe", "hub.verify_token": "tok",
                         "hub.challenge": "42"}) == "42")
check("whatsapp: rejects a bad verify token",
      wa.verify_webhook({"hub.mode": "subscribe", "hub.verify_token": "no",
                         "hub.challenge": "42"}) is None)

tg = channels.get_adapter("telegram")
m = tg.parse_inbound({"workspace_id": "w1",
                      "message": {"chat": {"id": 55501}, "text": "what are your hours?"}})
check("telegram: extracts text", m.text == "what are your hours?")
check("telegram: extracts chat id", m.sender_id == "55501")

gm = channels.get_adapter("gmail")
m = gm.parse_inbound({"workspace_id": "w1", "headers": {"From": "a@b.com"},
                      "body": "Please send a quote."})
check("gmail: extracts body", m.text == "Please send a quote.")
check("gmail: extracts sender", m.sender_id == "a@b.com")

# ── the agent runtime must stay channel-agnostic ──────────────────────
print("\n[4] Agent runtime has no channel coupling")
rt = open(os.path.join("services", "agent_runtime.py"), encoding="utf-8").read()
leaks = [w for w in ("whatsapp", "telegram", "gmail", "fastapi", "Request",
                     "HTTPException") if w in rt]
check("agent_runtime imports no transport concepts", not leaks, f"found {leaks}")

# ── in the live path, not decorative ─────────────────────────────────
print("\n[5] The adapter is actually wired into the endpoint")
main_src = open("main.py", encoding="utf-8").read()
check("endpoint calls the adapter", "adapter.handle_turn(" in main_src)
check("endpoint uses adapter formatting", "adapter.format_outbound(" in main_src)
check("old inline pipeline removed from main",
      "_friendly_action_reply" not in main_src,
      "tool-call handling now lives in the adapter only")
check("/api/channels registered", '@app.get("/api/channels")' in main_src)

try:
    r = requests.get(f"{API}/api/channels", timeout=20)
    if r.status_code == 200:
        d = r.json()
        check("channels endpoint responds", len(d.get("channels", [])) == 4)
        check("  reports web as live",
              any(c["name"] == "web" and c["status"] == "live" for c in d["channels"]))
        check("  reports others as planned",
              sum(1 for c in d["channels"] if c["status"] == "planned") == 3)
    else:
        skip("channels endpoint", f"HTTP {r.status_code}")
    h = requests.get(f"{API}/api/health", timeout=20).json()
    check("health advertises channels", h.get("channels") == ["web"], str(h.get("channels")))
except Exception as e:
    skip("channels endpoint", f"server unreachable: {str(e)[:40]}")

# ── a real turn must still work end to end ───────────────────────────
print("\n[6] A real agent turn still works through the adapter")
if LIVE:
    try:
        r = requests.post(f"{API}/api/workspaces/{WS}/agent/chat",
                          json={"message": "What services do you offer?", "history": []},
                          timeout=90)
        ok = r.status_code == 200
        check("live agent reply via adapter", ok, f"HTTP {r.status_code}")
        if ok:
            d = r.json()
            check("  reply present", len(d.get("reply", "")) > 20)
            check("  response keys unchanged",
                  set(d) == {"reply", "agent", "tool_call"}, str(sorted(d)))
            print(f"\n       AGENT SAID: {d.get('reply', '')[:200]}\n")
    except Exception as e:
        check("live agent reply via adapter", False, str(e)[:80])

    try:
        r = requests.post(f"{API}/api/workspaces/{WS}/agent/chat",
                          json={"message": "   ", "history": []}, timeout=30)
        check("empty message rejected with 400", r.status_code == 400, f"HTTP {r.status_code}")
    except Exception as e:
        skip("empty message", str(e)[:40])

    try:
        bad = "00000000-0000-0000-0000-000000000000"
        r = requests.post(f"{API}/api/workspaces/{bad}/agent/chat",
                          json={"message": "hi", "history": []}, timeout=30)
        check("unknown workspace returns 404", r.status_code == 404, f"HTTP {r.status_code}")
    except Exception as e:
        skip("unknown workspace", str(e)[:40])
else:
    skip("live agent turn", "pass --live to run (costs 1 LLM call)")

print("\n" + "=" * 72)
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped")
for f in FAIL:
    print("  FAILED:", f)
print("=" * 72)
