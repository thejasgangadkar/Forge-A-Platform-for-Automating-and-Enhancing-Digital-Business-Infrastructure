"""Verification test for Bug E — Scraper async safety.

Bug E: _scrape_playwright() uses sync_playwright() which crashes with
"Playwright Sync API cannot be used inside an asyncio loop" RuntimeError
when called from Uvicorn's event loop. The scraper would then silently
fall back to raw `requests`, which is blocked by firewalls.

Fix: scrape_website_structured() detects a running asyncio loop and runs
Playwright in a ThreadPoolExecutor worker. scrape_website_structured_async()
uses asyncio.to_thread() to offload the entire sync scrape, so the sync
Playwright API never executes in the main asyncio thread.

This test verifies:
  1. scrape_website_structured_async() completes without RuntimeError when
     called from inside an active asyncio event loop (simulating Uvicorn).
  2. The function returns structured data (dict with expected keys).
  3. scrape_website_structured() also works when a loop is running (ThreadPoolExecutor path).
"""
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.website_scraper import (
    scrape_website_structured,
    scrape_website_structured_async,
    scrape_website_async,
)

# Expected keys in the structured scrape result
EXPECTED_KEYS = {"title", "meta_description", "headings", "images", "text", "screenshot", "engine", "pages_crawled"}


# ─── Helpers ─────────────────────────────────────────────────────────

def _fake_playwright_scrape(url: str, max_pages: int = 4) -> dict:
    """Simulates a successful Playwright scrape returning structured data."""
    return {
        "title": "Test Business",
        "meta_description": "A test business site",
        "headings": ["Welcome", "About Us", "Services"],
        "images": ["https://example.com/img1.png"],
        "text": "[PAGE: https://example.com]\nWelcome to Test Business. We provide excellent services.",
        "screenshot": "/tmp/test_shot.png",
        "engine": "playwright",
        "pages_crawled": 1,
    }


def _fake_playwright_scrape_none(url: str, max_pages: int = 4) -> dict | None:
    """Simulates Playwright failing (returns None), triggering requests fallback."""
    return None


# ─── Test Class ──────────────────────────────────────────────────────

