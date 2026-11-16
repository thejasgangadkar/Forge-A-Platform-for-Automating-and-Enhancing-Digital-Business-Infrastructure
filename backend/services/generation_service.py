"""Generation service.

Two deliverables per workspace:
  1. Website  – modern responsive landing page (HTML + Tailwind + JS) with real images.
  2. Agents   – platform-native AI agents stored as JSON configs (the platform runs them).
                Types: receptionist, slot_booker, support, custom.

No n8n (dropped). Automations are delivered as agent capabilities.
"""
import os
import json
import time
import uuid
import zipfile

from services.llm_service import call_json, llm
from services.image_service import image_pack
from services import language_service as lang_svc

WORKSPACES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "generated_workspaces")

AGENT_TYPES = {
    "receptionist": "An AI receptionist that greets visitors, answers general questions, and routes them.",
    "slot_booker": "An AI appointment/slot booking assistant that collects details and proposes time slots.",
    "appointment_booker": "An AI appointment scheduler that confirms service, date and time, collects the visitor's name and contact details, and books the appointment.",
    "support": "A customer support agent that resolves issues using the business knowledge.",
    "lead_capture": "A lead qualification agent that engages visitors, understands what they need, and collects their name and contact details as a lead.",
    "faq": "An FAQ agent that answers frequently asked questions about the business, its services, hours and policies, strictly from the business knowledge.",
    "custom": "A custom agent tailored to a user-described purpose.",
}

# The tool-calls each agent type should be encouraged to use. Without this a
# lead-capture agent will happily chat without ever collecting contact details,
# which defeats its purpose.
AGENT_PRIMARY_ACTIONS = {
    "receptionist": ["capture_lead", "escalate"],
    "slot_booker": ["book_slot"],
    "appointment_booker": ["book_slot"],
    "support": ["escalate"],
    "lead_capture": ["capture_lead"],
    "faq": ["escalate"],
    "custom": [],
}


# ────────────────────────────── helpers ──────────────────────────────
def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def create_zip(source_dir: str, output_zip_path: str) -> None:
    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(source_dir):
            for fname in files:
                fp = os.path.join(root, fname)
                zf.write(fp, os.path.relpath(fp, source_dir))


# ────────────────────────── 1. Website ──────────────────────────
WEBSITE_PROMPT = """You are a senior front-end engineer. Build a complete, high-quality, fully responsive landing page as a SINGLE HTML file.

BUSINESS:
{ctx}

AVAILABLE IMAGES (use these real URLs in <img> tags / CSS backgrounds — do NOT invent other image URLs):
{images}

REQUIREMENTS (strict):
- Output a SINGLE complete HTML document only. Start with <!DOCTYPE html> and end with </html>.
- Tailwind via CDN (https://cdn.tailwindcss.com). Google Font "Inter".
- All JavaScript inline in a <script> tag at the end of <body> (smooth scroll, mobile menu toggle, FAQ accordion). No external JS files. No frameworks.
- Sections in order: sticky <nav> (logo + 4 links + CTA), hero <section> (headline + subheadline + 2 CTAs + a real image), features <section> (3-6 cards with inline SVG icons), how-it-works <section> (3 steps), testimonials <section> (2-3), pricing/services <section> (2-3 tiers), FAQ <section> (3-4 items, accordion), final CTA <section>, <footer>.
- Tasteful color palette derived from the business industry (CSS vars). Be consistent.
- Real, specific copy reflecting the business. NO Lorem Ipsum. NO placeholder text.
- Use ONLY the image URLs provided above, with meaningful alt text.
- Accessible: semantic HTML, alt text, aria-labels, focus styles.
- Include this exact comment right before </body>: <!--FORGE_AGENT_WIDGET-->
{lang_block}

Output ONLY the raw HTML. No markdown fences, no explanation, no JSON."""


def _strip_html(raw: str) -> str:
    s = (raw or "").strip()

    # If the model JSON-wrapped it ({"html": "..."} / {"index.html": "..."}), unwrap.
    if s.startswith("{"):
        import json as _json
        for parsed in (_try_json(s), _try_json(s + '"}')):  # tolerate truncated tail
            if isinstance(parsed, dict):
                for k in ("index.html", "html", "code", "content"):
                    if isinstance(parsed.get(k), str) and "<" in parsed[k]:
                        return _trim_to_doc(parsed[k])
        # Truncated JSON: pull the value of the first html-ish key manually.
        extracted = _extract_json_html_value(s)
        if extracted:
            return _trim_to_doc(extracted)

    if "```" in s:
        parts = s.split("```")
        for part in parts:
            p = part.strip()
            if p.lower().startswith("html"):
                p = p[4:].strip()
            if "<!doctype" in p.lower() or "<html" in p.lower():
                s = p
                break
    return _trim_to_doc(s)


def _try_json(s: str):
    import json as _json
    try:
        return _json.loads(s)
    except Exception:
        return None


def _extract_json_html_value(s: str) -> str:
    """Recover the HTML string from a (possibly truncated) JSON envelope."""
    import re
    m = re.search(r'"(?:index\.html|html|code|content)"\s*:\s*"', s)
    if not m:
        return ""
    body = s[m.end():]
    # Unescape JSON string escapes; stop at an unescaped closing quote if present.
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}.get(nxt, nxt))
            i += 2
            continue
        if c == '"':
            break
        out.append(c)
        i += 1
    return "".join(out)


def _trim_to_doc(s: str) -> str:
    s = (s or "").strip()
    low = s.lower()
    i = low.find("<!doctype")
    if i == -1:
        i = low.find("<html")
    if i > 0:
        s = s[i:]
    return s.strip()


def _keywords_from_context(context: str) -> list[str]:
    data = call_json(
        f"Business: {context[:800]}\n\n"
        "Return JSON {\"keywords\": [5 short stock-photo search terms relevant to this business]}",
        role="chat", max_tokens=600, temperature=0.3,
    )
    kws = data.get("keywords") if isinstance(data, dict) else None
    if not kws or not isinstance(kws, list):
        kws = ["business", "office", "team", "technology", "service"]
    return [str(k) for k in kws][:5]


def generate_website(context: str, output_dir: str, language: str | None = None) -> dict:
    keywords = _keywords_from_context(context)
    pack = image_pack(keywords, per_keyword=2)
    images_str = "\n".join(f"- {u}" for u in pack["gallery"][:10]) or "- (none)"

    raw = llm(
        WEBSITE_PROMPT.format(ctx=context[:2500], images=images_str,
                              lang_block=lang_svc.content_directive(language)),
        role="build", max_tokens=int(os.getenv("WEBSITE_MAX_TOKENS", "8000")), temperature=0.6,
    )
    html = _strip_html(raw)
    if "<html" not in html.lower() or len(html) < 800:
        html = _fallback_html(context, pack["hero"], language)
    html = _ensure_complete_html(html)

    _write(os.path.join(output_dir, "index.html"), html)
    return {"keywords": keywords, "images": pack["gallery"][:10]}


