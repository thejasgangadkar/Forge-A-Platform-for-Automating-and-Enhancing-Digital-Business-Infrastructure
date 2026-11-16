"""Verification test for Bug B — Agent grounding enforcement.

Bug B: The agent_runtime system prompt originally just said
"Business context: {context}" without any strict grounding rules. This allowed
the LLM to use pre-trained assumptions (wrong hours, prices, addresses) instead
of relying strictly on the provided business context.

Fix: The system prompt now includes CRITICAL GROUNDING RULES that instruct the
LLM to answer STRICTLY from the Business Context and Relevant business info,
and to never invent or assume details not present in the context.

This test verifies:
  1. The system prompt contains "STRICTLY" grounding instruction
  2. The system prompt contains "Do NOT invent" instruction
  3. The business_context is included in the system message
  4. RAG snippets are appended when available
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.agent_runtime import run_agent


class TestAgentGroundingEnforcement:
    """Verify that the agent runtime enforces strict grounding rules
    so the LLM cannot hallucinate business details."""

    def setup_method(self):
        """Set up common test fixtures."""
        self.agent_config = {
            "system_prompt": "You are a helpful receptionist for Sunrise Bakery.",
        }
        self.business_context = (
            "Sunrise Bakery is open Monday-Friday 7am-3pm. "
            "Located at 123 Main St, Portland OR. "
            "Specialties: sourdough, croissants, cinnamon rolls. "
            "No delivery service available."
        )
        self.user_message = "What are your hours?"

    @patch("services.agent_runtime.vector_store")
    @patch("services.agent_runtime.llm")
    def test_system_prompt_contains_strictly(self, mock_llm, mock_vs):
        """The system prompt must contain 'STRICTLY' to enforce grounding."""
        mock_llm.return_value = "We are open Monday-Friday 7am-3pm."
        mock_vs.query_business_context.return_value = []

        run_agent(self.agent_config, self.business_context, self.user_message)

        # Extract the system message passed to the LLM
        call_args = mock_llm.call_args
        messages = call_args[0][0]  # First positional arg is the messages list
        system_msg = messages[0]

        assert system_msg["role"] == "system"
        assert "STRICTLY" in system_msg["content"], (
            "System prompt must contain 'STRICTLY' to enforce grounding. "
            "Bug B is NOT fixed!"
        )

    @patch("services.agent_runtime.vector_store")
    @patch("services.agent_runtime.llm")
    def test_system_prompt_contains_do_not_invent(self, mock_llm, mock_vs):
        """The system prompt must contain 'Do NOT invent' instruction."""
        mock_llm.return_value = "We are open Monday-Friday 7am-3pm."
        mock_vs.query_business_context.return_value = []

        run_agent(self.agent_config, self.business_context, self.user_message)

        call_args = mock_llm.call_args
        messages = call_args[0][0]
        system_content = messages[0]["content"]

        assert "Do NOT invent" in system_content, (
            "System prompt must contain 'Do NOT invent' to prevent hallucination. "
            "Bug B is NOT fixed!"
        )

    @patch("services.agent_runtime.vector_store")
    @patch("services.agent_runtime.llm")
    def test_business_context_included_in_system_prompt(self, mock_llm, mock_vs):
        """The business_context must appear in the system message sent to LLM."""
        mock_llm.return_value = "We are open Monday-Friday 7am-3pm."
        mock_vs.query_business_context.return_value = []

        run_agent(self.agent_config, self.business_context, self.user_message)

        call_args = mock_llm.call_args
        messages = call_args[0][0]
        system_content = messages[0]["content"]

        # The business_context should be present (possibly truncated)
        assert "Sunrise Bakery" in system_content, (
            "Business context must be included in the system prompt"
        )
        assert "123 Main St" in system_content, (
            "Business context details must be present in the system prompt"
        )

    @patch("services.agent_runtime.vector_store")
    @patch("services.agent_runtime.llm")
    def test_rag_snippets_appended_when_available(self, mock_llm, mock_vs):
        """When RAG returns snippets, they must be appended to the system prompt."""
        mock_llm.return_value = "Our sourdough is $6 per loaf."
        mock_vs.query_business_context.return_value = [
            "Pricing: Sourdough loaf $6, Croissant $3.50, Cinnamon roll $4",
            "We source organic flour from a local mill in Willamette Valley",
        ]

        run_agent(
            self.agent_config,
            self.business_context,
            self.user_message,
            workspace_id="ws-123",
        )

        call_args = mock_llm.call_args
        messages = call_args[0][0]
        system_content = messages[0]["content"]

        # RAG snippets should appear in the system message
        assert "Relevant business info" in system_content, (
            "RAG block header should be present when snippets exist"
        )
        assert "Sourdough loaf $6" in system_content, (
            "RAG snippet content must be appended to the system prompt"
        )
        assert "organic flour" in system_content, (
            "All RAG snippets should be included"
        )

    @patch("services.agent_runtime.vector_store")
    @patch("services.agent_runtime.llm")
    def test_grounding_rules_present_as_block(self, mock_llm, mock_vs):
        """The system prompt should contain the full grounding rules block."""
        mock_llm.return_value = "Let me help you with that."
        mock_vs.query_business_context.return_value = []

        run_agent(self.agent_config, self.business_context, self.user_message)

        call_args = mock_llm.call_args
        messages = call_args[0][0]
        system_content = messages[0]["content"]

        # Check for the CRITICAL GROUNDING RULES header
        assert "CRITICAL GROUNDING RULES" in system_content, (
            "System prompt must include 'CRITICAL GROUNDING RULES' section header"
        )
        # Check that the business context label is present
        assert "Business context:" in system_content, (
            "System prompt must label the business context section"
        )

    @patch("services.agent_runtime.vector_store")
    @patch("services.agent_runtime.llm")
    def test_business_context_truncated_to_limit(self, mock_llm, mock_vs):
        """Business context should be truncated to prevent prompt overflow."""
        mock_llm.return_value = "I can help with that."
        mock_vs.query_business_context.return_value = []

        # Create an excessively long context
        long_context = "A" * 5000

        run_agent(self.agent_config, long_context, self.user_message)

        call_args = mock_llm.call_args
        messages = call_args[0][0]
        system_content = messages[0]["content"]

        # The context should be truncated (code uses [:1500])
        # So 5000 chars of 'A' should be cut down
        a_count = system_content.count("A")
        assert a_count <= 2000, (
            f"Business context should be truncated (found {a_count} 'A's, expected <= 2000). "
            "Prompt overflow protection missing."
        )
