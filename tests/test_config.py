"""Tests for aicommit.config module."""

import pytest

from aicommit.config import (
    ACTIVE_MODEL,
    ACTIVE_PROVIDER,
    API_KEY_ENV_VARS,
    AVAILABLE_MODELS,
    LLMProvider,
    MAX_TOKENS,
    TEMPERATURE,
    get_api_key_env_var,
)


class TestLLMProviderEnum:
    """Tests for LLMProvider enum."""

    def test_has_anthropic(self):
        """Test that ANTHROPIC provider exists."""
        assert LLMProvider.ANTHROPIC.value == "anthropic"

    def test_has_openai(self):
        """Test that OPENAI provider exists."""
        assert LLMProvider.OPENAI.value == "openai"

    def test_has_google(self):
        """Test that GOOGLE provider exists."""
        assert LLMProvider.GOOGLE.value == "google"

    def test_has_mistral(self):
        """Test that MISTRAL provider exists."""
        assert LLMProvider.MISTRAL.value == "mistral"

    def test_has_cohere(self):
        """Test that COHERE provider exists."""
        assert LLMProvider.COHERE.value == "cohere"

    def test_has_groq(self):
        """Test that GROQ provider exists."""
        assert LLMProvider.GROQ.value == "groq"

    def test_has_openrouter(self):
        """Test that OPENROUTER provider exists."""
        assert LLMProvider.OPENROUTER.value == "openrouter"


class TestActiveConfig:
    """Tests for active configuration settings."""

    def test_active_provider_is_valid(self):
        """Test that ACTIVE_PROVIDER is a valid LLMProvider."""
        assert isinstance(ACTIVE_PROVIDER, LLMProvider)

    def test_active_model_is_string(self):
        """Test that ACTIVE_MODEL is a string."""
        assert isinstance(ACTIVE_MODEL, str)
        assert len(ACTIVE_MODEL) > 0


class TestProviderSettings:
    """Tests for provider settings."""

    def test_max_tokens_positive(self):
        """Test that MAX_TOKENS is positive."""
        assert MAX_TOKENS > 0

    def test_max_tokens_reasonable(self):
        """Test that MAX_TOKENS is reasonable."""
        # Should be between 500 and 10000
        assert 500 <= MAX_TOKENS <= 10000

    def test_temperature_in_range(self):
        """Test that TEMPERATURE is in valid range."""
        assert 0.0 <= TEMPERATURE <= 2.0


class TestAvailableModels:
    """Tests for AVAILABLE_MODELS dictionary."""

    def test_has_all_providers(self):
        """Test that all providers have models defined."""
        for provider in LLMProvider:
            assert provider in AVAILABLE_MODELS
            assert len(AVAILABLE_MODELS[provider]) > 0

    def test_anthropic_models(self):
        """Test Anthropic models."""
        models = AVAILABLE_MODELS[LLMProvider.ANTHROPIC]
        assert any("claude" in m.lower() for m in models)

    def test_openai_models(self):
        """Test OpenAI models."""
        models = AVAILABLE_MODELS[LLMProvider.OPENAI]
        assert any("gpt" in m.lower() for m in models)

    def test_google_models(self):
        """Test Google models."""
        models = AVAILABLE_MODELS[LLMProvider.GOOGLE]
        assert any("gemini" in m.lower() for m in models)

    def test_openrouter_models(self):
        """Test OpenRouter models have provider prefix."""
        models = AVAILABLE_MODELS[LLMProvider.OPENROUTER]
        # OpenRouter models should have provider/model format
        assert any("/" in m for m in models)


class TestAPIKeyEnvVars:
    """Tests for API_KEY_ENV_VARS dictionary."""

    def test_has_all_providers(self):
        """Test that all providers have env var defined."""
        for provider in LLMProvider:
            assert provider in API_KEY_ENV_VARS
            assert len(API_KEY_ENV_VARS[provider]) > 0

    def test_anthropic_key_name(self):
        """Test Anthropic API key env var name."""
        assert API_KEY_ENV_VARS[LLMProvider.ANTHROPIC] == "ANTHROPIC_API_KEY"

    def test_openai_key_name(self):
        """Test OpenAI API key env var name."""
        assert API_KEY_ENV_VARS[LLMProvider.OPENAI] == "OPENAI_API_KEY"

    def test_google_key_name(self):
        """Test Google API key env var name."""
        assert API_KEY_ENV_VARS[LLMProvider.GOOGLE] == "GOOGLE_API_KEY"

    def test_all_keys_end_with_key(self):
        """Test that all env var names end with _KEY or _API_KEY."""
        for var in API_KEY_ENV_VARS.values():
            assert var.endswith("_KEY") or var.endswith("_API_KEY")


class TestGetApiKeyEnvVar:
    """Tests for get_api_key_env_var function."""

    def test_returns_correct_var(self):
        """Test that correct env var is returned."""
        assert get_api_key_env_var(LLMProvider.ANTHROPIC) == "ANTHROPIC_API_KEY"
        assert get_api_key_env_var(LLMProvider.OPENAI) == "OPENAI_API_KEY"
        assert get_api_key_env_var(LLMProvider.GOOGLE) == "GOOGLE_API_KEY"

    def test_all_providers(self):
        """Test all providers return valid env var."""
        for provider in LLMProvider:
            var = get_api_key_env_var(provider)
            assert isinstance(var, str)
            assert len(var) > 0