# ────────────────────── multi-page generation ────────────────────────
def _page_plan():
    """Page plan for generated sites.

    Default: the classic four-page business site. Setting
    FORGE_PAGES_PRESET=bms_demo switches to the 7-page academic-portal plan
    (login + a dashboard hub whose four sections each get their own page).
    The nav, sitemap, editor targeting and validation all follow PAGES."""
    classic = ["index", "about", "services", "contact"]
    presets = {
        "bms_demo": {
            "pages": ["index", "login", "dashboard", "students",
                      "faculty", "admissions", "campus_life"],
            "labels": {
                "index": "Home", "login": "Login", "dashboard": "Dashboard",
                "students": "Students", "faculty": "Faculty",
                "admissions": "Admissions", "campus_life": "Campus Life",
            },
        },
        "portal_demo": {
            "pages": ["index", "login", "dashboard", "services",
                      "gallery", "booking", "contact"],
            "labels": {
                "index": "Home", "login": "Login", "dashboard": "Dashboard",
                "services": "Services", "gallery": "Gallery",
                "booking": "Booking", "contact": "Contact",
            },
        },
    }
    preset_name = os.getenv("FORGE_PAGES_PRESET", "").strip()
    if preset_name in presets:
        plan = presets[preset_name]
        return plan["pages"], plan["labels"]
    return classic, {"index": "Home", "about": "About",
                    "services": "Services", "contact": "Contact"}


PAGES, PAGE_LABELS = _page_plan()

# briefs that belong to a preset rather than to a page name
PORTAL_BRIEFS = {
    "dashboard": (
        "A portal-style dashboard: a welcome band, a row of 4 KPI stats, and a "
        "2x2 grid of large clickable section cards that MUST link to "
        "services.html, gallery.html, booking.html and contact.html - each with "
        "an inline SVG icon, the section name and a one-line description. Add a "
        "short 'Latest updates' list. Reuse the shared CTA band and footer."
    ),
    "gallery": (
        "Hero band 'Gallery'. A masonry-style grid of 6 Pexels images with "
        "short captions, and a strip describing the work shown. Reuse the "
        "shared CTA band and footer."
    ),
    "booking": (
        "Hero band 'Book an appointment'. A clean booking form (name, phone, "
        "service select, preferred date, notes, submit button) beside an "
        "opening-hours card and three steps explaining what happens next. "
        "Reuse the shared footer."
    ),
}



DEFAULT_BRIEF = (
    "Hero header band with the page title + intro line, then well-structured "
    "sections of real content for this organisation: 2-3 informative cards or "
    "blocks with inline SVG icons where they fit, one supporting Pexels image, "
    "and a natural close. Reuse the shared CTA band and footer."
)

EXTRA_BRIEFS = {
    "login": (
        "A clean, centred login page: a single elevated card with the logo above "
        "it, an 'Email address' input, a 'Password' input with a show/hide eye "
        "toggle, a bold 'Sign in' gradient button with hover state, a 'Forgot "
        "password?' link and a small hint line. Include a short inline script: on "
        "submit, if both fields are non-empty, redirect to dashboard.html (demo "
        "behaviour), otherwise show an inline 'Enter both fields' warning. Keep "
        "the shared nav so the user can leave."
    ),
    "dashboard": (
        "A portal-style dashboard: a welcome band ('Welcome back' + a short line), "
        "a row of 4 KPI stat cards, then the centrepiece: a 2x2 grid of large, "
        "clickable section cards that MUST be anchor links to students.html, "
        "faculty.html, admissions.html and campus_life.html - each card has an "
        "inline SVG icon, the section name and a one-line description, and a "
        "hover lift. Add a short 'Recent notices' list under the grid. Reuse the "
        "shared CTA band and footer."
    ),
    "students": (
        "Hero header band 'Students'. A notices board (styled dated list of 5 "
        "items), a weekly timetable table, an exam-schedule table, and a results/"
        "resources strip with two cards (e-library, previous papers). Reuse the "
        "shared CTA band and footer."
    ),
    "faculty": (
        "Hero header band 'Faculty'. A directory grid of 6 member cards: Pexels "
        "portrait, name, designation, department, contact link. A 'Departments' "
        "side strip listing departments with counts. Reuse the shared CTA band "
        "and footer."
    ),
    "admissions": (
        "Hero header band 'Admissions'. A 3-step 'How to apply' process strip, an "
        "eligibility table (programme, eligibility, duration, intake), a key-dates "
        "card, and a fee-structure table. End with a bold 'Apply now' CTA band "
        "that links to contact.html."
    ),
    "campus_life": (
        "Hero header band 'Campus Life'. An events gallery (3 Pexels images with "
        "captions), an achievements card row, a clubs & societies strip, and a "
        "sports/facilities highlight. Reuse the shared CTA band and footer."
    ),
}

PAGES_CONFIG = {
    "index": (
        "Sticky translucent nav (blur backdrop) with logo + 4 links + a primary CTA button. "
        "Full-viewport hero: a Pexels background image with a dark gradient overlay, an eyebrow tag, "
        "a large bold headline, a supporting subheadline, and TWO CTAs (primary solid + secondary outline). "
        "A 'trust bar' strip under the hero (logos-as-text or stats like '500+ clients', 'Since 2014', '4.9★'). "
        "A 3-4 card feature grid, each card with an inline SVG icon, title, description, hover lift. "
        "A stats/highlights strip with 3-4 big numbers + labels on an accent gradient band. "
        "A testimonials section with 2-3 quotes, each with a person name, role, and small avatar image. "
        "A bold CTA band (gradient background) with headline + button. A rich multi-column footer."
    ),
    "about": (
        "Hero header band with page title + breadcrumb. An origin/story section pairing real prose with a "
        "Pexels image. A mission statement callout. A values grid (3-4 cards with icons). A team section with "
        "3-4 member placeholder cards (Pexels portrait image, name, role). A 'why choose us' section with "
        "checkmark bullet points beside a supporting image. Reuse the shared CTA band before the footer."
    ),
    "services": (
        "Hero header band with page title + intro line. A grid of detailed service cards: each with an image or "
        "icon, service name, a specific description, a short feature list, and a 'Starting at' price framing with "
        "a CTA. A comparison or process strip (how engagements work in 3 steps). Reuse the shared CTA band."
    ),
    "contact": (
        "Hero header band with page title. A two-column layout: a styled contact form (name, email, phone, "
        "message, submit button with hover state) on one side, and an info column on the other with an address "
        "block, phone/email, an opening-hours table, and social links (inline SVG icons). A full-width map "
        "placeholder (styled div / Pexels cityscape image with a pin). Reuse the shared footer."
    ),
}

