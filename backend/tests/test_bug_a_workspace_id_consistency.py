"""Verification test for Bug A — Workspace ID consistency.

Bug A: orchestrate_generation() used to create its own UUID for the asset folder,
while create_workspace() created a DIFFERENT UUID as the DB row ID. The widget in
the generated HTML would point to the folder UUID (not the DB UUID), causing 404
on agent chat.

Fix: /api/generate now creates the workspace DB row FIRST, then passes that real
ID to orchestrate_generation() so it uses the DB ID as the folder name.

This test verifies:
  DB row ID == asset directory name == widget endpoint UUID in generated HTML
"""
import os
import re
import uuid
import shutil
from unittest.mock import patch, MagicMock

import pytest

# We need to be able to import from the backend package
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.generation_service import (
    orchestrate_generation, WORKSPACES_DIR, inject_agent_widget,
)


# ─── Test 1: orchestrate_generation uses provided workspace_id ───────
class TestWorkspaceIdConsistency:
    """Verify that a pre-created workspace ID flows through to the asset
    directory and the widget HTML endpoint."""

    def setup_method(self):
        """Create a known workspace ID for each test."""
        self.ws_id = str(uuid.uuid4())
        self.ws_dir = os.path.join(WORKSPACES_DIR, self.ws_id)

    def teardown_method(self):
        """Clean up generated files."""
        if os.path.exists(self.ws_dir):
            shutil.rmtree(self.ws_dir, ignore_errors=True)

    @patch("services.generation_service.generate_website")
    @patch("services.generation_service.generate_agents")
    def test_orchestrate_uses_provided_workspace_id(self, mock_agents, mock_website):
        """When workspace_id is passed, orchestrate_generation uses it as the
        folder name — NOT a new UUID."""
        mock_website.return_value = {"keywords": ["test"], "images": []}
        mock_agents.return_value = [{"id": "a1", "name": "Test Agent", "type": "support"}]

        returned_id, ctx, meta = orchestrate_generation(
            "A test bakery business",
            agent_types=["support"],
            build_website=True,
            workspace_id=self.ws_id,
        )

        # Assert: returned ID matches the one we passed in
        assert returned_id == self.ws_id, (
            f"orchestrate_generation returned {returned_id}, expected {self.ws_id}"
        )

        # Assert: asset directory is named after the DB workspace ID
        assert os.path.isdir(self.ws_dir), (
            f"Expected directory {self.ws_dir} to exist"
        )
        website_dir = os.path.join(self.ws_dir, "website")
        agents_dir = os.path.join(self.ws_dir, "agents")
        assert os.path.isdir(website_dir), "website subdir should exist"
        assert os.path.isdir(agents_dir), "agents subdir should exist"

    @patch("services.generation_service.generate_website")
    @patch("services.generation_service.generate_agents")
    def test_orchestrate_without_workspace_id_creates_new_uuid(self, mock_agents, mock_website):
        """When no workspace_id is passed, a new UUID is generated (standalone mode)."""
        mock_website.return_value = {"keywords": ["test"], "images": []}
        mock_agents.return_value = [{"id": "a1", "name": "Agent", "type": "support"}]

        returned_id, ctx, meta = orchestrate_generation(
            "A test business",
            agent_types=["support"],
            build_website=True,
            workspace_id=None,
        )

        # Should be a valid UUID (not None, not empty)
        assert returned_id is not None
        uuid.UUID(returned_id)  # Raises ValueError if not a valid UUID

        # Clean up
        gen_dir = os.path.join(WORKSPACES_DIR, returned_id)
        if os.path.exists(gen_dir):
            shutil.rmtree(gen_dir, ignore_errors=True)

    def test_widget_html_uses_workspace_id(self):
        """The injected widget HTML must point to the SAME workspace ID
        that the folder is named after (the DB row ID)."""
        web_dir = os.path.join(self.ws_dir, "website")
        os.makedirs(web_dir, exist_ok=True)

        # Write a minimal HTML file with the widget marker
        index_path = os.path.join(web_dir, "index.html")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(
                '<!doctype html><html><head></head><body>'
                '<!--FORGE_AGENT_WIDGET--></body></html>'
            )

        # Inject the widget
        inject_agent_widget(self.ws_id, web_dir)

        # Read back and verify the workspace ID appears in the widget
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        # The widget JS should reference our workspace ID for the API call
        assert self.ws_id in html, (
            f"Widget HTML does not contain workspace ID {self.ws_id}"
        )

        # Verify the API endpoint URL uses our workspace ID
        # The widget calls: API+'/api/workspaces/'+WS+'/agent/chat'
        # where WS is set to the workspace_id passed to inject_agent_widget
        assert f'WS="{self.ws_id}"' in html, (
            f"Widget JS variable WS should be set to {self.ws_id}"
        )

    @patch("services.generation_service.generate_website")
    @patch("services.generation_service.generate_agents")
    def test_full_flow_id_consistency(self, mock_agents, mock_website):
        """End-to-end: simulate what /api/generate does — create ws ID first,
        then pass it to orchestrate_generation. All three IDs must match:
        DB row ID == asset directory name == widget endpoint UUID."""

        # Simulate what main.py does: create workspace first, get its ID
        db_row_id = self.ws_id  # In production this comes from Supabase

        # Mock website generation to produce a file with the widget marker
        def fake_generate_website(context, output_dir):
            html = (
                '<!doctype html><html><head></head><body>'
                '<h1>Test</h1><!--FORGE_AGENT_WIDGET--></body></html>'
            )
            with open(os.path.join(output_dir, "index.html"), "w") as f:
                f.write(html)
            return {"keywords": ["bakery"], "images": []}

        mock_website.side_effect = fake_generate_website
        mock_agents.return_value = [{"id": "ag1", "name": "Support", "type": "support"}]

        # Call orchestrate_generation with the DB-created ID (as main.py does)
        returned_id, ctx, meta = orchestrate_generation(
            "A cozy bakery in downtown Seattle",
            agent_types=["support"],
            build_website=True,
            workspace_id=db_row_id,
        )

        # CHECK 1: Returned ID == DB row ID
        assert returned_id == db_row_id

        # CHECK 2: Asset directory name == DB row ID
        asset_dir = os.path.join(WORKSPACES_DIR, db_row_id)
        assert os.path.isdir(asset_dir), f"Asset dir should be named {db_row_id}"

        # CHECK 3: Widget endpoint UUID in generated HTML == DB row ID
        index_path = os.path.join(asset_dir, "website", "index.html")
        assert os.path.exists(index_path), "index.html should exist"
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Extract workspace ID from widget JS: WS="<uuid>"
        ws_match = re.search(r'WS="([^"]+)"', html)
        assert ws_match is not None, "Widget JS should contain WS variable"
        widget_ws_id = ws_match.group(1)

        assert widget_ws_id == db_row_id, (
            f"Widget endpoint UUID ({widget_ws_id}) != DB row ID ({db_row_id}). "
            "Bug A is NOT fixed!"
        )

        # All three match
        assert returned_id == db_row_id == widget_ws_id, (
            f"ID mismatch! returned={returned_id}, dir={db_row_id}, widget={widget_ws_id}"
        )
