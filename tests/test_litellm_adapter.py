"""Tests for the LiteLLM adapter module."""

import os
from unittest.mock import MagicMock, patch

import pytest

from hunknote.compose.litellm_adapter import (
    calculate_token_budget,
    parse_tool_arguments,
    setup_litellm_api_keys,
    to_litellm_model,
)


class TestToLitellmModel:
    """Tests for the model name mapping function."""

    def test_google_model(self):
        assert to_litellm_model("google", "gemini-2.5-flash") == "gemini/gemini-2.5-flash"

    def test_google_model_3(self):
        assert to_litellm_model("google", "gemini-3-flash-preview") == "gemini/gemini-3-flash-preview"

    def test_anthropic_model(self):
        assert to_litellm_model("anthropic", "claude-sonnet-4-20250514") == "anthropic/claude-sonnet-4-20250514"

    def test_openai_model_no_prefix(self):
        """OpenAI models don't need a prefix in LiteLLM."""
        assert to_litellm_model("openai", "gpt-4o") == "gpt-4o"

    def test_groq_model(self):
        assert to_litellm_model("groq", "llama-3.3-70b-versatile") == "groq/llama-3.3-70b-versatile"

    def test_mistral_model(self):
        assert to_litellm_model("mistral", "mistral-large-latest") == "mistral/mistral-large-latest"

    def test_cohere_model(self):
        assert to_litellm_model("cohere", "command-r-plus") == "cohere_chat/command-r-plus"

    def test_openrouter_model(self):
        assert to_litellm_model("openrouter", "anthropic/claude-sonnet-4") == "openrouter/anthropic/claude-sonnet-4"

    def test_case_insensitive(self):
        assert to_litellm_model("Google", "gemini-2.0-flash") == "gemini/gemini-2.0-flash"

    def test_unknown_provider(self):
        """Unknown providers return the model name as-is."""
        assert to_litellm_model("some_new_provider", "my-model") == "my-model"


class TestSetupLitellmApiKeys:
    """Tests for API key bridging."""

    @patch.dict(os.environ, {}, clear=False)
    @patch("hunknote.global_config.get_credential", return_value="test-key-123")
    def test_sets_env_var_from_keychain(self, mock_cred):
        """When keychain has a key and env var is not set, inject it."""
        # Remove any existing key
        os.environ.pop("GOOGLE_API_KEY", None)
        setup_litellm_api_keys("google")
        assert os.environ.get("GOOGLE_API_KEY") == "test-key-123"
        # Clean up
        os.environ.pop("GOOGLE_API_KEY", None)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "existing-key"}, clear=False)
    def test_preserves_existing_env_var(self):
        """When env var already set, don't overwrite it."""
        setup_litellm_api_keys("google")
        assert os.environ.get("GOOGLE_API_KEY") == "existing-key"

    def test_handles_missing_global_config(self):
        """Gracefully handles missing global_config module."""
        with patch("hunknote.global_config.get_credential", side_effect=Exception("no key")):
            os.environ.pop("GOOGLE_API_KEY", None)
            # Should not raise
            setup_litellm_api_keys("google")


class TestCalculateTokenBudget:
    """Tests for token budget calculation."""

    def test_small_diff(self):
        budget = calculate_token_budget(5, 50)
        assert budget >= 16384  # At least base budget

    def test_large_diff(self):
        budget = calculate_token_budget(100, 5000)
        assert budget > 16384
        assert budget <= 131072  # Absolute cap

    def test_very_large_diff_capped(self):
        budget = calculate_token_budget(1000, 100000)
        assert budget == 131072  # Should hit cap

    def test_zero_hunks(self):
        budget = calculate_token_budget(0, 0)
        assert budget == 16384  # Returns base budget


class TestParseToolArguments:
    """Tests for safe JSON parsing of tool arguments."""

    def test_valid_json(self):
        assert parse_tool_arguments('{"foo": "bar"}') == {"foo": "bar"}

    def test_empty_string(self):
        assert parse_tool_arguments("") == {}

    def test_none(self):
        assert parse_tool_arguments(None) == {}

    def test_invalid_json(self):
        assert parse_tool_arguments("not json") == {}

    def test_nested_json(self):
        result = parse_tool_arguments('{"hunk_ids": ["H1", "H2"]}')
        assert result == {"hunk_ids": ["H1", "H2"]}

