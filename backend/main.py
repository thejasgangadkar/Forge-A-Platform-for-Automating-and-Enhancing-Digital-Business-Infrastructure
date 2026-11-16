"""Forge backend — FastAPI entrypoint (v3, multi-agent, auth-aware)."""
import os
import sys
from typing import List, Dict, Optional

# Windows consoles default to cp1252, which raises UnicodeEncodeError on any
# non-ASCII log output. A crash inside a log statement previously aborted a
# whole generation run, so force UTF-8 (replacing unencodable chars) instead.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Windows: the event loop is configured by loop_factory.py.
#
# The default Proactor loop raises OSError [WinError 64] from its accept()
# path when a client disconnects abruptly - which happens constantly here,
# because the browser aborts the long-running /api/generate request. Each
# occurrence left the listening socket broken and the server then refused the
# NEXT connection, so a build that finished successfully was followed by
# "connection aborted" when the generated site was fetched.
#
# The Selector loop handles an aborted accept cleanly. uvicorn 0.36+ supports
# a custom loop factory through the --loop option, which is what
# loop_factory.py provides; the run command in forge.config.env uses it.

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from services.auth_service import get_current_user
from services.chat_service import process_chat, get_scrape
from services import workspace_service as ws_svc
from services.generation_service import (
    WORKSPACES_DIR, orchestrate_generation, AGENT_TYPES,
)
from services.agent_runtime import run_agent
from services import editor_service
from services import workspace_assistant
from services import language_service as lang_svc
from services import rate_limit_service
from rag.vector_store import vector_store
import channels

