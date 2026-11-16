"""Editor agent — applies chat-based edits to existing workspace assets.

Generated sites are multi-page, which makes editing more than a single-file
rewrite. An instruction can be:
  - page-specific  ("change the contact form heading")   -> edit that page
  - site-wide      ("make the nav darker", "use a warmer palette") -> every page

Editing every page for every instruction would be slow and would risk the model
rewriting unrelated pages, so the target is resolved first and only the affected
pages are sent to the model.
"""
import os
import re

from services.llm_service import call_json, llm
from services.generation_service import (
    WORKSPACES_DIR, PAGES, PAGE_LABELS, NAV_LINKS,
    inject_agent_widget, create_zip, _strip_html,
    _ensure_complete_html, _ensure_nav,
)

# Elements that are duplicated across every page. An instruction touching any of
# these has to be applied site-wide or the pages drift out of sync.
NAV_LIST = ", ".join(f"{lbl} ({fn})" for fn, lbl in NAV_LINKS)

SHARED_ELEMENT_HINTS = (
    "nav", "navigation", "navbar", "menu", "header", "logo", "brand",
    "footer", "palette", "colour", "color", "theme", "font", "typography",
    "every page", "all pages", "whole site", "entire site", "sitewide",
    "site-wide", "throughout",
)

PAGE_ALIASES = {
    "index": ("home", "homepage", "home page", "landing", "hero", "index", "front page"),
    "about": ("about", "story", "team", "mission", "history", "values"),
    "services": ("service", "services", "offering", "pricing", "packages",
                 "treatment", "menu of services", "what we do"),
    "contact": ("contact", "enquiry", "inquiry", "form", "address", "map",
                "phone", "opening hours", "hours", "location"),
}

# every plan page gets its own alias tokens, so instructions like
# "edit the students page" resolve without hand-written maps
for _p in PAGES:
    if _p not in PAGE_ALIASES:
        _toks = {tok.lower() for tok in re.split(r"[_\s]", _p) if tok}
        _lbl = PAGE_LABELS.get(_p, _p)
        _toks |= set(re.findall(r"[A-Za-z]+", _lbl.lower()))
        PAGE_ALIASES[_p] = tuple(sorted(_toks))

EDIT_PROMPT = """You are editing ONE page of an existing multi-page website.
Apply the user's change and return the COMPLETE updated HTML document.

Rules:
- Keep everything not mentioned by the user exactly as it is.
- Keep the Tailwind CDN script.
- Keep the site navigation links: {nav_links}.
- Keep the <!--FORGE_AGENT_WIDGET--> marker, or the existing Forge widget script if present.
- Do not switch to a different colour palette unless the user asked for that.

PAGE BEING EDITED: {page}.html
USER CHANGE: {instruction}

CURRENT HTML:
{html}

Output ONLY the raw updated HTML. No markdown fences, no explanation."""


def _site_dir(asset_dir: str) -> str:
    return os.path.join(WORKSPACES_DIR, asset_dir, "website")


def _existing_pages(web_dir: str) -> list[str]:
    """Page stems present on disk, in canonical order."""
    if not os.path.isdir(web_dir):
        return []
    found = {f[:-5] for f in os.listdir(web_dir) if f.endswith(".html")}
    ordered = [p for p in PAGES if p in found]
    ordered += sorted(found - set(PAGES))
    return ordered


def resolve_targets(instruction: str, available: list[str]) -> tuple[list[str], str]:
    """Decide which pages an instruction affects.

    Returns (pages, reason). Keyword matching runs first because it is free and
    unambiguous for the common cases; the LLM is only consulted when the text
    gives no usable signal.
    """
    text = (instruction or "").lower()

    if any(h in text for h in SHARED_ELEMENT_HINTS):
        return available, "shared element or site-wide styling"

    named = [p for p in available
             if any(a in text for a in PAGE_ALIASES.get(p, (p,)))]
    if len(named) == 1:
        return named, f"instruction names the {named[0]} page"
    if len(named) > 1:
        return named, "instruction names several pages"

    # No textual signal: ask the router. Cheap call, and far better than
    # defaulting to the homepage when the user meant something else.
    try:
        data = call_json(
            "A user wants to change their multi-page website.\n"
            f"Available pages: {', '.join(available)}\n"
            f'User instruction: "{instruction}"\n\n'
            'Which pages must change? Reply ONLY as JSON: '
            '{"pages": ["index"], "site_wide": false}\n'
            'Use site_wide true when the change affects shared elements '
            "(navigation, footer, colours, fonts) that appear on every page.",
            role="chat", max_tokens=200, temperature=0.2,
        )
        if isinstance(data, dict):
            if data.get("site_wide"):
                return available, "router: site-wide change"
            pages = [p for p in (data.get("pages") or []) if p in available]
            if pages:
                return pages, "router selected page(s)"
    except Exception as e:
        print(f"[editor] target routing failed, defaulting to home: {e}")

    return (["index"] if "index" in available else available[:1]), "defaulted to home page"