MULTIPAGE_ONESHOT_PROMPT = """You are a world-class product designer and front-end engineer. Build a PREMIUM, modern 4-page business website that looks like it was crafted in Lovable, Framer, or by a top design studio — NOT a generic template.

BUSINESS INFO:
{ctx}

AVAILABLE IMAGES (real Pexels URLs — you MUST use these in <img> tags AND in CSS background-image; do NOT invent other image URLs):
{images}

Output ALL FOUR pages in ONE response. Separate each page with a line containing ONLY this exact marker:
===FORGE_PAGE:index===
===FORGE_PAGE:about===
===FORGE_PAGE:services===
===FORGE_PAGE:contact===

Put the marker line BEFORE each page's HTML. Page contents:
- index: {index_c}
- about: {about_c}
- services: {services_c}
- contact: {contact_c}

DESIGN SYSTEM (apply identically on ALL pages so the site feels like one product):
- Derive a cohesive, tasteful color palette from the business TYPE (e.g. spa = calm greens/cream, law firm = navy/gold, cafe = warm browns/amber, tech = indigo/cyan). Define it ONCE as CSS custom properties on :root (a primary, a darker primary, an accent, a light surface, a dark text) and reuse those variables everywhere. Use the SAME palette on every page.
- Use a Google Font: load Inter or Poppins via <link> and set it as the body font. Large, confident typography scale: hero headline ~clamp(2.5rem,6vw,4.5rem), bold weights for headings, relaxed line-height for body.
- Generous whitespace: large vertical section padding (py-20 / py-24), max-width content containers, comfortable gaps.
- Rounded corners (rounded-2xl on cards), subtle shadows (soft shadow-xl), and at least one gradient accent (hero overlay, CTA band, or stat strip) built from the palette variables.
- Smooth transitions on interactive elements: buttons and cards lift / change shade on hover (transition + transform/scale). Add focus styles for accessibility.

CONTENT (this is critical):
- Write REAL, SPECIFIC copy for THIS exact business. Real headlines, real service names and descriptions, real value props, real testimonial quotes with believable names. Absolutely NO Lorem Ipsum, NO 'placeholder text', NO generic 'Welcome to our website'.
- Every CTA has concrete action wording (e.g. 'Book a free consultation', 'Get your quote', 'Reserve a table'), not just 'Click here'.

IMAGERY:
- Use the provided Pexels URLs for the hero background (CSS background-image with a gradient overlay for text contrast), feature/service card images, team/testimonial avatars, and the contact map area. Every <img> needs meaningful alt text.

STRUCTURE & CONSISTENCY (EVERY page):
- Complete HTML document: <!DOCTYPE html><html lang="{html_lang}"><head>...</head><body>...</body></html>
- Tailwind CSS via CDN: <script src="https://cdn.tailwindcss.com"></script>
- IDENTICAL sticky top navigation on every page (same logo, same links, same CTA, blur/transparent-to-solid on scroll). Links: index.html (Home), about.html (About), services.html (Services), contact.html (Contact). Mark the current page's link as active.
- IDENTICAL multi-column footer on every page (business name, quick links, contact info, social icons, copyright).
- A proper <title> and <meta name="description"> per page; <meta name="viewport">.
- Mobile responsive: working hamburger menu on small screens, responsive grids.

POLISH (small inline JS/CSS only — no heavy libraries):
- Add CSS smooth scrolling (scroll-behavior:smooth on the html element) and smooth-scroll for in-page anchors.
- Add a lightweight scroll-reveal: elements with a .reveal class fade/slide in via an IntersectionObserver in an inline <script> at the end of <body>. Keep it tiny and self-contained per page.
- Nav background should turn solid on scroll via a small inline scroll listener.

MANDATORY:
- Include the exact comment <!--FORGE_AGENT_WIDGET--> right before </body> on EVERY page (do not omit it).
- Keep each page rich but efficient (clean markup, no redundant repetition) so all 4 complete pages fit in ONE response.
{lang_block}

Output ONLY the markers and raw HTML. No markdown fences, no commentary."""


def _split_oneshot_pages(raw: str) -> dict:
    """Parse a one-shot multi-page response into {page_name: html}.

    The model is asked to separate pages with a marker line, but it does not
    always comply exactly: it may write "===FORGE_PAGE:index ===", use a
    different number of "=" signs, or drop a marker altogether. The old parser
    matched one exact pattern, so a single malformed marker silently dropped
    that page - which then triggered a whole extra per-page LLM call and
    doubled the build time and cost for no visible reason.

    So the parsing is now deliberately forgiving:

    1. The marker pattern accepts surrounding whitespace and 3+ "=" signs.
    2. If a page is still missing (or a marker was unreadable), the page
       boundaries are recovered from the "<!DOCTYPE html>" / "<html" document
       starts in the response, in order, and matched to the expected page
       order. That recovers pages whose marker the model mangled.
    """
    import re as _re
    pages = {}

    # Marker tolerant of whitespace and any run of 3+ '=' characters.
    marker = r"=+\s*FORGE_PAGE\s*:\s*(index|about|services|contact)\s*=+"
    parts = _re.split(marker, raw, flags=_re.IGNORECASE)
    # parts = [pre, name1, html1, name2, html2, ...]
    i = 1
    while i + 1 < len(parts):
        name = parts[i].strip().lower()
        html = parts[i + 1]
        if name in PAGES and "<html" in html.lower():
            pages[name] = _ensure_complete_html(_strip_html(html))
        i += 2

    # Recovery pass: a page whose marker was missing or unparsable still
    # exists in the response as its own HTML document. Recover those and
    # attach them to the page names still missing, in document order.
    missing = [p for p in PAGES if p not in pages]
    if missing:
        docs = _re.findall(r"<!DOCTYPE\s+html.*?</html>", raw,
                           flags=_re.IGNORECASE | _re.DOTALL)
        if not docs:
            docs = _re.findall(r"<html.*?</html>", raw,
                               flags=_re.IGNORECASE | _re.DOTALL)
        # Only documents that were not already captured by a marker.
        captured = set()
        for html in pages.values():
            head = html[:200]
            for d in docs:
                if d[:200] == head or d[:120] in html[:400]:
                    captured.add(d[:120])
        spare = [d for d in docs if d[:120] not in captured]
        for name, doc in zip(missing, spare):
            pages[name] = _ensure_complete_html(_strip_html(doc))
        if spare:
            print(f"[forge] recovered {len(spare)} page(s) without a usable "
                  f"marker: {[n for n in missing][:len(spare)]}")

    return pages


