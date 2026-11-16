"""Unified workspace assistant.

ONE chat per workspace that figures out what the user wants and does it:
  - build/add a website
  - add an AI agent (receptionist / slot_booker / support / custom)
  - edit the website ("make the hero darker")
  - edit an agent ("make it more formal")
  - just answer a question about the business/workspace

Returns a structured action result the frontend renders inline. No tabs, no forms.
"""
from services.llm_service import call_json
from services import workspace_service as ws_svc
from services import editor_service
from services import language_service as lang_svc
from services.generation_service import (
    orchestrate_generation, generate_agent_config, AGENT_TYPES, WORKSPACES_DIR,
)
from rag.vector_store import vector_store
import os


def _classify(message: str, ws: dict, has_website: bool, agents: list[dict],
              lang: dict | None = None) -> dict:
    agent_names = [a.get("name") for a in agents]
    lang = lang or lang_svc.info(lang_svc.DEFAULT_LANG)
    # Routing reads the English gloss so the intent list stays in one language,
    # while the reply is written back in the user's own language.
    routing_text = lang.get("english") or message
    original_line = (
        f'\nORIGINAL MESSAGE (in {lang["name"]}): "{message}"'
        if lang["code"] != lang_svc.DEFAULT_LANG else ""
    )
    data = call_json(
        f"""You route a message in a business workspace assistant. Decide ONE intent.

WORKSPACE: {ws.get('business_name')} — {(ws.get('description') or '')[:400]}
HAS_WEBSITE: {has_website}
EXISTING_AGENTS: {agent_names or 'none'}

USER MESSAGE: "{routing_text}"{original_line}

Intents:
- "add_website": user wants to create/build a website (only if none exists or they ask for a new one)
- "add_agent": user wants a new AI agent. Pick agent_type from
  receptionist | slot_booker | appointment_booker | support | lead_capture | faq | custom.
  Guidance: slot_booker/appointment_booker for scheduling, lead_capture when the goal is
  collecting contact details, faq for answering common questions, support for resolving
  issues, receptionist for greeting and routing.
- "edit_website": user wants to change the existing website (colors, text, sections, images)
- "edit_agent": user wants to change an existing agent's behaviour/persona/tone
- "answer": a question or chit-chat that needs no build/edit

Return ONLY JSON:
{{
  "intent": "add_website|add_agent|edit_website|edit_agent|answer",
  "agent_type": "receptionist|slot_booker|appointment_booker|support|lead_capture|faq|custom|null",
  "reply": "<one short friendly sentence confirming what you're doing, or the answer if intent=answer>"
}}{lang_svc.reply_directive(lang)}""",
        # 400 -> 1200 (2026-10-30): the intent-routing reply is a small JSON
        # object, but the model spends part of its budget reasoning first, and
        # at 400 the JSON was being cut off (which fell back to a generic
        # "answer" intent and made the assistant look unresponsive).
        role="chat", max_tokens=1200, temperature=0.3,
    )
    if not isinstance(data, dict) or "intent" not in data:
        return {"intent": "answer", "agent_type": None,
                "reply": lang_svc.localize(
                    "Tell me what you'd like — a website, an AI agent, "
                    "or a change to what's here.", lang)}
    return data


