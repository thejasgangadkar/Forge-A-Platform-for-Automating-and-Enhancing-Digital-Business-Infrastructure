"""Website scraper — deep, multi-page, JS-aware.

Primary engine: Crawl4AI (async-native, LLM-ready markdown output).
Fallback chain: Crawl4AI → Playwright (in thread) → BeautifulSoup/requests.

Returns a structured dict with clean merged `text` field.
"""
import asyncio
import os
import re
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

SHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                         "generated_workspaces", "_scrape_shots")

# Internal link keywords worth following for richer business context.
FOLLOW_KEYWORDS = ("about", "service", "product", "pricing", "price", "menu",
                   "contact", "team", "work", "feature", "solution", "shop")


# ═══════════════════════════════════════════════════════════════════════
#  CRAWL4AI — PRIMARY ENGINE (async-native)
# ═══════════════════════════════════════════════════════════════════════

def _build_run_config(CrawlerRunConfig):
    """Build a CrawlerRunConfig using only params the installed version supports.

    Configures robustness for real-world business sites: a sane page timeout,
    waits for network idle, dismisses cookie/consent overlays, and captures a
    screenshot. Any param missing in this crawl4ai version is skipped.
    """
    import inspect
    supported = set(inspect.signature(CrawlerRunConfig.__init__).parameters)
    desired = {
        "word_count_threshold": 50,
        "page_timeout": 30000,            # ~30s per page for slow business sites
        "wait_until": "domcontentloaded", # forgiving: heavy sites rarely reach networkidle
        "magic": True,                    # auto-handle popups/overlays if present
        "remove_overlay_elements": True,  # strip cookie/consent banners
        "remove_consent_popups": True,
        "scan_full_page": True,           # trigger lazy-loaded content
        "screenshot": True,
        "user_agent": UA,
    }
    kwargs = {k: v for k, v in desired.items() if k in supported}
    try:
        return CrawlerRunConfig(**kwargs)
    except Exception:
        # Last-resort: minimal config that always works.
        try:
            return CrawlerRunConfig(word_count_threshold=50)
        except Exception:
            return CrawlerRunConfig()


async def _scrape_crawl4ai(url: str, max_pages: int = 5) -> dict | None:
    """Primary scraper: uses Crawl4AI for async, JS-aware, LLM-ready output."""
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    except ImportError:
        return None

    try:
        os.makedirs(SHOTS_DIR, exist_ok=True)

        # Browser config — always set a real User-Agent so business sites
        # don't serve us a bot wall. Guard each kwarg against API drift.
        browser_kwargs = {"headless": True}
        try:
            import inspect
            _bp = set(inspect.signature(BrowserConfig.__init__).parameters)
            if "user_agent" in _bp:
                browser_kwargs["user_agent"] = UA
            if "viewport_width" in _bp:
                browser_kwargs["viewport_width"] = 1366
            if "viewport_height" in _bp:
                browser_kwargs["viewport_height"] = 900
        except Exception:
            pass
        browser_config = BrowserConfig(**browser_kwargs)

        # Run config — only pass kwargs supported by the installed crawl4ai
        # version so we degrade gracefully across releases.
        run_config = _build_run_config(CrawlerRunConfig)

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)

            if not result or not result.success:
                return None

            # Extract metadata
            title = ""
            desc = ""
            if result.metadata:
                title = result.metadata.get("title", "") or ""
                desc = result.metadata.get("description", "") or ""

            # Get clean text (prefer markdown for LLM-readiness)
            text = result.markdown or result.cleaned_html or ""
            headings = _extract_headings_from_markdown(text)
            images = _extract_images_from_html(result.html or "", url)

            # Get internal links to follow
            links = _extract_follow_links(result.html or "", url)

            # Follow internal pages
            pages_text = [f"[PAGE: {url}]\n{text[:5000]}"]
            for link in links[:max_pages - 1]:
                try:
                    sub_result = await crawler.arun(url=link, config=run_config)
                    if sub_result and sub_result.success:
                        sub_text = sub_result.markdown or sub_result.cleaned_html or ""
                        if sub_text:
                            pages_text.append(f"[PAGE: {link}]\n{sub_text[:3000]}")
                except Exception:
                    continue

            merged = "\n\n".join(pages_text)[:14000]

            # Screenshot
            shot_path = None
            if hasattr(result, 'screenshot') and result.screenshot:
                import base64
                safe = "".join(c for c in url if c.isalnum())[:40] or "site"
                shot_path = os.path.join(SHOTS_DIR, f"{safe}.png")
                try:
                    with open(shot_path, "wb") as f:
                        f.write(base64.b64decode(result.screenshot))
                except Exception:
                    shot_path = None

            return {
                "title": title,
                "meta_description": desc,
                "headings": headings[:30],
                "images": images[:20],
                "text": merged,
                "screenshot": shot_path,
                "engine": "crawl4ai",
                "pages_crawled": len(pages_text),
            }
    except Exception as e:
        print(f"[scraper] crawl4ai failed: {e}")
        return None


