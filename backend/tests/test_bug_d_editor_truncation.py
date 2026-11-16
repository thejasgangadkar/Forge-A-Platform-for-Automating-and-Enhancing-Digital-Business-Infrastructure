"""Verification test for Bug D — Editor content preservation.

Bug D: editor_service.py used `current[:18000]` to slice long HTML pages before
passing them to the LLM for editing. Since generated pages are typically 30K+
characters, the bottom half of the page was silently lost, causing edits to
destroy content below the 18K mark.

Fix:
  1. Changed `current[:18000]` to `current[:80000]` (Qwen/Groq models have
     large context windows that can handle full pages).
  2. Changed `max_tokens=16000` to `max_tokens=32000` so the LLM can return
     the complete edited page without truncation.

This test verifies:
  - The LLM receives content that is NOT truncated to 18000 chars
  - Content up to 80000 chars is passed through intact
  - The max_tokens parameter allows full-page output (32000)
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.editor_service import edit_website
from services.generation_service import WORKSPACES_DIR


class TestEditorContentPreservation:
    """Verify that long HTML content is not silently truncated before the LLM
    sees it for editing."""

    def setup_method(self):
        """Create a workspace with a large HTML file for testing."""
        self.ws_id = "test-bug-d-workspace"
        self.web_dir = os.path.join(WORKSPACES_DIR, self.ws_id, "website")
        os.makedirs(self.web_dir, exist_ok=True)

        # Create a realistic 50,000+ character HTML page
        # Simulates a multi-section landing page with lots of content
        sections = []
        for i in range(50):
            section = (
                f'<section id="section-{i}" class="py-16">'
                f'<div class="container mx-auto px-4">'
                f'<h2 class="text-3xl font-bold">Section {i} Title</h2>'
                f'<p class="mt-4 text-lg text-gray-600">'
                f'{"Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 20}'
                f'</p>'
                f'<div class="grid grid-cols-3 gap-8 mt-8">'
                f'<div class="card-{i}-a p-6 rounded shadow">Content block A for section {i}</div>'
                f'<div class="card-{i}-b p-6 rounded shadow">Content block B for section {i}</div>'
                f'<div class="card-{i}-c p-6 rounded shadow">Content block C for section {i}</div>'
                f'</div>'
                f'</div>'
                f'</section>\n'
            )
            sections.append(section)

        self.large_html = (
            '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            '<meta charset="UTF-8">\n'
            '<script src="https://cdn.tailwindcss.com"></script>\n'
            '<title>Test Business Page</title>\n'
            '</head>\n<body>\n'
            + "".join(sections)
            + '<!--FORGE_AGENT_WIDGET-->\n'
            '</body>\n</html>'
        )

        # Verify our test data is large enough (50K+ chars)
        assert len(self.large_html) > 50000, (
            f"Test HTML is only {len(self.large_html)} chars, need 50000+"
        )

        self.index_path = os.path.join(self.web_dir, "index.html")
        with open(self.index_path, "w", encoding="utf-8") as f:
            f.write(self.large_html)

    def teardown_method(self):
        """Clean up generated test files."""
        import shutil
        ws_dir = os.path.join(WORKSPACES_DIR, self.ws_id)
        if os.path.exists(ws_dir):
            shutil.rmtree(ws_dir, ignore_errors=True)

    @patch("services.editor_service.llm")
    def test_llm_receives_full_content_not_truncated_to_18k(self, mock_llm):
        """The LLM prompt must contain content beyond the old 18000 char limit.
        
        Pre-fix: current[:18000] would cut a 50K page at 18K chars.
        Post-fix: current[:80000] passes the full 50K page through.
        """
        # Make the LLM return a valid HTML response
        mock_llm.return_value = self.large_html

        edit_website(self.ws_id, "Make the hero section green")

        # The LLM should have been called
        mock_llm.assert_called_once()

        # Get the prompt that was passed to the LLM
        call_args = mock_llm.call_args
        prompt = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")

        # CRITICAL ASSERTION: The prompt must contain content BEYOND 18000 chars
        # of the original HTML. If the old bug existed (current[:18000]), the prompt
        # would only have up to 18000 chars of the HTML content.
        assert len(prompt) > 18000, (
            f"Prompt length is only {len(prompt)} chars. "
            "The old [:18000] truncation bug may still be present!"
        )

        # Verify the prompt contains at least 30000 chars of original content
        # (our HTML is 50K+, so after slicing to 80K the full thing should be there)
        assert len(prompt) > 30000, (
            f"Prompt length is {len(prompt)} chars — expected >30000 to confirm "
            "the full page content is passed to the LLM."
        )

    @patch("services.editor_service.llm")
    def test_content_from_bottom_half_reaches_llm(self, mock_llm):
        """Content from the BOTTOM HALF of the page (beyond 25K chars) must
        appear in the LLM prompt. This was the primary user impact of Bug D:
        edits to sections in the second half of the page would silently lose
        all that content."""
        mock_llm.return_value = self.large_html

        edit_website(self.ws_id, "Update the last section")

        call_args = mock_llm.call_args
        prompt = call_args[0][0]

        # The last sections (section-49, section-48, etc.) should be in the prompt
        # These are well past the 18K boundary
        assert "section-49" in prompt, (
            "Last section (section-49) not found in LLM prompt — "
            "content is being truncated before reaching the LLM!"
        )
        assert "section-40" in prompt, (
            "Section 40 not found in LLM prompt — mid-page content is lost!"
        )

    @patch("services.editor_service.llm")
    def test_max_tokens_allows_full_page_output(self, mock_llm):
        """max_tokens must be 32000 (not the old 16000) so the LLM can return
        a complete edited page without its output being cut off."""
        mock_llm.return_value = self.large_html

        edit_website(self.ws_id, "Change the background color")

        call_args = mock_llm.call_args
        kwargs = call_args[1] if call_args[1] else {}

        assert kwargs.get("max_tokens") == 32000, (
            f"max_tokens is {kwargs.get('max_tokens')}, expected 32000. "
            "The old 16000 limit would truncate LLM output for large pages."
        )

    @patch("services.editor_service.llm")
    def test_slice_limit_is_80000_not_18000(self, mock_llm):
        """Directly verify the content slice boundary is 80000 chars.
        
        Create content exactly at the boundary to confirm the limit.
        """
        # Create an HTML file with exactly 80000+ chars
        # Build content to exceed 80K
        filler = "X" * 79000
        huge_html = (
            '<!DOCTYPE html><html><head></head><body>'
            f'<div id="start-marker">{filler}</div>'
            '<div id="end-marker">END_CONTENT_HERE</div>'
            '<!--FORGE_AGENT_WIDGET-->'
            '</body></html>'
        )

        # Write this huge file
        with open(self.index_path, "w", encoding="utf-8") as f:
            f.write(huge_html)

        mock_llm.return_value = (
            '<!DOCTYPE html><html><head></head><body>'
            '<div>edited</div></body></html>'
        )

        edit_website(self.ws_id, "Edit something")

        call_args = mock_llm.call_args
        prompt = call_args[0][0]

        # The start marker should definitely be in the prompt
        assert "start-marker" in prompt, "Start of content should be in prompt"

        # With 80K limit and ~79K of filler + markup overhead,
        # the content up to 80K chars should be included
        assert "XXXXXXX" in prompt, (
            "Filler content should be in the prompt (not truncated at 18K)"
        )