def generate_multipage_website(context: str, output_dir: str,
                               design_notes: str = "",
                               language: str | None = None) -> dict:
    """Generate a multi-page website (index, about, services, contact).

    Primary path (2026-10-30): the four pages are generated as PARALLEL
    per-page calls. The old single one-shot call asked for all four pages in
    one response (~25K output tokens), and it was the slowest thing in the
    system: 258 s for the site, with the whole time spent streaming one
    enormous response. Four concurrent calls of ~6K tokens each finish in
    roughly the time of ONE page, because the provider streams them at the
    same time. Measured: one-shot 258 s vs parallel ~90-120 s.

    The one-shot path is kept as a fallback (if a parallel page fails, or
    BUILD_STRATEGY=oneshot is set), because it is occasionally cheaper.

    SEO is templated (no extra LLM calls) for speed.

    `design_notes` carries visual findings from a screenshot of the user's
    existing site (see vision_service), so an enhancement can preserve what
    worked and correct what did not instead of ignoring the original design.
    """
    keywords = _keywords_from_context(context)
    pack = image_pack(keywords, per_keyword=2)
    images_str = "\n".join(f"- {u}" for u in pack["gallery"][:10]) or "- (none)"
    notes = design_notes or ""

    pages_html = {}

    budget = int(os.getenv("WEBSITE_MAX_TOKENS", "16000"))
    oneshot_min = int(os.getenv("ONESHOT_MIN_TOKENS", "10000"))
    strategy = os.getenv("BUILD_STRATEGY", "parallel").lower()

    # ── Primary: parallel per-page calls ──
    if strategy != "oneshot":
        pages_html = _generate_pages_parallel(context, notes, images_str,
                                              language, budget, pack)
    else:
        print("[forge] BUILD_STRATEGY=oneshot - using the single-call path")

    # ── Fallback: the one-shot single call, for any page still missing ──
    missing = [p for p in PAGES if p not in pages_html]
    if missing and strategy != "oneshot" and set(PAGES) == {"index", "about", "services", "contact"}:
        # A parallel page failed. One shot can still produce the lot, so try
        # it before falling back to individual calls.
        if budget >= oneshot_min:
            print(f"[forge] {len(missing)} page(s) missing after the parallel "
                  f"pass - trying the one-shot call")
            try:
                raw = llm(
                    MULTIPAGE_ONESHOT_PROMPT.format(
                        ctx=context[:2500] + notes, images=images_str,
                        index_c=PAGES_CONFIG["index"], about_c=PAGES_CONFIG["about"],
                        services_c=PAGES_CONFIG["services"], contact_c=PAGES_CONFIG["contact"],
                        html_lang=lang_svc.html_lang(language),
                        lang_block=lang_svc.content_directive(language),
                    ),
                    role="build", max_tokens=budget, temperature=0.6,
                )
                pages_html.update(_split_oneshot_pages(raw))
            except Exception as e:
                print(f"[forge] one-shot multipage failed: {e}")
        missing = [p for p in PAGES if p not in pages_html]

    # ── Last resort: one call per page, in parallel ──
    if missing:
        workers = max(1, int(os.getenv("PAGE_CONCURRENCY", "4")))
        print(f"[forge] generating {len(missing)} page(s) "
              f"({min(workers, len(missing))} at a time): {missing}")

        def _one_page(page_name: str) -> tuple[str, str]:
            try:
                raw = llm(
                    _single_page_prompt(context + notes, page_name, images_str,
                                        language),
                    role="build", max_tokens=budget, temperature=0.6,
                )
                html = _strip_html(raw)
                if "<html" not in html.lower() or len(html) < 500:
                    html = _fallback_html(context, pack.get("hero", ""), language)
                return page_name, _ensure_complete_html(html)
            except Exception as e:
                print(f"[forge] page '{page_name}' failed, using fallback: {e}")
                return page_name, _ensure_complete_html(
                    _fallback_html(context, pack.get("hero", ""), language))

        if len(missing) == 1 or workers == 1:
            for p in missing:
                name, html = _one_page(p)
                pages_html[name] = html
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(workers, len(missing))) as ex:
                for name, html in ex.map(_one_page, missing):
                    pages_html[name] = html

    # ── Write all pages (nav + SEO guaranteed on each) ──
    biz_hint = (context or "").strip().split(".")[0][:40]
    hero_img = pack.get("hero", "")
    generated_pages = []

    # Structured data is built once from the business context and shared by every
    # page, so search engines see one consistent business identity.
    jsonld = ""
    try:
        from services.seo_service import build_local_business_jsonld
        jsonld = build_local_business_jsonld(context, biz_hint, hero_img)
    except Exception as e:
        print(f"[forge] JSON-LD skipped: {e}")

    for page_name in PAGES:
        if page_name in pages_html:
            html = _ensure_nav(pages_html[page_name], page_name, biz_hint)
            html = _strip_foreign_links(html)
            # The prompt asks for title/description and usually delivers, but
            # social tags and structured data are inconsistent - add whatever the
            # model left out rather than assuming it complied.
            try:
                from services.seo_service import ensure_social_tags, inject_jsonld
                html = ensure_social_tags(html, "", "", hero_img)
                html = inject_jsonld(html, jsonld)
            except Exception as e:
                print(f"[forge] SEO tags skipped for {page_name}: {e}")
            _write(os.path.join(output_dir, f"{page_name}.html"), html)
            generated_pages.append(f"{page_name}.html")

    # ── Templated SEO files (no LLM calls) ──
    try:
        from services.seo_service import generate_sitemap, generate_robots_txt
        _write(os.path.join(output_dir, "sitemap.xml"), generate_sitemap(".", generated_pages))
        _write(os.path.join(output_dir, "robots.txt"), generate_robots_txt("."))
    except Exception as e:
        print(f"[forge] SEO files skipped: {e}")

    return {"keywords": keywords, "images": pack["gallery"][:10], "pages": generated_pages}


