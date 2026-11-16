"""Architect chat service.

Gathers business info (text or scraped URL), decides when ready to build, and
returns a build plan. Designed to ask FEW questions: if a URL is scraped, it has
almost everything it needs and should go straight to ready.
"""
import re
import uuid
from services.llm_service import call_json
from scraper.website_scraper import scrape_website_structured
from rag.vector_store import vector_store

URL_RE = re.compile(r'https?://[^\s<>"\']+')
# Kept in sync with generation_service.AGENT_TYPES - imported rather than
# duplicated so a new agent type only has to be declared in one place.
from services.generation_service import AGENT_TYPES
VALID_AGENTS = set(AGENT_TYPES)

# In-process cache of scraped content keyed by a temp ref, so generation can
# inherit the RAG context into the real workspace id.
_SCRAPE_CACHE: dict[str, dict] = {}


def extract_urls(text: str):
    return URL_RE.findall(text or "")


def get_scrape(ref: str) -> dict | None:
    return _SCRAPE_CACHE.get(ref)


def process_chat(history: list) -> dict:
    """Return {status, reply, summary, business_name, build_plan, scrape_ref}."""
    latest = history[-1]["content"] if history and history[-1].get("role") == "user" else ""
    urls = extract_urls(latest)

    scraped_block = ""
    scrape_ref = None
    if urls:
        d = scrape_website_structured(urls[0])
        text = d.get("text", "")
        if text and not text.startswith("Error"):
            # Read the screenshot for design cues the text cannot carry (palette,
            # layout, how dated it looks). Optional: returns {} if unavailable.
            vision = {}
            try:
                from services.vision_service import analyze_screenshot
                if d.get("screenshot"):
                    vision = analyze_screenshot(d["screenshot"])
                    if vision:
                        print(f"[chat] vision analysis: {vision.get('style')} / "
                              f"{len(vision.get('recommendations', []))} recommendations")
            except Exception as e:
                print(f"[chat] vision analysis skipped: {e}")

            scrape_ref = uuid.uuid4().hex[:10]
            _SCRAPE_CACHE[scrape_ref] = {
                "url": urls[0], "text": text,
                "title": d.get("title", ""), "images": d.get("images", []),
                "screenshot": d.get("screenshot"), "vision": vision,
            }
            # store in RAG under the temp ref (re-keyed to workspace on generate)
            try:
                vector_store.add_business_context(scrape_ref, text, {"source_url": urls[0]})
            except Exception:
                pass
            head = ", ".join(d.get("headings", [])[:10])
            scraped_block = (
                f"\n[SCRAPED {urls[0]} | {d.get('pages_crawled',1)} pages | "
                f"title: {d.get('title','')} | sections: {head}]\n{text[:4000]}\n[/SCRAPED]\n"
            )
        else:
            scraped_block = f"\n[SCRAPE FAILED for {urls[0]} — ask the user to describe the business instead]\n"

    # Carry prior assistant-extracted info by sending the whole short history.
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in history[-8:])

    prompt = f"""You are the Forge AI Architect helping a business owner build a website and/or AI agents.

CONVERSATION:
{convo}
{scraped_block}

GOAL: collect just enough to build — business name, what they do, audience, and what to build.

DECISION RULES (important — do NOT over-ask):
- If a site was SCRAPED, you already have the business details. Do NOT ask about name/industry/services.
  Only ask ONE thing: what they want built (website, agents, or both) — UNLESS they already said it, then go ready.
- If the user already stated what to build, set status="ready" immediately. Never re-ask something already answered.
- Ask AT MOST one short question, and only if truly necessary. Never repeat a question.
- "build it"/"yes"/"go"/"generate" → status="ready".
- Default build_plan when ambiguous: website=true, agents=["support"].

AGENT TYPES: receptionist, slot_booker, appointment_booker, support, lead_capture, faq, custom.

Return ONLY JSON:
{{
  "status": "needs_info" | "ready",
  "reply": "<short message>",
  "summary": "<rich business summary if ready (include offerings, audience, tone), else null>",
  "business_name": "<name if known, else null>",
  "build_plan": {{ "website": true, "enhance_url": "<url or null>", "agents": ["support"] }}
}}"""

    # 1100 -> 2500 (2026-10-30): the chat model reasons before answering, so a
    # small cap truncated the reply mid-sentence and risked cutting the JSON
    # itself. The extra headroom is a couple of hundred tokens at most.
    data = call_json(prompt, role="chat", max_tokens=2500, temperature=0.4)

    if not isinstance(data, dict) or "status" not in data:
        return {"status": "needs_info",
                "reply": "Tell me about your business and whether you want a website, AI agents, or both. You can also paste your website URL.",
                "summary": None, "business_name": None, "build_plan": None, "scrape_ref": None}

    bp = data.get("build_plan") or {}
    agents = [a for a in (bp.get("agents") or ["support"]) if a in VALID_AGENTS] or ["support"]
    data["build_plan"] = {
        "website": bool(bp.get("website", True)),
        "enhance_url": bp.get("enhance_url") or (urls[0] if urls else None),
        "agents": agents,
    }
    data["scrape_ref"] = scrape_ref

    if data.get("status") == "ready":
        data["status"] = "generate"
    return data