def _edit_one_page(web_dir: str, page: str, instruction: str,
                   business_hint: str = "") -> bool:
    """Rewrite a single page. Returns True when the file was updated."""
    path = os.path.join(web_dir, f"{page}.html")
    if not os.path.exists(path):
        return False

    current = open(path, encoding="utf-8").read()
    try:
        raw = llm(
            EDIT_PROMPT.format(page=page, instruction=instruction,
                               nav_links=NAV_LIST, html=current[:80000]),
            role="build", max_tokens=int(os.getenv("EDIT_MAX_TOKENS", "6000")),
            temperature=0.4,
        )
    except Exception as e:
        print(f"[editor] '{page}' edit call failed: {e}")
        return False

    new_html = _strip_html(raw)
    # Guard against the model returning prose, a fragment, or a gutted page.
    if "<html" not in new_html.lower() or len(new_html) < 500:
        print(f"[editor] '{page}' produced invalid HTML, keeping original")
        return False
    if len(new_html) < len(current) * 0.4:
        print(f"[editor] '{page}' shrank {len(current)}->{len(new_html)} chars, "
              "rejecting as truncated")
        return False

    new_html = _ensure_nav(_ensure_complete_html(new_html), page, business_hint)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_html)
    return True


def edit_website(asset_dir: str, instruction: str) -> dict:
    """Apply a natural-language edit across the generated site's pages."""
    web_dir = _site_dir(asset_dir)
    available = _existing_pages(web_dir)
    if not available:
        return {"ok": False, "error": "No website to edit."}

    targets, reason = resolve_targets(instruction, available)
    print(f"[editor] editing {targets} ({reason})")

    business_hint = ""
    idx = os.path.join(web_dir, "index.html")
    if os.path.exists(idx):
        m = re.search(r"<title>(.*?)</title>",
                      open(idx, encoding="utf-8").read(), re.S | re.I)
        if m:
            business_hint = re.split(r"[|\-\u2013\u2014]", m.group(1))[0].strip()[:40]

    updated = [p for p in targets if _edit_one_page(web_dir, p, instruction, business_hint)]

    if not updated:
        return {"ok": False, "error": "The edit could not be applied. Try rephrasing it."}

    # Re-inject the widget (an edit may have replaced the marker) and refresh the
    # downloadable zip so it matches what is being previewed.
    try:
        inject_agent_widget(asset_dir, web_dir)
    except Exception as e:
        print(f"[editor] widget re-injection skipped: {e}")
    try:
        create_zip(web_dir, os.path.join(WORKSPACES_DIR, asset_dir, "website.zip"))
    except Exception as e:
        print(f"[editor] zip refresh skipped: {e}")

    failed = [p for p in targets if p not in updated]
    label = ", ".join(f"{p}.html" for p in updated)
    msg = f"Updated {label}." if len(updated) > 1 else f"Updated {label}."
    if failed:
        msg += f" Could not change {', '.join(failed)}."
    return {"ok": True, "message": msg, "pages_updated": updated,
            "pages_failed": failed, "scope": reason}


def edit_agent(agent_config: dict, instruction: str) -> dict:
    """Apply a natural-language edit to an agent's config (persona/behaviour)."""
    data = call_json(
        f"""Update this AI agent config per the user's instruction. Keep the JSON shape.
CURRENT CONFIG: {agent_config}
USER CHANGE: {instruction}

Return ONLY JSON with keys: name, system_prompt, greeting, capabilities, sample_questions.""",
        role="chat", max_tokens=700, temperature=0.4,
    )
    if not isinstance(data, dict) or "system_prompt" not in data:
        return {"ok": False, "error": "Edit failed.", "config": agent_config}
    # preserve identifiers
    data["id"] = agent_config.get("id")
    data["type"] = agent_config.get("type", "custom")
    return {"ok": True, "config": data}