def _generate_pages_parallel(context: str, notes: str, images_str: str,
                             language: str | None, budget: int,
                             pack: dict) -> dict:
    """Build all four pages concurrently, one call each.

    Each page is an independent LLM call of roughly a quarter of the tokens
    of the old one-shot call, and all four run at the same time. That is what
    makes it fast: the provider streams four responses concurrently instead
    of one enormous one.

    To stop four independent calls from looking like four different sites,
    a SHARED design brief (one palette, one font pairing, one nav/footer
    shape) is computed once and pasted into every page prompt, so the pages
    agree with each other.
    """
    from concurrent.futures import ThreadPoolExecutor

    shared = _shared_design_brief(context)

    def _build(page_name: str):
        try:
            raw = llm(
                _single_page_prompt(context + notes, page_name, images_str,
                                    language, shared=shared),
                role="build",
                # A single page needs far less than the full-site budget, and
                # a smaller cap is also faster. 12K comfortably holds one rich
                # page (measured ~6-9K tokens) without truncation.
                max_tokens=int(os.getenv("PAGE_MAX_TOKENS", "12000")),
                temperature=0.6,
            )
            html = _strip_html(raw)
            if "<html" not in html.lower() or len(html) < 2000:
                print(f"[forge] page '{page_name}' came back too small "
                      f"({len(html)} chars) - using the fallback")
                return page_name, _ensure_complete_html(
                    _fallback_html(context, pack.get("hero", ""), language))
            return page_name, _ensure_complete_html(html)
        except Exception as e:
            print(f"[forge] page '{page_name}' failed, using fallback: {e}")
            return page_name, _ensure_complete_html(
                _fallback_html(context, pack.get("hero", ""), language))

    workers = max(1, int(os.getenv("PAGE_CONCURRENCY", "4")))
    out = {}
    t0 = time.time()
    print(f"[forge] generating {len(PAGES)} pages in parallel "
          f"({min(workers, len(PAGES))} at a time)")
    with ThreadPoolExecutor(max_workers=min(workers, len(PAGES))) as ex:
        for name, html in ex.map(_build, PAGES):
            out[name] = html
    print(f"[forge] all pages done in {time.time() - t0:.0f}s")
    return out


def _shared_design_brief(context: str) -> str:
    """One design system shared by every page, so parallel pages still match.

    It is written by hand from the business text rather than generated: an
    extra LLM call would cost a full request's latency, which is exactly what
    this parallel path is trying to avoid. The palette is also given as exact
    CSS values rather than left for the model to choose - asking a reasoning
    model to pick colours was one of the things that made it deliberate for
    tens of thousands of tokens before writing any HTML.
    """
    c = (context or "").lower()
    palettes = [
        (("spa", "salon", "beauty", "yoga", "wellness", "clinic", "dental", "skin"),
         ("#3f7d5e", "#2a5940", "#c9a227", "#faf8f3", "#1d1f1c")),
        (("law", "legal", "attorney", "advocate"),
         ("#1b2a4a", "#0f1a30", "#c9a227", "#fbfaf7", "#15171c")),
        (("cafe", "coffee", "bakery", "restaurant", "bistro", "bar", "pizza"),
         ("#6b4423", "#4a2e18", "#d97706", "#fdf8f0", "#241a12")),
        (("plant", "garden", "florist", "nursery", "farm", "organic"),
         ("#2f6b46", "#1e4a30", "#d97706", "#faf7f0", "#1b1b18")),
        (("gym", "fitness", "sport", "football", "crossfit"),
         ("#23262b", "#121417", "#f97316", "#f7f7f8", "#121316")),
        (("school", "tutor", "education", "academy", "course", "training"),
         ("#1e40af", "#1a3690", "#f97316", "#f8fafc", "#111827")),
        (("real estate", "property", "interior", "architecture", "realty"),
         ("#334155", "#1e293b", "#b08d3f", "#fafafa", "#0f172a")),
        (("tech", "software", "startup", "saas", "agency", "studio", "consult"),
         ("#4f46e5", "#3730a3", "#06b6d4", "#fbfbff", "#111827")),
    ]
    primary, primary_dark, accent, surface, text = ("#4f46e5", "#3730a3", "#06b6d4",
                                                     "#fbfbff", "#111827")
    for keys, pal in palettes:
        if any(k in c for k in keys):
            primary, primary_dark, accent, surface, text = pal
            break

    return (
        "Design facts for every page (use them exactly):\n"
        f"- CSS variables on :root --color-primary:{primary}; --color-primary-dark:{primary_dark}; "
        f"--color-accent:{accent}; --color-surface:{surface}; --color-text:{text}. "
        "Use only these variables for colours.\n"
        "- Font: Inter for body, Space Grotesk for headings, via one Google Fonts <link>.\n"
        "- Nav on every page: sticky, transparent with a blur backdrop that turns solid on scroll; "
        "logo left; links Home / About / Services / Contact to index.html, about.html, services.html, "
        "contact.html; one CTA button right; this page's link marked active.\n"
        "- Footer on every page: four columns (brand + one line, quick links, contact details, social "
        "icons) over a copyright bar.\n"
        "- Section padding py-20/py-24, max-width container, rounded-2xl cards with soft shadows, "
        "one gradient accent band before the footer.\n"
    )


def _single_page_prompt(context: str, page_name: str, images_str: str,
                        language: str | None = None,
                        shared: str = "") -> str:
    """Prompt for ONE page of the site.

    Why this prompt is terse (measured, 2026-10-30):

    The first version of this prompt was long and advisory - "derive a
    palette from the business type", "think about the structure", a long list
    of design rules. Asking a reasoning model to make those decisions made it
    deliberate for tens of thousands of tokens BEFORE writing a single line of
    HTML: 26,000 reasoning tokens on a 4-page request, first token at 191
    seconds, and whole builds that ended with no HTML at all.

    The version that works gives the model every decision as a fact instead of
    asking it to make one. Measured on the same page spec:
      advisory prompt  ->  21 s, 0 reasoning tokens, 15K chars of HTML
      terse prompt     ->  34 s for all four pages in parallel, same quality
    With nothing to deliberate about, the model answers immediately.

    Keep this prompt short and factual. Every "you decide" or "think about"
    instruction brings the reasoning tax back.
    """
    spec = (PORTAL_BRIEFS.get(page_name) if
            os.getenv("FORGE_PAGES_PRESET", "").strip() == "portal_demo" else None)
    if not spec:
        spec = (PAGES_CONFIG.get(page_name) or EXTRA_BRIEFS.get(page_name)
                or DEFAULT_BRIEF)
    return (
        f"Write ONE page of a premium business website for {context[:300]}.\n"
        "Output ONLY the full HTML document (DOCTYPE to </html>). No commentary, "
        "no markdown fences.\n"
        f"{shared}"
        "Use Tailwind via CDN (https://cdn.tailwindcss.com) and the Inter font.\n"
        f"Images to use:\n{images_str}\n"
        f"PAGE CONTENT: {spec}\n"
        f"Include a sticky nav with these links: {NAV_STRING} and a CTA, a 4-column "
        "footer, mobile responsiveness with a hamburger menu, an inline "
        "IntersectionObserver scroll-reveal script, and the comment "
        "<!--FORGE_AGENT_WIDGET--> right before </body>.\n"
        "Keep the page compact: roughly 400-600 lines of HTML, one section per "
        "listed item, no repeated boilerplate blocks.\n"
        "Write real copy for this business.\n"
        f"{lang_svc.content_directive(language)}\n"
        "Output only the HTML."
    )