def _extract_headings_from_markdown(md: str) -> list:
    """Extract headings from markdown text (lines starting with #)."""
    headings = []
    for line in md.split("\n"):
        line = line.strip()
        if line.startswith("#"):
            h = line.lstrip("#").strip()
            if h and len(h) < 100:
                headings.append(h)
    return headings[:30]


def _extract_images_from_html(html: str, base_url: str) -> list:
    """Extract image URLs from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    imgs = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = urljoin(base_url, src)
        if src.startswith("http"):
            imgs.append(src)
    return imgs


def _extract_follow_links(html: str, base_url: str) -> list:
    """Extract internal links worth following."""
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if urlparse(href).netloc != base_host:
            continue
        label = (a.get_text(strip=True) + " " + href).lower()
        if any(k in label for k in FOLLOW_KEYWORDS):
            href = href.split("#")[0].rstrip("/")
            if href and href != base_url.rstrip("/"):
                links.append(href)
    seen, ordered = set(), []
    for l in links:
        if l not in seen:
            seen.add(l); ordered.append(l)
    return ordered[:5]


# ═══════════════════════════════════════════════════════════════════════
#  PLAYWRIGHT FALLBACK (sync, run in thread)
# ═══════════════════════════════════════════════════════════════════════

def _clean(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "svg", "form"]):
        tag.extract()
    text = soup.get_text(separator=" ")
    lines = (ln.strip() for ln in text.splitlines())
    chunks = (p.strip() for ln in lines for p in ln.split("  "))
    text = " ".join(c for c in chunks if c)
    return re.sub(r"\s{2,}", " ", text).strip()


def _meta(soup: BeautifulSoup, name=None, prop=None):
    if name:
        m = soup.find("meta", attrs={"name": name})
    else:
        m = soup.find("meta", attrs={"property": prop})
    return m["content"].strip() if m and m.get("content") else ""


def _parse(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string.strip() if soup.title and soup.title.string else "")
    desc = _meta(soup, name="description") or _meta(soup, prop="og:description")
    headings = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"]) if h.get_text(strip=True)][:30]
    imgs = _extract_images_from_html(html, base_url)
    links = _extract_follow_links(html, base_url)
    return {
        "title": title,
        "meta_description": desc,
        "headings": headings,
        "images": imgs[:20],
        "text": _clean(soup),
        "links": links,
    }


def _scrape_playwright(url: str, max_pages: int = 4) -> dict | None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    try:
        os.makedirs(SHOTS_DIR, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900})
            page = ctx.new_page()

            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            try:
                page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                pass
            home = _parse(page.content(), url)

            shot_path = None
            safe = "".join(c for c in url if c.isalnum())[:40] or "site"
            shot_path = os.path.join(SHOTS_DIR, f"{safe}.png")
            try:
                page.screenshot(path=shot_path, full_page=False)
            except Exception:
                shot_path = None

            pages_text = [f"[PAGE: {url}]\n{home['text'][:4000]}"]
            all_imgs = list(home["images"])
            all_heads = list(home["headings"])
            for link in home["links"][: max_pages - 1]:
                try:
                    page.goto(link, wait_until="domcontentloaded", timeout=15000)
                    sub = _parse(page.content(), link)
                    if sub["text"]:
                        pages_text.append(f"[PAGE: {link}]\n{sub['text'][:3000]}")
                    all_imgs.extend(sub["images"])
                    all_heads.extend(sub["headings"])
                except Exception:
                    continue

            browser.close()

        merged = "\n\n".join(pages_text)[:14000]
        seen, imgs = set(), []
        for i in all_imgs:
            if i not in seen:
                seen.add(i); imgs.append(i)

        return {
            "title": home["title"],
            "meta_description": home["meta_description"],
            "headings": all_heads[:30],
            "images": imgs[:20],
            "text": merged,
            "screenshot": shot_path,
            "engine": "playwright",
            "pages_crawled": len(pages_text),
        }
    except Exception as e:
        print(f"[scraper] playwright failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════
#  BEAUTIFULSOUP/REQUESTS FALLBACK
# ═══════════════════════════════════════════════════════════════════════

def _scrape_requests(url: str) -> dict:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, verify=False, timeout=15)
        r.raise_for_status()
        d = _parse(r.text, url)
        pages_text = [f"[PAGE: {url}]\n{d['text'][:5000]}"]
        for link in d["links"][:2]:
            try:
                rr = requests.get(link, headers={"User-Agent": UA}, verify=False, timeout=12)
                if rr.ok:
                    sd = _parse(rr.text, link)
                    if sd["text"]:
                        pages_text.append(f"[PAGE: {link}]\n{sd['text'][:3000]}")
            except Exception:
                continue
        d["text"] = "\n\n".join(pages_text)[:14000]
        d["screenshot"] = None
        d["engine"] = "requests"
        d["pages_crawled"] = len(pages_text)
        return d
    except Exception as e:
        return {"title": "", "meta_description": "", "headings": [], "images": [],
                "text": f"Error scraping website: {e}", "screenshot": None,
                "engine": "error", "pages_crawled": 0}


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINTS
# ═══════════════════════════════════════════════════════════════════════

async def scrape_website_structured_async(url: str) -> dict:
    """Primary async entry point. Fallback chain: Crawl4AI -> Playwright -> BS4.

    This is the function all FastAPI endpoints should call.
    """
    # Try 1: Crawl4AI (async-native, best quality)
    try:
        data = await _scrape_crawl4ai(url)
        if data and data.get("text") and not data["text"].startswith("Error"):
            return data
    except Exception as e:
        print(f"[scraper] crawl4ai entry failed: {e}")

    # Try 2: Playwright (run in thread to avoid async loop conflict)
    try:
        data = await asyncio.to_thread(_scrape_playwright, url)
        if data and data.get("text") and not data["text"].startswith("Error"):
            return data
    except Exception as e:
        print(f"[scraper] playwright entry failed: {e}")

    # Try 3: BeautifulSoup/requests (simplest fallback) — never raises.
    return _scrape_requests(url)


def scrape_website_structured(url: str) -> dict:
    """Sync entry point (for backward compatibility). Runs the async version.

    When called from within a running event loop (e.g. an async FastAPI
    endpoint like /api/chat), we cannot use asyncio.run() on this thread.
    Instead we offload the FULL async pipeline to a fresh worker thread, which
    has no event loop, so asyncio.run() works there and Crawl4AI (the intended
    PRIMARY engine) runs properly. Falls back to Playwright then requests
    exactly as the async pipeline does. Never raises out of this entry point.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Inside a running loop: run the full async pipeline in a worker thread.
        from concurrent.futures import ThreadPoolExecutor

        def _run_in_thread():
            try:
                return asyncio.run(scrape_website_structured_async(url))
            except Exception as e:
                print(f"[scraper] async pipeline in thread failed: {e}")
                # Last-resort fallbacks (already-sync engines).
                try:
                    pw = _scrape_playwright(url)
                    if pw and pw.get("text") and not pw["text"].startswith("Error"):
                        return pw
                except Exception:
                    pass
                return _scrape_requests(url)

        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(_run_in_thread).result()
        except Exception as e:
            print(f"[scraper] threaded scrape failed: {e}")
            return _scrape_requests(url)
    else:
        try:
            return asyncio.run(scrape_website_structured_async(url))
        except Exception as e:
            print(f"[scraper] scrape failed: {e}")
            return _scrape_requests(url)


async def scrape_website_async(url: str) -> str:
    """Convenience: returns just the text."""
    data = await scrape_website_structured_async(url)
    return data.get("text", "")


def scrape_website(url: str) -> str:
    """Sync convenience: returns just the text."""
    return scrape_website_structured(url).get("text", "")
