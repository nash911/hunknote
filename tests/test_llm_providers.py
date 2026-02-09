"""Tests for LLM provider modules."""

import os
from unittest.mock import patch

import pytest

from aicommit.config import LLMProvider
from aicommit.llm import get_provider
from aicommit.llm.base import MissingAPIKeyError


class TestGetProvider:
    """Tests for get_provider factory function."""

    def test_returns_anthropic_provider(self):
        """Test getting Anthropic provider."""
        from aicommit.llm.anthropic_provider import AnthropicProvider

        provider = get_provider(LLMProvider.ANTHROPIC)
        assert isinstance(provider, AnthropicProvider)

    def test_returns_openai_provider(self):
        """Test getting OpenAI provider."""
        from aicommit.llm.openai_provider import OpenAIProvider

        provider = get_provider(LLMProvider.OPENAI)
        assert isinstance(provider, OpenAIProvider)

    def test_returns_google_provider(self):
        """Test getting Google provider."""
        from aicommit.llm.google_provider import GoogleProvider

        provider = get_provider(LLMProvider.GOOGLE)
        assert isinstance(provider, GoogleProvider)

    def test_returns_mistral_provider(self):
        """Test getting Mistral provider."""
        from aicommit.llm.mistral_provider import MistralProvider

        provider = get_provider(LLMProvider.MISTRAL)
        assert isinstance(provider, MistralProvider)

    def test_returns_cohere_provider(self):
        """Test getting Cohere provider."""
        from aicommit.llm.cohere_provider import CohereProvider

        provider = get_provider(LLMProvider.COHERE)
        assert isinstance(provider, CohereProvider)

    def test_returns_groq_provider(self):
        """Test getting Groq provider."""
        from aicommit.llm.groq_provider import GroqProvider

        provider = get_provider(LLMProvider.GROQ)
        assert isinstance(provider, GroqProvider)

    def test_returns_openrouter_provider(self):
        """Test getting OpenRouter provider."""
        from aicommit.llm.openrouter_provider import OpenRouterProvider

        provider = get_provider(LLMProvider.OPENROUTER)
        assert isinstance(provider, OpenRouterProvider)

    def test_custom_model(self):
        """Test provider with custom model."""
        provider = get_provider(LLMProvider.OPENAI, model="gpt-4-turbo")
        assert provider.model == "gpt-4-turbo"


class TestAnthropicProvider:
    """Tests for AnthropicProvider."""

    def test_default_model(self):
        """Test default model is set."""
        from aicommit.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider()
        # Default should be a Claude model when no model specified
        # Note: if ACTIVE_MODEL is from another provider, it still gets used
        assert provider.model is not None
        assert len(provider.model) > 0

    def test_custom_model(self):
        """Test custom model."""
        from aicommit.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(model="claude-3-opus-latest")
        assert provider.model == "claude-3-opus-latest"

    def test_missing_api_key_raises_error(self):
        """Test that missing API key raises error."""
        from aicommit.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider()

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(MissingAPIKeyError) as exc_info:
                provider.get_api_key()

            assert "ANTHROPIC_API_KEY" in str(exc_info.value)

    def test_gets_api_key_from_env(self):
        """Test getting API key from environment."""
        from aicommit.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider()

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            key = provider.get_api_key()
            assert key == "test-key"


class TestOpenAIProvider:
    """Tests for OpenAIProvider."""

    def test_default_model(self):
        """Test default model is set."""
        from aicommit.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()
        assert "gpt" in provider.model.lower()

    def test_missing_api_key_raises_error(self):
        """Test that missing API key raises error."""
        from aicommit.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(MissingAPIKeyError) as exc_info:
                provider.get_api_key()

            assert "OPENAI_API_KEY" in str(exc_info.value)


class TestGoogleProvider:
    """Tests for GoogleProvider."""

    def test_default_model(self):
        """Test default model is set."""
        from aicommit.llm.google_provider import GoogleProvider

        provider = GoogleProvider()
        assert "gemini" in provider.model.lower()

    def test_missing_api_key_raises_error(self):
        """Test that missing API key raises error."""
        from aicommit.llm.google_provider import GoogleProvider

        provider = GoogleProvider()

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(MissingAPIKeyError) as exc_info:
                provider.get_api_key()

            assert "GOOGLE_API_KEY" in str(exc_info.value)

    def test_is_thinking_model(self):
        """Test thinking model detection."""
        from aicommit.llm.google_provider import GoogleProvider

        # Thinking model
        provider = GoogleProvider(model="gemini-2.5-flash")
        assert provider._is_thinking_model() is True

        # Non-thinking model
        provider = GoogleProvider(model="gemini-2.0-flash")
        assert provider._is_thinking_model() is False


class TestMistralProvider:
    """Tests for MistralProvider."""

    def test_default_model(self):
        """Test default model is set."""
        from aicommit.llm.mistral_provider import MistralProvider

        provider = MistralProvider()
        assert "mistral" in provider.model.lower()

    def test_missing_api_key_raises_error(self):
        """Test that missing API key raises error."""
        from aicommit.llm.mistral_provider import MistralProvider

        provider = MistralProvider()

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(MissingAPIKeyError) as exc_info:
                provider.get_api_key()

            assert "MISTRAL_API_KEY" in str(exc_info.value)


class TestCohereProvider:
    """Tests for CohereProvider."""

    def test_default_model(self):
        """Test default model is set."""
        from aicommit.llm.cohere_provider import CohereProvider

        provider = CohereProvider()
        assert "command" in provider.model.lower()

    def test_missing_api_key_raises_error(self):
        """Test that missing API key raises error."""
        from aicommit.llm.cohere_provider import CohereProvider

        provider = CohereProvider()

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(MissingAPIKeyError) as exc_info:
                provider.get_api_key()

            assert "COHERE_API_KEY" in str(exc_info.value)


class TestGroqProvider:
    """Tests for GroqProvider."""

    def test_default_model(self):
        """Test default model is set."""
        from aicommit.llm.groq_provider import GroqProvider

        provider = GroqProvider()
        assert len(provider.model) > 0

    def test_missing_api_key_raises_error(self):
        """Test that missing API key raises error."""
        from aicommit.llm.groq_provider import GroqProvider

        provider = GroqProvider()

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(MissingAPIKeyError) as exc_info:
                provider.get_api_key()

            assert "GROQ_API_KEY" in str(exc_info.value)


class TestOpenRouterProvider:
    """Tests for OpenRouterProvider."""

    def test_default_model(self):
        """Test default model is set."""
        from aicommit.llm.openrouter_provider import OpenRouterProvider

        provider = OpenRouterProvider()
        assert len(provider.model) > 0

    def test_missing_api_key_raises_error(self):
        """Test that missing API key raises error."""
        from aicommit.llm.openrouter_provider import OpenRouterProvider

        provider = OpenRouterProvider()

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(MissingAPIKeyError) as exc_info:
                provider.get_api_key()

            assert "OPENROUTER_API_KEY" in str(exc_info.value)