NAV_LINKS = [(f"{p}.html", PAGE_LABELS.get(p, p)) for p in PAGES]
NAV_STRING = " | ".join(f"{lbl} ({fn})" for fn, lbl in NAV_LINKS)


def _strip_foreign_links(html: str) -> str:
    """Remove anchors pointing at pages that are not in the page plan.

    Models habitually reuse the classic nav/footer links even when the plan
    has different pages; clicking one of those would 404.
    """
    import re as _re
    plan = {f"{p}.html" for p in PAGES}
    negative = "|".join(_re.escape(f) for f in sorted(plan))
    pattern = _re.compile(
        r'<a\b[^>]*href="(?!' + negative + r')([a-z_0-9]+\.html)"[^>]*>(.*?)</a>',
        _re.S | _re.I)
    return pattern.sub(r"\2", html)


def _ensure_nav(html: str, page_name: str, business: str = "") -> str:
    """Guarantee cross-page navigation exists.

    The generator asks the model for an identical nav on every page, but a
    single-page retry occasionally omits some links, which strands the visitor.
    Navigation is a functional requirement, not a stylistic one, so if any link
    is missing we prepend a minimal accessible nav rather than trusting the LLM.
    """
    missing = [href for href, _ in NAV_LINKS if href not in html]
    if not missing:
        return html

    brand = (business or "Home").strip()[:28] or "Home"
    items = []
    for href, label in NAV_LINKS:
        current = href.startswith(page_name)
        aria = ' aria-current="page"' if current else ""
        weight = "font-semibold" if current else "font-medium"
        items.append(
            f'<a href="{href}"{aria} class="{weight} px-3 py-2 rounded-lg '
            f'hover:bg-black/5 focus:outline-none focus:ring-2 focus:ring-offset-2">{label}</a>'
        )
    nav = (
        '<nav aria-label="Main navigation" '
        'style="position:sticky;top:0;z-index:9998;backdrop-filter:blur(10px)" '
        'class="w-full bg-white/85 border-b border-black/10">'
        '<div class="max-w-6xl mx-auto flex items-center justify-between gap-4 px-5 py-3">'
        f'<a href="index.html" class="font-bold tracking-tight">{brand}</a>'
        f'<div class="flex items-center gap-1 text-sm">{"".join(items)}</div>'
        '</div></nav>'
    )

    low = html.lower()
    i = low.find("<body")
    if i != -1:
        j = html.find(">", i)
        if j != -1:
            return html[:j + 1] + "\n" + nav + html[j + 1:]
    return nav + html


def _ensure_complete_html(html: str) -> str:
    """Repair truncated docs and guarantee the agent-widget marker exists."""
    low = html.lower()
    # Close an unterminated document so the browser still renders it.
    if "</html>" not in low:
        if "</body>" not in low:
            html = html.rstrip() + "\n<!--FORGE_AGENT_WIDGET-->\n</body>"
        html = html.rstrip() + "\n</html>"
    # Ensure a widget marker is present (so inject_agent_widget can wire it).
    if "<!--FORGE_AGENT_WIDGET-->" not in html and "forge-agent-btn" not in html:
        html = html.replace("</body>", "<!--FORGE_AGENT_WIDGET-->\n</body>", 1)
    return html


def _fallback_html(ctx: str, hero: str = "", language: str | None = None) -> str:
    safe = (ctx or "Your business").replace("<", "&lt;")[:500]
    img = f'<img src="{hero}" alt="hero" class="rounded-xl mt-6 w-full"/>' if hero else ""
    # This page only appears when generation failed outright. Its two strings are
    # still localised, because a visitor seeing sudden English on an otherwise
    # Hindi site is a more confusing failure than a plain one.
    li = lang_svc.info(language)
    headline = lang_svc.localize("Your business, online.", li)
    cta = lang_svc.localize("Get started", li)
    return f"""<!doctype html><html lang="{li['code']}"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Generated Landing</title>
<script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-slate-900 text-slate-100">
<main class="max-w-3xl mx-auto p-10">
<h1 class="text-4xl font-bold mb-4">{headline}</h1>
<p class="text-slate-300">{safe}</p>{img}
<a href="#" class="mt-6 inline-block bg-indigo-500 px-6 py-3 rounded-lg">{cta}</a>
</main><!--FORGE_AGENT_WIDGET--></body></html>"""


def _fallback_js() -> str:
    return ("document.querySelectorAll('a[href^=\"#\"]').forEach(a=>a.addEventListener('click',"
            "e=>{const t=document.querySelector(a.getAttribute('href'));"
            "if(t){e.preventDefault();t.scrollIntoView({behavior:'smooth'});}}));")


