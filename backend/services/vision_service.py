"""Vision analysis of scraped page screenshots.

The scraper already captures a screenshot of a pasted site, but text alone loses
everything visual: the colour palette, how dense the layout is, whether it looks
dated, whether the imagery is decent. When the task is "make me a better version
of this site", those cues are the whole point.

A vision model reads the screenshot and returns structured design notes, which
are folded into the generation prompt so the rebuild deliberately keeps what
worked and fixes what did not.

Entirely optional: without a key, model, or screenshot this returns an empty dict
and generation proceeds on text alone. Website enhancement must never fail
because a nice-to-have signal was unavailable.
"""
from __future__ import annotations

import base64
import json
import os

from services.llm_service import _safe_json

# Benchmarked 2026-08-19 (tests/bench_vision_models.py): this model answered in
# 5.6s with valid JSON, while the larger llama-3.2 vision models either timed out
# on the free tier or replied in prose. Overridable, since endpoints get retired.
VISION_MODEL = os.getenv("VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl")
VISION_PROVIDER = os.getenv("VISION_PROVIDER", "nvidia")

# Vision requests carry a base64 image, so they are far larger and slower than
# text calls. Anything past this and it is not worth blocking generation.
VISION_TIMEOUT = int(os.getenv("VISION_TIMEOUT", "60"))

# NIM rejects oversized inline images; a downscaled screenshot is plenty for
# judging layout and colour.
MAX_IMAGE_BYTES = int(os.getenv("VISION_MAX_IMAGE_BYTES", str(180_000)))

PROMPT = """You are a senior web designer reviewing a screenshot of a business website.

Describe what you SEE, then judge it. Be specific and honest - this feeds a rebuild.

Return ONLY JSON with these exact keys:
{
  "palette": ["up to 4 dominant colours as hex codes you actually observe"],
  "layout": "one sentence on the structure (hero style, column count, density)",
  "style": "2-4 words, e.g. 'dated corporate', 'clean minimal', 'cluttered retail'",
  "typography": "one short phrase on the type treatment",
  "imagery": "one short phrase on photo quality and usage",
  "strengths": ["up to 3 things genuinely worth preserving"],
  "weaknesses": ["up to 4 concrete visual problems"],
  "recommendations": ["up to 4 specific, actionable improvements"]
}

Judge only what is visible. Do not invent brand names, copy, or colours."""


def is_available() -> bool:
    """Whether vision analysis can run in this deployment."""
    if os.getenv("VISION_ENABLED", "true").lower() not in ("true", "1", "yes"):
        return False
    key = "NVIDIA_API_KEY" if VISION_PROVIDER == "nvidia" else "OPENROUTER_API_KEY"
    return bool(os.getenv(key))


def _encode_image(path: str) -> tuple[str, str] | None:
    """Read an image as base64. Returns (b64, mime) or None if unusable."""
    try:
        if not path or not os.path.isfile(path):
            return None
        size = os.path.getsize(path)
        if size == 0:
            return None

        data = open(path, "rb").read()

        # Mime must describe the BYTES being sent, not the file on disk:
        # downscaling re-encodes a PNG as JPEG, and mislabelling it makes the
        # vision endpoint reject the payload.
        ext = os.path.splitext(path)[1].lower()
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"

        if len(data) > MAX_IMAGE_BYTES:
            smaller = _downscale(data)
            if smaller:
                data, mime = smaller, "image/jpeg"
            if len(data) > MAX_IMAGE_BYTES:
                print(f"[vision] screenshot still {len(data)} bytes after "
                      "downscaling; skipping analysis")
                return None

        return base64.b64encode(data).decode("ascii"), mime
    except Exception as e:
        print(f"[vision] could not read screenshot: {e}")
        return None


def _downscale(data: bytes) -> bytes | None:
    """Shrink a screenshot to fit the inline size budget.

    Pillow ships with crawl4ai, but this stays optional: if it is missing we
    simply skip analysis rather than breaking the build.
    """
    try:
        import io
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        # A 1024px-wide render preserves layout and colour cues while cutting
        # size dramatically. Full-page screenshots can be very tall.
        img.thumbnail((1024, 1400))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=72, optimize=True)
        return out.getvalue()
    except ImportError:
        print("[vision] Pillow unavailable; cannot downscale screenshot")
        return None
    except Exception as e:
        print(f"[vision] downscale failed: {e}")
        return None


def analyze_screenshot(path: str) -> dict:
    """Analyse a page screenshot. Returns {} when unavailable - never raises."""
    if not is_available():
        return {}

    encoded = _encode_image(path)
    if not encoded:
        return {}
    b64, mime = encoded

    try:
        from openai import OpenAI

        base = ("https://integrate.api.nvidia.com/v1" if VISION_PROVIDER == "nvidia"
                else "https://openrouter.ai/api/v1")
        key = os.getenv("NVIDIA_API_KEY" if VISION_PROVIDER == "nvidia"
                        else "OPENROUTER_API_KEY")
        client = OpenAI(api_key=key, base_url=base,
                        timeout=VISION_TIMEOUT, max_retries=0)

        resp = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }],
            max_tokens=700,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        # Vision is an enhancement, so a failure is logged and swallowed.
        print(f"[vision] analysis unavailable ({VISION_MODEL}): {str(e)[:160]}")
        return {}

    data = _safe_json(raw)
    if not isinstance(data, dict) or not data:
        print("[vision] model returned no usable JSON")
        return {}

    return _normalise(data)


def _normalise(data: dict) -> dict:
    """Coerce the model's output into the documented shape."""
    def as_list(value, limit: int) -> list[str]:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if str(v).strip()][:limit]

    def as_text(value) -> str:
        return str(value).strip()[:200] if value else ""

    palette = [c for c in as_list(data.get("palette"), 4)
               if c.startswith("#") and 4 <= len(c) <= 9]

    return {
        "palette": palette,
        "layout": as_text(data.get("layout")),
        "style": as_text(data.get("style")),
        "typography": as_text(data.get("typography")),
        "imagery": as_text(data.get("imagery")),
        "strengths": as_list(data.get("strengths"), 3),
        "weaknesses": as_list(data.get("weaknesses"), 4),
        "recommendations": as_list(data.get("recommendations"), 4),
        "model": VISION_MODEL,
    }


def format_for_prompt(analysis: dict) -> str:
    """Render an analysis as a prompt block. Empty string when there is nothing."""
    if not analysis:
        return ""

    lines = ["", "VISUAL ANALYSIS OF THEIR CURRENT SITE (from a screenshot):"]
    if analysis.get("style"):
        lines.append(f"- Current style: {analysis['style']}")
    if analysis.get("layout"):
        lines.append(f"- Current layout: {analysis['layout']}")
    if analysis.get("palette"):
        lines.append(f"- Colours observed: {', '.join(analysis['palette'])}")
    if analysis.get("typography"):
        lines.append(f"- Typography: {analysis['typography']}")
    if analysis.get("imagery"):
        lines.append(f"- Imagery: {analysis['imagery']}")
    if analysis.get("strengths"):
        lines.append("- KEEP these strengths: " + "; ".join(analysis["strengths"]))
    if analysis.get("weaknesses"):
        lines.append("- FIX these problems: " + "; ".join(analysis["weaknesses"]))
    if analysis.get("recommendations"):
        lines.append("- Apply these improvements: " + "; ".join(analysis["recommendations"]))
    lines.append(
        "Build a clearly BETTER site: keep the brand's recognisable colours where "
        "they work, but modernise layout, spacing, typography and hierarchy."
    )
    return "\n".join(lines)
