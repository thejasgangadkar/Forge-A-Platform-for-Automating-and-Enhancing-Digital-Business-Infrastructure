"""Task 4.1 — Verify NVIDIA NIM client configuration in llm_service.py.

Tests:
1. _client("nvidia") returns an OpenAI client with correct base_url and API key.
2. BUILD_NVIDIA_MODEL env var controls model selection when BUILD_PROVIDER=nvidia.
3. The build role uses nvidia provider/model when BUILD_PROVIDER=nvidia.
4. Fallback chain triggers for nvidia → groq on error codes 401/402/403/404/410.
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# Ensure the backend root is on sys.path so imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestNvidiaClientConfiguration:
    """Verify _client('nvidia') returns a properly configured OpenAI client."""

    def setup_method(self):
        """Clear cached clients before each test."""
        from services import llm_service
        llm_service._clients.clear()

    def test_nvidia_client_has_correct_base_url(self):
        """_client('nvidia') should use https://integrate.api.nvidia.com/v1."""
        from services.llm_service import _client, NVIDIA_BASE

        client = _client("nvidia")
        assert client.base_url is not None
        # OpenAI client stores base_url as an httpx URL; compare string representation
        base_url_str = str(client.base_url).rstrip("/")
        assert base_url_str == NVIDIA_BASE or base_url_str == NVIDIA_BASE + "/"

    def test_nvidia_client_uses_nvidia_api_key(self):
        """_client('nvidia') should use the NVIDIA_API_KEY from environment."""
        from services.llm_service import _client, NVIDIA_API_KEY

        client = _client("nvidia")
        assert client.api_key == NVIDIA_API_KEY

    def test_nvidia_client_is_cached(self):
        """Subsequent calls to _client('nvidia') should return the same instance."""
        from services.llm_service import _client

        c1 = _client("nvidia")
        c2 = _client("nvidia")
        assert c1 is c2

    def test_unknown_provider_raises_value_error(self):
        """_client() should raise ValueError for unknown providers."""
        from services.llm_service import _client

        with pytest.raises(ValueError, match="Unknown provider"):
            _client("nonexistent_provider")


class TestBuildNvidiaModelRouting:
    """Verify BUILD_NVIDIA_MODEL env var controls model when BUILD_PROVIDER=nvidia."""

    def test_build_nvidia_model_env_var_loaded(self):
        """BUILD_NVIDIA_MODEL should be loaded from environment."""
        from services.llm_service import BUILD_NVIDIA_MODEL
        # Should match the .env value or the default
        assert BUILD_NVIDIA_MODEL == os.getenv(
            "BUILD_NVIDIA_MODEL", "qwen/qwen3-coder-480b-a35b-instruct"
        )

    @patch("services.llm_service._complete")
    @patch("services.llm_service.BUILD_PROVIDER", "nvidia")
    def test_build_role_uses_nvidia_model_when_provider_is_nvidia(self, mock_complete):
        """When BUILD_PROVIDER=nvidia, llm(role='build') should use BUILD_NVIDIA_MODEL."""
        mock_complete.return_value = "generated code"

        from services.llm_service import llm, BUILD_NVIDIA_MODEL

        result = llm("write hello world", role="build")

        # Verify _complete was called with nvidia provider and the nvidia model
        mock_complete.assert_called()
        call_args = mock_complete.call_args
        provider_arg = call_args[0][0]  # first positional arg = provider
        model_arg = call_args[0][1]     # second positional arg = model

        assert provider_arg == "nvidia"
        assert model_arg == BUILD_NVIDIA_MODEL
        assert result == "generated code"

    @patch("services.llm_service._complete")
    @patch("services.llm_service.BUILD_PROVIDER", "groq")
    def test_build_role_uses_build_model_when_provider_is_groq(self, mock_complete):
        """When BUILD_PROVIDER=groq, llm(role='build') should use BUILD_MODEL (not nvidia model)."""
        mock_complete.return_value = "generated code"

        from services.llm_service import llm, BUILD_MODEL

        result = llm("write hello world", role="build")

        call_args = mock_complete.call_args
        provider_arg = call_args[0][0]
        model_arg = call_args[0][1]

        assert provider_arg == "groq"
        assert model_arg == BUILD_MODEL


class TestNvidiaFallbackChain:
    """Verify fallback from nvidia → groq on auth/availability errors."""

    def setup_method(self):
        from services import llm_service
        llm_service._clients.clear()

    @patch("services.llm_service._complete")
    @patch("services.llm_service.BUILD_PROVIDER", "nvidia")
    def test_fallback_to_groq_on_401(self, mock_complete):
        """401 Unauthorized from nvidia should fallback to groq."""
        mock_complete.side_effect = [
            Exception("Error code: 401 - Unauthorized"),
            "fallback response",
        ]

        from services.llm_service import llm

        result = llm("test", role="build", max_retries=3)
        assert result == "fallback response"
        # Second call should use groq
        second_call = mock_complete.call_args_list[1]
        assert second_call[0][0] == "groq"

    @patch("services.llm_service._complete")
    @patch("services.llm_service.BUILD_PROVIDER", "nvidia")
    def test_fallback_to_groq_on_402(self, mock_complete):
        """402 Payment Required from nvidia should fallback to groq."""
        mock_complete.side_effect = [
            Exception("Error code: 402 - insufficient credits"),
            "fallback response",
        ]

        from services.llm_service import llm

        result = llm("test", role="build", max_retries=3)
        assert result == "fallback response"
        second_call = mock_complete.call_args_list[1]
        assert second_call[0][0] == "groq"

    @patch("services.llm_service._complete")
    @patch("services.llm_service.BUILD_PROVIDER", "nvidia")
    def test_fallback_to_groq_on_404(self, mock_complete):
        """404 Not Found from nvidia should fallback to groq."""
        mock_complete.side_effect = [
            Exception("Error code: 404 - model not found"),
            "fallback response",
        ]

        from services.llm_service import llm

        result = llm("test", role="build", max_retries=3)
        assert result == "fallback response"
        second_call = mock_complete.call_args_list[1]
        assert second_call[0][0] == "groq"

    @patch("services.llm_service._complete")
    @patch("services.llm_service.BUILD_PROVIDER", "nvidia")
    def test_fallback_to_groq_on_410(self, mock_complete):
        """410 Gone (end of life) from nvidia should fallback to groq."""
        mock_complete.side_effect = [
            Exception("Error code: 410 - gone / end of life"),
            "fallback response",
        ]

        from services.llm_service import llm

        result = llm("test", role="build", max_retries=3)
        assert result == "fallback response"
        second_call = mock_complete.call_args_list[1]
        assert second_call[0][0] == "groq"

    @patch("services.llm_service._complete")
    @patch("services.llm_service.BUILD_PROVIDER", "nvidia")
    def test_fallback_to_groq_on_403(self, mock_complete):
        """403 Forbidden from nvidia should fallback to groq."""
        mock_complete.side_effect = [
            Exception("Error code: 403 - unauthorized access"),
            "fallback response",
        ]

        from services.llm_service import llm

        result = llm("test", role="build", max_retries=3)
        assert result == "fallback response"
        second_call = mock_complete.call_args_list[1]
        assert second_call[0][0] == "groq"