# ────────────────────────── 2. Agents (platform-native) ──────────────────────────
def generate_agent_config(context: str, agent_type: str = "support",
                          custom_purpose: str = "",
                          language: str | None = None) -> dict:
    """Produce a JSON agent config the platform can run directly (no files for the user).

    `language` sets the language of the customer-facing strings (greeting) and
    instructs the persona to converse in that language by default. The agent can
    still answer a visitor who writes in another language, because the runtime
    resolves each visitor's language per message.
    """
    agent_type = agent_type if agent_type in AGENT_TYPES else "custom"
    role_desc = AGENT_TYPES[agent_type]
    if agent_type == "custom" and custom_purpose:
        role_desc = custom_purpose

    actions = AGENT_PRIMARY_ACTIONS.get(agent_type, [])
    action_line = (
        f"\nThis agent's PRIMARY GOAL is to perform: {', '.join(actions)}. "
        "The system prompt must actively steer the conversation toward gathering "
        "the details that action needs, rather than only answering questions.\n"
        if actions else ""
    )

    data = call_json(
        f"""Design an AI agent for this business.
BUSINESS: {context[:1500]}
AGENT ROLE: {role_desc}{action_line}
Return JSON with EXACT keys:
{{
  "name": "short agent name",
  "system_prompt": "detailed system prompt (<=140 words) that makes the agent excel at its role for THIS business",
  "greeting": "first message the agent says to a user",
  "capabilities": ["3-5 concrete things this agent can do"],
  "sample_questions": ["3 example user questions"]
}}{_agent_language_block(language)}""",
        role="chat",
        # Raised from 700/1100 on 2026-10-30: the chat model is a reasoning
        # model, so it spends part of the budget thinking before it emits the
        # JSON. At 700 the response came back with finish_reason="length" -
        # the JSON only survived because it happened to finish just inside the
        # cap. The extra headroom costs a few hundred tokens and removes the
        # chance of a truncated, unparsable agent config.
        max_tokens=2000 if lang_svc.info(language)["code"] == "en" else 3000,
        temperature=0.5,
    )

    if not isinstance(data, dict) or "system_prompt" not in data:
        li = lang_svc.info(language)
        data = {
            "name": f"{agent_type.replace('_', ' ').title()} Agent",
            "system_prompt": f"You are a helpful {agent_type.replace('_', ' ')} agent. {role_desc}",
            "greeting": lang_svc.localize("Hi! How can I help you today?", li),
            "capabilities": ["Answer questions", "Help users", "Provide information"],
            "sample_questions": ["What do you offer?", "How does this work?", "Can you help me?"],
        }
    data["type"] = agent_type
    data["id"] = str(uuid.uuid4())
    data["primary_actions"] = actions
    data["language"] = lang_svc.info(language)["code"]
    return data


def _agent_language_block(language: str | None) -> str:
    """Language rules for an agent's persona and greeting."""
    li = lang_svc.info(language)
    if li["code"] == lang_svc.DEFAULT_LANG:
        return ""
    return (
        f"\n\nLANGUAGE:\n"
        f"This business serves {li['name']} ({li['native_name']}) speaking customers.\n"
        f'- Write "greeting" and "sample_questions" in {li["name"]} using '
        f"{li['script']} script.\n"
        f'- Write "system_prompt" in English (it is an internal instruction), but '
        f"it MUST tell the agent to converse with visitors in {li['name']} by "
        f"default, and to reply in whatever language a visitor writes in.\n"
        f'- "name" and "capabilities" may stay in English.'
    )


def generate_agents(context: str, output_dir: str,
                    agent_types: list[str] | None = None,
                    language: str | None = None) -> list[dict]:
    """Generate one or more agent configs. Defaults to a support agent."""
    agent_types = agent_types or ["support"]
    configs = [generate_agent_config(context, t, language=language) for t in agent_types]
    _write(os.path.join(output_dir, "agents.json"), json.dumps(configs, indent=2))
    return configs


# ────────────────────────── orchestration ──────────────────────────
def orchestrate_generation(business_context: str, agent_types: list[str] | None = None,
                           build_website: bool = True, workspace_id: str | None = None,
                           design_notes: str = "", language: str | None = None):
    """Generate assets for a workspace. Returns (workspace_id, context, meta).

    If `workspace_id` is provided (the real Supabase row id), it is used as the
    asset directory name AND the widget endpoint id, so the live chat widget
    always points at a workspace that actually exists in the database. When
    omitted, a fresh id is minted (used only for standalone/test generation).

    `design_notes` optionally carries visual findings from a screenshot of the
    user's existing site, used when enhancing rather than building from scratch.
    """
    workspace_id = workspace_id or str(uuid.uuid4())
    ws_dir = os.path.join(WORKSPACES_DIR, workspace_id)
    web_dir = os.path.join(ws_dir, "website")
    agents_dir = os.path.join(ws_dir, "agents")
    ensure_dir(web_dir)
    ensure_dir(agents_dir)

    print(f"[forge] generating workspace {workspace_id}")
    meta = {"website": None, "agents": []}

    if build_website:
        # Use multi-page generation if MULTIPAGE env is set (default: true)
        use_multipage = os.getenv("MULTIPAGE", "true").lower() in ("true", "1", "yes")
        if use_multipage:
            meta["website"] = generate_multipage_website(
                business_context, web_dir, design_notes=design_notes,
                language=language)
        else:
            meta["website"] = generate_website(business_context, web_dir,
                                               language=language)
        # Inject the agent chat widget into ALL generated pages.
        try:
            inject_agent_widget(workspace_id, web_dir, language=language)
        except Exception as e:
            print(f"[forge] widget injection skipped: {e}")
        create_zip(web_dir, os.path.join(ws_dir, "website.zip"))

    meta["language"] = lang_svc.info(language)["code"]
    meta["agents"] = generate_agents(business_context, agents_dir, agent_types,
                                     language=language)
    create_zip(agents_dir, os.path.join(ws_dir, "agents.zip"))

    return workspace_id, business_context, meta