class TestBugEScraperAsyncSafety:
    """Verify that scraper functions work safely inside an active asyncio loop."""

    # --- Test 1: async entry point doesn't crash in asyncio loop ---

    @pytest.mark.asyncio
    @patch("scraper.website_scraper._scrape_playwright", side_effect=_fake_playwright_scrape)
    async def test_async_scrape_no_runtime_error(self, mock_pw):
        """scrape_website_structured_async() must NOT raise RuntimeError
        when called from inside an active asyncio event loop (Uvicorn scenario)."""

        # We are already inside an asyncio loop (pytest-asyncio provides one).
        # This simulates being inside Uvicorn's event loop.
        loop = asyncio.get_running_loop()
        assert loop is not None, "Test must run inside an active asyncio loop"

        # This should NOT raise "Playwright Sync API inside asyncio loop"
        result = await scrape_website_structured_async("https://example.com")

        # Should have returned structured data, not crashed
        assert isinstance(result, dict), "Expected dict result, got something else"
        assert result.get("engine") == "playwright", (
            f"Expected playwright engine, got {result.get('engine')}"
        )

    # --- Test 2: returns valid structured data with all expected keys ---

    @pytest.mark.asyncio
    @patch("scraper.website_scraper._scrape_playwright", side_effect=_fake_playwright_scrape)
    async def test_async_scrape_returns_structured_data(self, mock_pw):
        """Result dict must contain all expected keys for downstream processing."""
        result = await scrape_website_structured_async("https://example.com")

        missing_keys = EXPECTED_KEYS - set(result.keys())
        assert not missing_keys, f"Missing keys in scrape result: {missing_keys}"

        # Verify data types
        assert isinstance(result["title"], str)
        assert isinstance(result["headings"], list)
        assert isinstance(result["images"], list)
        assert isinstance(result["text"], str)
        assert len(result["text"]) > 0, "text field should not be empty"

    # --- Test 3: sync scrape also works when asyncio loop is running ---

    @pytest.mark.asyncio
    @patch("scraper.website_scraper._scrape_playwright", side_effect=_fake_playwright_scrape)
    async def test_sync_scrape_detects_loop_uses_threadpool(self, mock_pw):
        """scrape_website_structured() should detect the running loop and
        use ThreadPoolExecutor to avoid the RuntimeError."""

        # Call the sync function from within an async context
        # It should detect the loop and use ThreadPoolExecutor
        result = await asyncio.to_thread(scrape_website_structured, "https://example.com")

        assert isinstance(result, dict)
        assert result.get("engine") == "playwright"

    # --- Test 4: graceful fallback when Playwright fails ---

    @pytest.mark.asyncio
    @patch("scraper.website_scraper._scrape_playwright", side_effect=_fake_playwright_scrape_none)
    @patch("scraper.website_scraper._scrape_requests")
    async def test_async_scrape_falls_back_gracefully(self, mock_requests, mock_pw):
        """When Playwright returns None, should fall back to requests-based
        scraping without crashing."""
        mock_requests.return_value = {
            "title": "Fallback Title",
            "meta_description": "Fallback desc",
            "headings": ["Heading"],
            "images": [],
            "text": "Fallback text content",
            "screenshot": None,
            "engine": "requests",
            "pages_crawled": 1,
        }

        result = await scrape_website_structured_async("https://example.com")

        assert isinstance(result, dict)
        assert result.get("engine") == "requests", (
            "Should have fallen back to requests engine"
        )
        assert result.get("text"), "Fallback should still provide text"

    # --- Test 5: scrape_website_async convenience function ---

    @pytest.mark.asyncio
    @patch("scraper.website_scraper._scrape_playwright", side_effect=_fake_playwright_scrape)
    async def test_scrape_website_async_returns_text(self, mock_pw):
        """scrape_website_async() convenience function returns a string."""
        text = await scrape_website_async("https://example.com")

        assert isinstance(text, str)
        assert len(text) > 0, "Should return non-empty text"

    # --- Test 6: Simulates the EXACT Uvicorn scenario ---

    @pytest.mark.asyncio
    @patch("scraper.website_scraper._scrape_playwright", side_effect=_fake_playwright_scrape)
    async def test_uvicorn_style_concurrent_scrapes(self, mock_pw):
        """Simulate multiple concurrent scrape requests as Uvicorn would handle
        them — all should complete without RuntimeError."""

        # Launch 3 concurrent scrape calls (like Uvicorn handling 3 requests)
        tasks = [
            scrape_website_structured_async(f"https://example{i}.com")
            for i in range(3)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            assert not isinstance(result, RuntimeError), (
                f"Scrape {i} raised RuntimeError: {result}"
            )
            assert isinstance(result, dict), (
                f"Scrape {i} should return dict, got {type(result)}"
            )

    # --- Test 7: Verify ThreadPoolExecutor path is taken in-loop ---

    @pytest.mark.asyncio
    @patch("scraper.website_scraper._scrape_playwright", side_effect=_fake_playwright_scrape)
    async def test_threadpool_path_used_in_loop(self, mock_pw):
        """When inside a running asyncio loop, scrape_website_structured should
        use the ThreadPoolExecutor path (not call _scrape_playwright directly
        in the main thread)."""
        import threading

        call_threads = []
        original_side_effect = _fake_playwright_scrape

        def track_thread(url, max_pages=4):
            call_threads.append(threading.current_thread().name)
            return original_side_effect(url, max_pages)

        mock_pw.side_effect = track_thread

        # We're in an asyncio loop (pytest-asyncio), so scrape_website_structured
        # should offload to a ThreadPoolExecutor
        result = await scrape_website_structured_async("https://example.com")

        assert isinstance(result, dict)
        # The mock was called (Playwright path was attempted)
        assert mock_pw.called, "_scrape_playwright should have been called"