def handle(workspace_id: str, user_id: str, message: str,
           language: str | None = None) -> dict:
    """Main entry. Returns {reply, action, changed, language, ...}.

    `language` is an optional override from the client (the UI picker or the
    speech locale). When absent the language is detected from the message, which
    also covers users typing their own language in English letters.
    """
    ws = ws_svc.get_workspace(workspace_id, user_id)
    if not ws:
        # No workspace means no stored preference, so honour whatever the client
        # declared rather than forcing English onto the error message.
        return {"reply": lang_svc.localize("Workspace not found.",
                                           lang_svc.info(language)),
                "action": "error", "changed": False,
                "language": lang_svc.info(language)["code"]}

    assets = ws_svc.get_assets(workspace_id)
    agents = [a["config"] for a in assets if a.get("type") == "agent" and a.get("config")]
    has_website = any(a.get("type") == "website" for a in assets)
    ctx = ws.get("description") or ws.get("business_name") or ""

    profile = ws.get("business_profile") or {}
    # An explicit choice wins; otherwise fall back to what this workspace used
    # last time, so a returning user is not re-detected on every message.
    lang = lang_svc.analyze(message, declared=language or profile.get("language"))
    _remember_language(workspace_id, profile, lang)

    # persist user message
    ws_svc.add_message(workspace_id, "user", message)

    route = _classify(message, ws, has_website, agents, lang)
    intent = route.get("intent", "answer")
    # Guard rails against misclassification. These run on the ENGLISH GLOSS, not
    # the raw message: the keyword lists below are English, so a Hindi or
    # romanized-Hindi request would never match them and would silently misroute.
    msg_l = (lang.get("english") or message).lower()
    wants_build = any(k in msg_l for k in ("build", "create", "make me", "generate", "i need", "add a website", "want a website"))
    mentions_site = any(k in msg_l for k in ("website", "site", "landing", "page", "web page"))
    if not has_website and mentions_site and (wants_build or intent in ("edit_website",)):
        intent = "add_website"
        route["reply"] = ""  # clear stale "edit" wording
    if has_website and intent == "add_website":
        intent = "edit_website"
    reply = route.get("reply", "")
    result = {"reply": reply, "action": intent, "changed": False,
              "language": lang["code"], "locale": lang["locale"]}

    asset_dir = profile.get("asset_dir") or workspace_id

    def say(text: str) -> str:
        """Localise a canned reply. No-op for English."""
        return lang_svc.localize(text, lang)

    try:
        if intent == "add_website":
            if has_website:
                result["reply"] = say("You already have a website here. "
                                      "Tell me what to change and I'll edit it.")
            else:
                r = _attach_website(workspace_id, ctx, profile, lang)
                result.update(r)
                result["reply"] = reply or say("Your website is ready.")

        elif intent == "add_agent":
            atype = route.get("agent_type") if route.get("agent_type") in AGENT_TYPES else "support"
            # The agent greets real customers, so its persona and greeting are
            # generated in the business's language, not just translated after.
            cfg = generate_agent_config(ctx, atype, language=lang["code"])
            ws_svc.add_asset(workspace_id, "agent", cfg.get("name", "Agent"), config=cfg)
            result["changed"] = True
            result["new_agent"] = cfg
            result["reply"] = reply or say(
                f"Added a {atype.replace('_', ' ')} agent: {cfg.get('name')}.")

        elif intent == "edit_website":
            if not has_website:
                result["reply"] = say("There's no website yet. Want me to build one?")
            else:
                r = editor_service.edit_website(asset_dir, message)
                result["changed"] = bool(r.get("ok"))
                if r.get("ok"):
                    # Prefer the editor's own message: it names the pages that
                    # changed, which matters now that a site is multi-page and an
                    # edit may touch one page or all of them.
                    pages = r.get("pages_updated") or []
                    result["pages_updated"] = pages
                    if len(pages) > 1:
                        result["reply"] = say(
                            f"Done — applied that across {len(pages)} pages "
                            f"({', '.join(pages)})."
                        )
                    else:
                        result["reply"] = say(
                            r.get("message") or "Done — updated your website.")
                else:
                    result["reply"] = say("Couldn't apply that:") + f" {r.get('error')}"

        elif intent == "edit_agent":
            if not agents:
                result["reply"] = say("There's no agent yet. Want me to add one?")
            else:
                target = agents[0]
                r = editor_service.edit_agent(target, message)
                if r.get("ok"):
                    _update_agent_asset(workspace_id, target.get("id"), r["config"])
                    result["changed"] = True
                    result["reply"] = reply or say(
                        f"Updated {r['config'].get('name')}.")
                else:
                    result["reply"] = say("Couldn't update the agent:") + f" {r.get('error')}"
        else:
            # answer using RAG
            from services.agent_runtime import run_agent
            cfg = {"system_prompt": "You are the helpful Forge assistant for this business. "
                                    "Answer clearly and concisely.", "type": "support"}
            result["reply"] = run_agent(cfg, ctx, message,
                                        workspace_id=workspace_id, language=lang)
    except Exception as e:
        result["reply"] = say("Something went wrong:") + f" {e}"
        result["action"] = "error"

    ws_svc.add_message(workspace_id, "assistant", result["reply"])
    return result


def _remember_language(workspace_id: str, profile: dict, lang: dict) -> None:
    """Store the workspace's language on business_profile.

    Kept in the existing jsonb column rather than a new one, so no migration is
    needed. It is what lets the PUBLIC agent endpoint know which language a
    business speaks without the visitor's browser telling it.
    Only written when it actually changes, to avoid a database round trip on
    every single message.
    """
    if profile.get("language") == lang["code"]:
        return
    profile["language"] = lang["code"]
    try:
        ws_svc.update_workspace(workspace_id, {"business_profile": profile})
    except Exception as e:
        # A failed preference write must not break the user's actual request.
        print(f"[lang] could not persist workspace language: {str(e)[:100]}")


def _attach_website(workspace_id: str, ctx: str, profile: dict,
                    lang: dict | None = None) -> dict:
    """Generate a website for THIS workspace (asset dir == workspace id).

    Using the real workspace id as the asset directory keeps the embedded chat
    widget endpoint valid (no live-site 404), and lets a workspace hold both a
    website and agents instead of fragmenting across throwaway ids.
    """
    from services.generation_service import orchestrate_generation
    code = (lang or {}).get("code") or profile.get("language")
    _, _, meta = orchestrate_generation(
        ctx, agent_types=[], build_website=True, workspace_id=workspace_id,
        language=code)
    profile["asset_dir"] = workspace_id
    ws_svc.update_workspace(workspace_id, {"business_profile": profile})
    ws_svc.add_asset(workspace_id, "website", "Landing Page",
                     path=f"{workspace_id}/website/index.html")
    return {"changed": True, "asset_dir": workspace_id}


def _update_agent_asset(workspace_id: str, agent_id: str, new_cfg: dict) -> None:
    from database.supabase_client import get_supabase
    for a in ws_svc.get_assets(workspace_id, "agent"):
        if (a.get("config") or {}).get("id") == agent_id:
            get_supabase().table("assets").update(
                {"config": new_cfg, "name": new_cfg.get("name")}
            ).eq("id", a["id"]).execute()
            return