def inject_agent_widget(workspace_id: str, web_dir: str,
                        language: str | None = None) -> None:
    """Replace the <!--FORGE_AGENT_WIDGET--> marker with a live chat widget
    pointing at this workspace's agent endpoint. Injects into ALL .html files."""
    widget = _agent_widget_snippet(workspace_id, language)
    for fname in os.listdir(web_dir):
        if not fname.endswith(".html"):
            continue
        fpath = os.path.join(web_dir, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            html = f.read()
        if "<!--FORGE_AGENT_WIDGET-->" in html:
            html = html.replace("<!--FORGE_AGENT_WIDGET-->", widget)
        elif "</body>" in html:
            html = html.replace("</body>", widget + "\n</body>")
        else:
            continue
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(html)


def _agent_widget_snippet(workspace_id: str, language: str | None = None) -> str:
    api = os.getenv("PUBLIC_API_BASE", "http://127.0.0.1:8000")
    li = lang_svc.info(language)
    # Localised once at generation time, so the widget carries no runtime
    # translation cost and works even if the language service is unavailable.
    t_title = lang_svc.localize("AI Assistant", li)
    t_ask = lang_svc.localize("Ask anything...", li)
    t_greet = lang_svc.localize("Hi! How can I help you today?", li)
    t_fast = lang_svc.localize(
        "You're sending messages very quickly. Please wait a moment and try again.", li)
    t_err = lang_svc.localize("Connection error.", li)
    t_mic = lang_svc.localize("Speak your message", li)
    locale = li["locale"]
    return f"""
<!-- Forge AI Agent Widget -->
<div id="forge-agent-btn" style="position:fixed;bottom:24px;right:24px;width:60px;height:60px;border-radius:50%;background:linear-gradient(135deg,#6366f1,#06b6d4);box-shadow:0 8px 24px rgba(99,102,241,.4);display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:99999;font-size:26px;">💬</div>
<div id="forge-agent-panel" style="position:fixed;bottom:96px;right:24px;width:340px;max-width:90vw;height:460px;background:#0f172a;border:1px solid rgba(148,163,184,.2);border-radius:16px;box-shadow:0 20px 50px rgba(0,0,0,.5);display:none;flex-direction:column;overflow:hidden;z-index:99999;font-family:system-ui,sans-serif;">
  <div style="padding:14px 16px;background:rgba(99,102,241,.15);color:#f1f5f9;font-weight:600;">{t_title}</div>
  <div id="forge-agent-msgs" style="flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px;color:#e2e8f0;font-size:14px;"></div>
  <form id="forge-agent-form" style="display:flex;align-items:center;border-top:1px solid rgba(148,163,184,.15);">
    <input id="forge-agent-input" placeholder="{t_ask}" style="flex:1;border:none;background:transparent;padding:12px;color:#f1f5f9;outline:none;font-size:14px;"/>
    <button type="button" id="forge-agent-mic" title="{t_mic}" aria-label="{t_mic}" style="display:none;border:none;background:transparent;color:#cbd5e1;padding:0 10px;cursor:pointer;font-size:17px;">&#127908;</button>
    <button id="forge-agent-send" style="border:none;background:#6366f1;color:#fff;padding:0 16px;height:44px;cursor:pointer;">&#8594;</button>
  </form>
</div>
<style>
@keyframes forge-blink {{ 0%,80%,100% {{ opacity:.25; transform:translateY(0) }} 40% {{ opacity:1; transform:translateY(-3px) }} }}
.forge-dot {{ width:6px;height:6px;border-radius:50%;background:#cbd5e1;display:inline-block;margin-right:3px;animation:forge-blink 1.4s infinite both }}
</style>
<script>
(function(){{
  var API="{api}", WS="{workspace_id}", hist=[], busy=false;
  var btn=document.getElementById('forge-agent-btn'), panel=document.getElementById('forge-agent-panel');
  var msgs=document.getElementById('forge-agent-msgs'), form=document.getElementById('forge-agent-form');
  var input=document.getElementById('forge-agent-input'), sendBtn=document.getElementById('forge-agent-send');
  var micBtn=document.getElementById('forge-agent-mic');
  var LOCALE="{locale}";
  // Voice is opt-in: replies are only spoken once the visitor has actually used
  // the microphone, so a text-only visitor never gets unexpected audio.
  var voiceMode=false, SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  var canSpeak=('speechSynthesis' in window);
  function say(txt){{
    if(!voiceMode||!canSpeak||!txt) return;
    try{{
      window.speechSynthesis.cancel();
      var u=new SpeechSynthesisUtterance(txt);
      u.lang=LOCALE; u.rate=1; u.pitch=1;
      // Pick a voice matching the language, else the browser reads e.g. Hindi
      // text with an English voice, which is unintelligible.
      var vs=window.speechSynthesis.getVoices()||[];
      var base=LOCALE.split('-')[0];
      var v=vs.filter(function(x){{return x.lang===LOCALE}})[0]
          ||vs.filter(function(x){{return x.lang&&x.lang.split('-')[0]===base}})[0];
      if(v) u.voice=v;
      window.speechSynthesis.speak(u);
    }}catch(e){{}}
  }}
  function bubble(role){{var d=document.createElement('div');d.style.alignSelf=role==='user'?'flex-end':'flex-start';d.style.background=role==='user'?'#6366f1':'rgba(148,163,184,.15)';d.style.padding='8px 12px';d.style.borderRadius='12px';d.style.maxWidth='80%';return d;}}
  function add(role,txt){{var d=bubble(role);d.textContent=txt;msgs.appendChild(d);msgs.scrollTop=msgs.scrollHeight;return d;}}
  function showTyping(){{
    var d=bubble('agent');d.id='forge-typing';
    d.setAttribute('aria-label','Assistant is typing');
    d.innerHTML='<span class="forge-dot"></span><span class="forge-dot" style="animation-delay:.2s"></span><span class="forge-dot" style="animation-delay:.4s"></span>';
    msgs.appendChild(d);msgs.scrollTop=msgs.scrollHeight;return d;
  }}
  btn.onclick=function(){{panel.style.display=panel.style.display==='flex'?'none':'flex';if(!msgs.children.length)add('agent',{t_greet!r});input.focus();}};

  if(SR){{
    micBtn.style.display='block';
    var rec=null;
    micBtn.onclick=function(){{
      if(busy) return;
      if(rec){{ try{{rec.stop()}}catch(e){{}} rec=null; micBtn.style.color='#cbd5e1'; return; }}
      try{{
        rec=new SR();
        rec.continuous=false; rec.interimResults=false;
        rec.lang=LOCALE;            // speak in the site's language, not en-US
        voiceMode=true;             // from now on, read replies aloud
        micBtn.style.color='#f87171';
        rec.onresult=function(ev){{
          var t=ev.results[0][0].transcript;
          input.value=t; rec=null; micBtn.style.color='#cbd5e1';
          form.dispatchEvent(new Event('submit'));
        }};
        rec.onerror=function(){{ rec=null; micBtn.style.color='#cbd5e1'; }};
        rec.onend=function(){{ rec=null; micBtn.style.color='#cbd5e1'; }};
        rec.start();
      }}catch(e){{ rec=null; micBtn.style.color='#cbd5e1'; }}
    }};
  }}

  form.onsubmit=async function(e){{
    e.preventDefault();
    var m=input.value.trim(); if(!m||busy) return;
    busy=true; input.disabled=true; sendBtn.disabled=true; sendBtn.style.opacity='.5';
    add('user',m); input.value='';
    var typing=showTyping();
    try{{
      var r=await fetch(API+'/api/workspaces/'+WS+'/agent/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{message:m,history:hist,locale:LOCALE}})}});
      typing.remove();
      if(r.status===429){{ add('agent',{t_fast!r}); }}
      else {{
        var d=await r.json();
        add('agent',d.reply||'...');
        say(d.reply);
        hist.push({{role:'user',content:m}}); hist.push({{role:'assistant',content:d.reply}});
      }}
    }}catch(err){{ typing.remove(); add('agent',{t_err!r}); }}
    busy=false; input.disabled=false; sendBtn.disabled=false; sendBtn.style.opacity='1'; input.focus();
  }};
}})();
</script>"""