app = FastAPI(title="Forge API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── models ─────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    history: List[ChatMessage]
    workspace_id: Optional[str] = None


class GenerateRequest(BaseModel):
    business_context: str
    business_name: Optional[str] = None
    agents: Optional[List[str]] = None
    build_website: bool = True
    scrape_ref: Optional[str] = None
    workspace_id: Optional[str] = None   # if set, add assets to this workspace
    # Language for the generated site copy and agent greetings. When omitted it
    # is inferred from the business description, so a user who wrote their brief
    # in Tamil gets a Tamil site without having to ask for one.
    language: Optional[str] = None


class AgentChatRequest(BaseModel):
    message: str
    history: List[Dict[str, str]] = []
    agent_id: Optional[str] = None
    # `locale` is what the browser widget sends (e.g. "hi-IN"); `language` is the
    # bare code. Either is accepted so the widget, the hosted page and API
    # callers can all use whichever they naturally hold.
    language: Optional[str] = None
    locale: Optional[str] = None


class EditRequest(BaseModel):
    target: str          # "website" | "agent"
    instruction: str
    agent_id: Optional[str] = None


class AssistRequest(BaseModel):
    message: str
    language: Optional[str] = None


# ─── health ─────────────────────────────────────────────────────────
@app.get("/api/health")
def health_check():
    return {"status": "Forge Backend is Active", "version": "3.1.0",
            "agent_types": list(AGENT_TYPES.keys()),
            "channels": channels.enabled_channels()}


# ─── architect chat ─────────────────────────────────────────────────
@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest, user=Depends(get_current_user)):
    try:
        history = [m.dict() for m in request.history]
        # process_chat makes a blocking HTTPS call to the LLM provider. Run it
        # in a worker thread so the event loop stays free to serve other
        # requests while this one waits (2026-10-30).
        result = await run_in_threadpool(process_chat, history)
        # Persist to an existing workspace's conversation if provided.
        if request.workspace_id and history:
            try:
                ws_svc.add_message(request.workspace_id, "user", history[-1]["content"])
                ws_svc.add_message(request.workspace_id, "assistant", result.get("reply", ""))
            except Exception:
                pass
        return {
            "action": result.get("status", "needs_info"),
            "reply": result.get("reply", ""),
            "summary": result.get("summary", ""),
            "business_name": result.get("business_name"),
            "build_plan": result.get("build_plan"),
            "scrape_ref": result.get("scrape_ref"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── generation ─────────────────────────────────────────────────────
@app.post("/api/generate")
async def generate_endpoint(request: GenerateRequest, user=Depends(get_current_user)):
    # The whole generation pipeline is blocking (it makes synchronous HTTPS
    # calls to the LLM provider, writes files, and talks to Postgres). Running
    # it directly inside this async endpoint froze the entire event loop for
    # the whole build - the server could not answer /api/health, could not
    # serve the generated site, and dropped the connection when the browser
    # timed out. Handing it to a worker thread keeps the server responsive
    # for the whole 3-5 minute build (2026-10-30).
    return await run_in_threadpool(_generate_sync, request, user)


def _generate_sync(request: GenerateRequest, user: dict):
    try:
        # 1) Establish the REAL workspace id FIRST (DB row), so the asset
        #    directory + chat-widget endpoint always match a workspace that
        #    exists in the database. Fixes the live-widget 404 (Bug A/F).
        if request.workspace_id:
            ws = ws_svc.get_workspace(request.workspace_id, user["id"])
            if not ws:
                raise HTTPException(status_code=404, detail="Workspace not found")
            target_ws_id = ws["id"]
        else:
            ws = ws_svc.create_workspace(
                user_id=user["id"],
                business_name=request.business_name or "New Forge Project",
                description=request.business_context,
                business_profile={},
            )
            target_ws_id = ws["id"]

        # 2) If this build came from a scraped URL, reuse the visual analysis of
        #    their existing site so the result is a deliberate improvement rather
        #    than an unrelated redesign.
        design_notes = ""
        if request.scrape_ref:
            try:
                from services.vision_service import format_for_prompt
                cached = get_scrape(request.scrape_ref) or {}
                design_notes = format_for_prompt(cached.get("vision") or {})
            except Exception as e:
                print(f"[generate] design notes unavailable: {e}")

        # 2b) Resolve the language for the generated assets. An explicit choice
        #     wins; otherwise it is detected from the business description, so a
        #     brief written in Tamil produces a Tamil site without being asked.
        profile_pre = ws.get("business_profile") or {}
        language = (request.language or profile_pre.get("language")
                    or lang_svc.analyze(request.business_context)["code"])

        # 3) Generate all assets UNDER the real workspace id.
        workspace_id, ctx, meta = orchestrate_generation(
            request.business_context,
            agent_types=request.agents,
            build_website=request.build_website,
            workspace_id=target_ws_id,
            design_notes=design_notes,
            language=language,
        )

        # 4) Persist profile (asset_dir now equals the workspace id).
        profile = ws.get("business_profile") or {}
        profile["asset_dir"] = target_ws_id
        profile["language"] = language
        if (meta.get("website") or {}).get("keywords"):
            profile["keywords"] = meta["website"]["keywords"]
        if design_notes:
            profile["enhanced_from_screenshot"] = True
        ws_svc.update_workspace(target_ws_id, {"business_profile": profile})

        # Transfer scraped RAG context (temp ref → real workspace id).
        if request.scrape_ref:
            try:
                vector_store.copy_context(request.scrape_ref, target_ws_id)
            except Exception:
                pass
        # Always seed the workspace description into RAG.
        try:
            vector_store.add_business_context(target_ws_id, ctx, {"workspace_id": target_ws_id})
        except Exception:
            pass

        for cfg in meta.get("agents", []):
            ws_svc.add_asset(target_ws_id, "agent", cfg.get("name", "Agent"), config=cfg)
        if meta.get("website") is not None:
            ws_svc.add_asset(target_ws_id, "website", "Landing Page",
                             path=f"{target_ws_id}/website/index.html")

        return {"status": "success", "workspace_id": target_ws_id, "asset_dir": target_ws_id,
                "agents": meta.get("agents", [])}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── workspaces ─────────────────────────────────────────────────────
@app.get("/api/workspaces")
async def list_workspaces(user=Depends(get_current_user)):
    try:
        return ws_svc.list_workspaces(user["id"])
    except Exception:
        return []


@app.get("/api/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str, user=Depends(get_current_user)):
    ws = ws_svc.get_workspace(workspace_id, user["id"])
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    ws["conversations"] = ws_svc.get_messages(workspace_id)
    ws["assets"] = ws_svc.get_assets(workspace_id)
    return ws


@app.delete("/api/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str, user=Depends(get_current_user)):
    """Permanently delete a workspace and all of its assets.

    Irreversible, and it also takes down the workspace's hosted page and embedded
    widget, so ownership is enforced inside the service layer.
    """
    result = ws_svc.delete_workspace(workspace_id, user["id"])
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Workspace not found"))
    return result


@app.get("/api/workspaces/{workspace_id}/messages")
async def workspace_messages(workspace_id: str, user=Depends(get_current_user)):
    if not ws_svc.get_workspace(workspace_id, user["id"]):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws_svc.get_messages(workspace_id)


@app.get("/api/workspaces/{workspace_id}/agents")
async def workspace_agents(workspace_id: str, user=Depends(get_current_user)):
    if not ws_svc.get_workspace(workspace_id, user["id"]):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws_svc.get_agent_configs(workspace_id)


def _asset_dir(ws: dict) -> str:
    profile = ws.get("business_profile") or {}
    return profile.get("asset_dir") or ws["id"]


@app.get("/api/workspaces/{workspace_id}/download/{asset_type}")
async def download_asset(workspace_id: str, asset_type: str, user=Depends(get_current_user)):
    if asset_type not in {"website", "agents"}:
        raise HTTPException(status_code=400, detail="Invalid asset type")
    ws = ws_svc.get_workspace(workspace_id, user["id"])
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    zip_path = os.path.join(WORKSPACES_DIR, _asset_dir(ws), f"{asset_type}.zip")
    if not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(zip_path, filename=f"{workspace_id}_{asset_type}.zip",
                        media_type="application/zip")


# ─── agent sandbox (platform-run agent) ─────────────────────────────
@app.post("/api/workspaces/{workspace_id}/agent/chat")
async def chat_with_agent(workspace_id: str, request: AgentChatRequest,
                          http_request: Request):
    """Public: used by the embedded site widget AND the in-app sandbox.

    Unauthenticated by design (customers must not need an account), so it is
    rate limited per IP to stop a leaked workspace id draining the LLM quota.

    The agent turn itself runs through the web channel adapter, which is the same
    code path any future WhatsApp or Telegram channel uses — the endpoint only
    handles HTTP concerns.
    """
    rate_limit_service.enforce(http_request, "chat", workspace_id)

    adapter = channels.get_adapter("web")
    inbound = adapter.parse_inbound({
        "workspace_id": workspace_id,
        "message": request.message,
        "history": request.history,
        "agent_id": request.agent_id,
        # A visitor may not speak the language the business was configured in,
        # so the hint travels with the turn and the runtime still falls back to
        # detecting from the message itself.
        "language": request.language or request.locale,
    })
    if not inbound.text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        # handle_turn calls the LLM synchronously; keep it off the event loop
        # so one slow agent reply cannot stall the whole server (2026-10-30).
        outbound = await run_in_threadpool(adapter.handle_turn, inbound)
    except LookupError:
        raise HTTPException(status_code=404, detail="Workspace not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return adapter.format_outbound(outbound)


@app.get("/api/channels")
async def get_channels():
    """Which delivery channels this build supports, and their readiness.

    'enabled' means shipped; 'configured' means this deployment also has the
    credentials. Public because it advertises capability, not data.
    """
    return {"channels": channels.list_channels(),
            "active": channels.enabled_channels()}


@app.post("/api/workspaces/{workspace_id}/assist")
async def workspace_assist(workspace_id: str, request: AssistRequest, user=Depends(get_current_user)):
    """Unified workspace chat: understands intent and builds/edits/answers in one place."""
    if not ws_svc.get_workspace(workspace_id, user["id"]):
        raise HTTPException(status_code=404, detail="Workspace not found")
    # Off the event loop: the assistant makes blocking LLM calls (2026-10-30).
    return await run_in_threadpool(
        workspace_assistant.handle, workspace_id, user["id"], request.message,
        language=request.language)


@app.get("/api/languages")
async def get_languages():
    """Languages the platform can build and converse in.

    Public: the login and signup screens need it before a session exists, and it
    advertises capability rather than data. Drives the UI picker, and each entry
    carries the BCP-47 locale the browser needs for speech.
    """
    return {"languages": lang_svc.supported_list(),
            "default": lang_svc.DEFAULT_LANG}


@app.get("/api/workspaces/{workspace_id}/embed")
async def get_embed(workspace_id: str, user=Depends(get_current_user)):
    """Return the simplest ways to deploy: a shareable link + an optional copy-paste snippet."""
    ws = ws_svc.get_workspace(workspace_id, user["id"])
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    api_base = os.getenv("PUBLIC_API_BASE", "http://127.0.0.1:8000")
    share_link = f"{api_base}/a/{workspace_id}"
    snippet = (
        f'<script src="{api_base}/workspaces/_widget/forge-widget.js" '
        f'data-forge-workspace="{workspace_id}" '
        f'data-forge-api="{api_base}" defer></script>'
    )
    return {"share_link": share_link, "snippet": snippet,
            "workspace_id": workspace_id, "api_base": api_base}


@app.get("/a/{workspace_id}")
async def public_agent_page(workspace_id: str, http_request: Request):
    """A clean, shareable full-page chat for a workspace's agent. No login needed."""
    rate_limit_service.enforce(http_request, "page", workspace_id)

    ws = ws_svc.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Not found")
    # Track visit event
    track_event(workspace_id, "visit", {"source": "public_page"})
    configs = ws_svc.get_agent_configs(workspace_id)
    agent = configs[0] if configs else {"name": "Assistant", "greeting": "Hi! How can I help?"}
    api_base = os.getenv("PUBLIC_API_BASE", "http://127.0.0.1:8000")
    biz = (ws.get("business_name") or "Assistant")
    greeting = agent.get("greeting", "Hi! How can I help you today?")

    # This page is what a real customer opens, so its own furniture (placeholder,
    # error and rate-limit text) has to speak the business's language too, not
    # just the agent's replies.
    li = lang_svc.info(agent.get("language")
                       or (ws.get("business_profile") or {}).get("language"))
    html = _PUBLIC_CHAT_HTML.format(
        biz=biz.replace("<", "&lt;"),
        agent=agent.get("name", "Assistant").replace("<", "&lt;"),
        greeting=greeting.replace("<", "&lt;").replace('"', "&quot;"),
        ws=workspace_id, api=api_base,
        lang=li["code"], locale=li["locale"],
        t_placeholder=lang_svc.localize("Type your message...", li),
        t_fast=lang_svc.localize(
            "You're sending messages very quickly. "
            "Please wait a moment and try again.", li),
        t_err=lang_svc.localize("Connection error.", li),
    )
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html)


# ─── per-workspace editor ───────────────────────────────────────────
@app.post("/api/workspaces/{workspace_id}/edit")
async def edit_workspace(workspace_id: str, request: EditRequest, user=Depends(get_current_user)):
    ws = ws_svc.get_workspace(workspace_id, user["id"])
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    adir = _asset_dir(ws)

    if request.target == "website":
        # The editor makes blocking LLM calls; keep it off the event loop so
        # the server stays responsive during an edit (2026-10-30).
        res = await run_in_threadpool(editor_service.edit_website, adir,
                                       request.instruction)
        return res

    if request.target == "agent":
        configs = ws_svc.get_agent_configs(workspace_id)
        cfg = next((c for c in configs if c.get("id") == request.agent_id), None) \
            or (configs[0] if configs else None)
        if not cfg:
            raise HTTPException(status_code=404, detail="No agent to edit")
        res = await run_in_threadpool(editor_service.edit_agent, cfg,
                                       request.instruction)
        if res.get("ok"):
            # update the matching asset row
            for a in ws_svc.get_assets(workspace_id, "agent"):
                if (a.get("config") or {}).get("id") == cfg.get("id"):
                    from database.supabase_client import get_supabase
                    get_supabase().table("assets").update(
                        {"config": res["config"], "name": res["config"].get("name")}
                    ).eq("id", a["id"]).execute()
                    break
        return res

    raise HTTPException(status_code=400, detail="Invalid edit target")


# ─── analytics & tool-call endpoints ────────────────────────────────
from services.analytics_service import track_event, get_analytics
from services.agent_runtime import parse_tool_call, validate_tool_call


@app.get("/api/workspaces/{workspace_id}/analytics")
async def workspace_analytics(workspace_id: str, period: str = "week", user=Depends(get_current_user)):
    """Return aggregated analytics for a workspace."""
    ws = ws_svc.get_workspace(workspace_id, user["id"])
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return get_analytics(workspace_id, period)


@app.get("/api/workspaces/{workspace_id}/actions")
async def workspace_actions(workspace_id: str, user=Depends(get_current_user)):
    """List tool-call actions for a workspace."""
    ws = ws_svc.get_workspace(workspace_id, user["id"])
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    from database.supabase_client import get_supabase
    result = get_supabase().table("agent_actions")\
        .select("*")\
        .eq("workspace_id", workspace_id)\
        .order("created_at", desc=True)\
        .limit(50)\
        .execute()
    return {"actions": result.data or []}


# ─── static / generated sites ───────────────────────────────────────
os.makedirs(WORKSPACES_DIR, exist_ok=True)
app.mount("/workspaces", StaticFiles(directory=WORKSPACES_DIR), name="workspaces")


@app.get("/")
async def root():
    return {"message": "Forge API v3 running.", "docs": "/docs"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Browsers request this automatically when the API root is opened directly.

    Answering 204 keeps it out of the log as a spurious 404, which otherwise looks
    like a real failure when scanning output during a demo.
    """
    from fastapi import Response
    return Response(status_code=204)


# ─── public shareable agent chat page ───────────────────────────────
_PUBLIC_CHAT_HTML = """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{biz} — Assistant</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:system-ui,Segoe UI,sans-serif;background:#04060f;color:#eef1f8;height:100vh;display:flex;flex-direction:column}}
  .top{{padding:16px 20px;border-bottom:1px solid rgba(140,160,200,.15);display:flex;align-items:center;gap:12px;background:#0a0f1f}}
  .dot{{width:10px;height:10px;border-radius:50%;background:#00e0d1;box-shadow:0 0 10px #00e0d1}}
  .top h1{{font-size:1rem;font-weight:700}} .top p{{font-size:.78rem;color:#97a3bd}}
  .wrap{{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:14px;max-width:760px;margin:0 auto;width:100%}}
  .m{{padding:11px 15px;border-radius:16px;max-width:80%;line-height:1.55;font-size:.95rem;white-space:pre-wrap}}
  .u{{align-self:flex-end;background:linear-gradient(135deg,#7c6cff,#6354ff);color:#fff;border-bottom-right-radius:5px}}
  .a{{align-self:flex-start;background:rgba(30,41,64,.6);border:1px solid rgba(140,160,200,.15);border-bottom-left-radius:5px}}
  form{{display:flex;gap:10px;padding:16px 24px;border-top:1px solid rgba(140,160,200,.15);max-width:760px;margin:0 auto;width:100%}}
  input{{flex:1;padding:13px 16px;border-radius:14px;background:rgba(255,255,255,.05);border:1px solid rgba(140,160,200,.25);color:#fff;outline:none;font-size:.95rem}}
  input:focus{{border-color:#7c6cff}}
  button{{border:none;background:linear-gradient(135deg,#7c6cff,#6354ff);color:#fff;width:48px;border-radius:14px;font-size:1.2rem;cursor:pointer}}
  .foot{{text-align:center;font-size:.72rem;color:#5f6c87;padding:8px}}
  .foot a{{color:#7c6cff;text-decoration:none}}
  button:disabled{{opacity:.5;cursor:not-allowed}}
  input:disabled{{opacity:.6}}
  #mic{{background:rgba(255,255,255,.06);border:1px solid rgba(140,160,200,.28);font-size:1rem}}
  #mic.listening{{background:#e5484d;border-color:#e5484d;animation:mic 1.4s ease-in-out infinite}}
  #mic.speaking{{background:#7c6cff;border-color:#7c6cff}}
  @keyframes mic{{0%,100%{{box-shadow:0 0 0 0 rgba(229,72,77,.55)}}50%{{box-shadow:0 0 0 7px rgba(229,72,77,0)}}}}
  @media (prefers-reduced-motion: reduce){{ #mic.listening{{animation:none}} .dot{{animation:none}} }}
  @keyframes blink{{0%,80%,100%{{opacity:.25;transform:translateY(0)}}40%{{opacity:1;transform:translateY(-3px)}}}}
  .dot{{width:7px;height:7px;border-radius:50%;background:#cbd5e1;display:inline-block;margin-right:4px;animation:blink 1.4s infinite both}}
</style></head>
<body>
  <div class="top"><span class="dot"></span><div><h1>{agent}</h1><p>{biz}</p></div></div>
  <div class="wrap" id="w"></div>
  <form id="f">
    <input id="i" placeholder="{t_placeholder}" autocomplete="off"/>
    <button type="button" id="mic" title="Speak" aria-label="Start voice input">&#127908;</button>
    <button id="s" aria-label="Send">&#8593;</button>
  </form>
  <div class="foot">Powered by <a href="/">Forge</a></div>
<script>
  var WS="{ws}",API="{api}",hist=[],busy=false;
  var LOCALE="{locale}",T_FAST="{t_fast}",T_ERR="{t_err}";
  var w=document.getElementById('w'),f=document.getElementById('f'),i=document.getElementById('i'),s=document.getElementById('s');
  var mic=document.getElementById('mic');
  function add(role,txt){{var d=document.createElement('div');d.className='m '+(role==='user'?'u':'a');d.textContent=txt;w.appendChild(d);w.scrollTop=w.scrollHeight;return d;}}
  function typing(){{var d=document.createElement('div');d.className='m a';d.setAttribute('aria-label','Assistant is typing');
    d.innerHTML='<span class="dot"></span><span class="dot" style="animation-delay:.2s"></span><span class="dot" style="animation-delay:.4s"></span>';
    w.appendChild(d);w.scrollTop=w.scrollHeight;return d;}}
  add('agent',"{greeting}");

  // ── Voice, via the browser's built-in Web Speech API (no service, no cost) ──
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var canSpeak = 'speechSynthesis' in window;
  var voiceMode = false;              // set once the visitor uses the mic
  if(!SR) {{ mic.style.display='none'; }}

  function say(text){{
    if(!canSpeak || !voiceMode || !text) return;
    try{{
      speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(text);
      u.lang = LOCALE; u.rate = 1; u.pitch = 1;
      // Without an explicit matching voice the browser reads non-English text
      // with an English voice, which comes out unintelligible.
      var vs = speechSynthesis.getVoices() || [], base = LOCALE.split('-')[0];
      var v = vs.filter(function(x){{ return x.lang===LOCALE; }})[0]
           || vs.filter(function(x){{ return x.lang && x.lang.split('-')[0]===base; }})[0];
      if(v) u.voice = v;
      u.onstart = function(){{ mic.classList.add('speaking'); }};
      u.onend = function(){{ mic.classList.remove('speaking'); }};
      speechSynthesis.speak(u);
    }}catch(e){{}}
  }}

  if(SR){{
    mic.onclick = function(){{
      if(busy) return;
      if(mic.classList.contains('speaking')){{ speechSynthesis.cancel(); mic.classList.remove('speaking'); return; }}
      var rec = new SR();
      rec.continuous=false; rec.interimResults=false; rec.lang=LOCALE;
      rec.onstart=function(){{ mic.classList.add('listening'); }};
      rec.onend=function(){{ mic.classList.remove('listening'); }};
      rec.onerror=function(){{ mic.classList.remove('listening'); }};
      rec.onresult=function(ev){{
        var t = ev.results[0][0].transcript;
        mic.classList.remove('listening');
        if(t){{ voiceMode = true; i.value = t; send(t); }}
      }};
      try{{ rec.start(); }}catch(e){{}}
    }};
  }}

  async function send(text){{
    var m=(text!==undefined?text:i.value).trim(); if(!m||busy) return;
    busy=true; i.disabled=true; s.disabled=true;
    add('user',m); i.value='';
    var t=typing();
    try{{
      var r=await fetch(API+'/api/workspaces/'+WS+'/agent/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{message:m,history:hist,locale:LOCALE}})}});
      t.remove();
      if(r.status===429){{
        add('agent',T_FAST);
      }}
      else {{
        var d=await r.json();
        var reply=d.reply||'...';
        add('agent',reply);
        hist.push({{role:'user',content:m}}); hist.push({{role:'assistant',content:reply}});
        say(reply);
      }}
    }}catch(err){{ t.remove(); add('agent',T_ERR); }}
    busy=false; i.disabled=false; s.disabled=false; i.focus();
  }}

  f.onsubmit=function(e){{ e.preventDefault(); send(); }};
</script></body></html>"""


if __name__ == "__main__":
    import uvicorn
    # The custom loop factory keeps the server alive when a client aborts a
    # long request (see loop_factory.py for the full explanation).
    uvicorn.run(app, host="0.0.0.0", port=8000,
                loop="loop_factory:windows_safe_loop_factory")