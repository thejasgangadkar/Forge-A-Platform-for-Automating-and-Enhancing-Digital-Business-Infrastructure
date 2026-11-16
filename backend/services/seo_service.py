"""SEO and Meta Generation Service.

Auto-generates: page titles, meta descriptions, Open Graph tags,
sitemap.xml, and robots.txt for generated websites.
"""
from services.llm_service import call_json


def generate_seo_meta(context: str, page_name: str) -> dict:
    """Generate SEO metadata for a page using the LLM.

    Returns: {"title": str, "description": str, "og_title": str, "og_description": str}
    """
    data = call_json(
        f"Business info: {context[:800]}\nPage: {page_name}\n\n"
        "Generate SEO metadata. Return JSON with these exact keys:\n"
        '{"title": "<max 60 chars>", "description": "<max 160 chars>", '
        '"og_title": "<max 60 chars>", "og_description": "<max 160 chars>"}',
        role="chat", max_tokens=200, temperature=0.3,
    )
    # Ensure all keys exist with defaults
    return {
        "title": data.get("title", f"{page_name.title()} - Business")[:60],
        "description": data.get("description", "")[:160],
        "og_title": data.get("og_title", data.get("title", ""))[:60],
        "og_description": data.get("og_description", data.get("description", ""))[:160],
    }


def inject_seo_tags(html: str, meta: dict) -> str:
    """Inject title and meta tags into an HTML page's <head>."""
    title_tag = f"<title>{meta['title']}</title>"
    meta_tags = (
        f'<meta name="description" content="{meta["description"]}">\n'
        f'<meta property="og:title" content="{meta["og_title"]}">\n'
        f'<meta property="og:description" content="{meta["og_description"]}">\n'
        f'<meta property="og:type" content="website">\n'
        f'<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{meta["og_title"]}">\n'
        f'<meta name="twitter:description" content="{meta["og_description"]}">'
    )

    # Replace existing title or insert after <head>
    if "<title>" in html:
        import re
        html = re.sub(r"<title>.*?</title>", title_tag, html, count=1)
    elif "<head>" in html:
        html = html.replace("<head>", f"<head>\n{title_tag}", 1)

    # Insert meta tags after <head> or after title
    if "</head>" in html:
        html = html.replace("</head>", f"{meta_tags}\n</head>", 1)

    return html


def generate_sitemap(base_url: str, pages: list[str]) -> str:
    """Generate sitemap.xml content for the given pages."""
    urls = "\n".join(
        f"  <url>\n    <loc>{base_url}/{p}</loc>\n    <priority>{'1.0' if p == 'index.html' else '0.8'}</priority>\n  </url>"
        for p in pages
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'{urls}\n'
        '</urlset>'
    )


def generate_robots_txt(base_url: str) -> str:
    """Generate a standard robots.txt."""
    return f"User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n"


# ─── JSON-LD structured data ─────────────────────────────────────────
def build_local_business_jsonld(context: str, business_name: str,
                                image: str = "") -> str:
    """Build a schema.org LocalBusiness JSON-LD block.

    Structured data is what lets search engines show hours, phone number and
    address directly in results, which matters more than meta tags for the local
    service businesses Forge targets. Fields are extracted from the business
    description and omitted when genuinely unknown - publishing invented opening
    hours or a made-up phone number would be worse than publishing nothing.
    """
    import json
    import re

    text = context or ""

    phone = ""
    m = re.search(r"(\+?\d[\d\s\-()]{7,}\d)", text)
    if m:
        phone = m.group(1).strip()

    email = ""
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    if m:
        # The character class matches dots, so a sentence-ending period gets
        # swallowed into the address. Publishing an invalid email in structured
        # data is worse than omitting it.
        email = m.group(0).rstrip(".")

    data = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": business_name or "Business",
    }
    desc = " ".join(text.split())[:300]
    if desc:
        data["description"] = desc
    if phone:
        data["telephone"] = phone
    if email:
        data["email"] = email
    if image:
        data["image"] = image

    # Only claim a location when the text actually names one.
    m = re.search(r"\bin\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)", text)
    if m:
        data["address"] = {"@type": "PostalAddress",
                           "addressLocality": m.group(1).strip()}

    return ('<script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False) + "</script>")


def inject_jsonld(html: str, jsonld: str) -> str:
    """Insert a JSON-LD block into <head>, replacing any previous one."""
    import re
    if not jsonld:
        return html
    html = re.sub(r'<script type="application/ld\+json">.*?</script>', "",
                  html, flags=re.S)
    if "</head>" in html:
        return html.replace("</head>", f"{jsonld}\n</head>", 1)
    return html


def ensure_social_tags(html: str, title: str, description: str,
                       image: str = "") -> str:
    """Guarantee Open Graph and Twitter card tags exist.

    The generator prompt asks for a title and meta description, and usually
    produces them, but social tags are inconsistent - so rather than trusting the
    model, any missing tag is added from the page's own title/description.
    """
    import re

    if not title:
        m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        title = (m.group(1).strip() if m else "")
    if not description:
        m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']',
                      html, re.S | re.I)
        description = (m.group(1).strip() if m else "")

    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")

    wanted = [
        ("og:title", esc(title)),
        ("og:description", esc(description)),
        ("og:type", "website"),
        ("twitter:card", "summary_large_image"),
        ("twitter:title", esc(title)),
        ("twitter:description", esc(description)),
    ]
    if image:
        wanted += [("og:image", esc(image)), ("twitter:image", esc(image))]

    additions = []
    for key, value in wanted:
        if not value:
            continue
        if re.search(rf'(property|name)=["\']{re.escape(key)}["\']', html, re.I):
            continue
        attr = "property" if key.startswith("og:") else "name"
        additions.append(f'<meta {attr}="{key}" content="{value}">')

    if not additions:
        return html
    block = "\n".join(additions)
    if "</head>" in html:
        return html.replace("</head>", f"{block}\n</head>", 1)
    return html
