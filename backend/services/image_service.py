"""Image service — fetches relevant stock photos for generated sites.

Provider-agnostic: tries Pexels first, falls back to Lorem Picsum (no key).
Returns plain image URLs that can be dropped straight into <img src=...>.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()
# Load the documented control panel (forge.config.env) with priority.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "forge.config.env"), override=True)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PEXELS_SEARCH = "https://api.pexels.com/v1/search"


def _picsum(n: int, seed: str = "forge"):
    # Deterministic-ish placeholder set; always works, no key.
    return [f"https://picsum.photos/seed/{seed}-{i}/1200/800" for i in range(n)]


def search_images(query: str, count: int = 6, orientation: str = "landscape") -> list[str]:
    """Return up to `count` image URLs matching `query`."""
    if PEXELS_API_KEY:
        try:
            r = requests.get(
                PEXELS_SEARCH,
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": query, "per_page": count, "orientation": orientation},
                timeout=12,
            )
            if r.ok:
                photos = r.json().get("photos", [])
                urls = [p["src"].get("large2x") or p["src"].get("large") for p in photos]
                urls = [u for u in urls if u]
                if urls:
                    return urls
        except Exception as e:
            print(f"[image] pexels failed: {e}")
    seed = "".join(c for c in query.lower() if c.isalnum())[:12] or "forge"
    return _picsum(count, seed)


def image_pack(business_keywords: list[str], per_keyword: int = 2) -> dict:
    """Build a small library of images keyed by topic for a website.

    Returns e.g. {"hero": url, "gallery": [urls...], "by_keyword": {...}}.
    """
    by_keyword: dict[str, list[str]] = {}
    gallery: list[str] = []
    for kw in business_keywords[:5]:
        imgs = search_images(kw, count=per_keyword)
        by_keyword[kw] = imgs
        gallery.extend(imgs)

    if not gallery:
        gallery = _picsum(6)

    return {
        "hero": gallery[0] if gallery else _picsum(1)[0],
        "gallery": gallery,
        "by_keyword": by_keyword,
    }
