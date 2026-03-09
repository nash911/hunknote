"""Tests for LLM provider modules."""

import pytest

from hunknote.config import LLMProvider
from hunknote.llm import get_provider
from hunknote.llm.litellm_provider import LiteLLMProvider


class TestGetProvider:
    """Tests for get_provider factory function.

    All providers are now routed through the unified LiteLLMProvider.
    """

    def test_returns_anthropic_provider(self):
        """Test getting Anthropic provider returns LiteLLMProvider."""
        provider = get_provider(LLMProvider.ANTHROPIC)
        assert isinstance(provider, LiteLLMProvider)
        assert provider.provider == LLMProvider.ANTHROPIC

    def test_returns_openai_provider(self):
        """Test getting OpenAI provider returns LiteLLMProvider."""
        provider = get_provider(LLMProvider.OPENAI)
        assert isinstance(provider, LiteLLMProvider)
        assert provider.provider == LLMProvider.OPENAI

    def test_returns_google_provider(self):
        """Test getting Google provider returns LiteLLMProvider."""
        provider = get_provider(LLMProvider.GOOGLE)
        assert isinstance(provider, LiteLLMProvider)
        assert provider.provider == LLMProvider.GOOGLE

    def test_returns_mistral_provider(self):
        """Test getting Mistral provider returns LiteLLMProvider."""
        provider = get_provider(LLMProvider.MISTRAL)
        assert isinstance(provider, LiteLLMProvider)
        assert provider.provider == LLMProvider.MISTRAL

    def test_returns_cohere_provider(self):
        """Test getting Cohere provider returns LiteLLMProvider."""
        provider = get_provider(LLMProvider.COHERE)
        assert isinstance(provider, LiteLLMProvider)
        assert provider.provider == LLMProvider.COHERE

    def test_returns_groq_provider(self):
        """Test getting Groq provider returns LiteLLMProvider."""
        provider = get_provider(LLMProvider.GROQ)
        assert isinstance(provider, LiteLLMProvider)
        assert provider.provider == LLMProvider.GROQ

    def test_returns_openrouter_provider(self):
        """Test getting OpenRouter provider returns LiteLLMProvider."""
        provider = get_provider(LLMProvider.OPENROUTER)
        assert isinstance(provider, LiteLLMProvider)
        assert provider.provider == LLMProvider.OPENROUTER

    def test_custom_model(self):
        """Test provider with custom model."""
        provider = get_provider(LLMProvider.OPENAI, model="gpt-4-turbo")
        assert provider.model == "gpt-4-turbo"

    def test_default_style(self):
        """Test provider with default style."""
        provider = get_provider(LLMProvider.GOOGLE)
        assert provider.style == "default"

    def test_custom_style(self):
        """Test provider with custom style."""
        provider = get_provider(LLMProvider.GOOGLE, style="blueprint")
        assert provider.style == "blueprint"

    def test_style_with_model(self):
        """Test provider with both model and style."""
        provider = get_provider(LLMProvider.OPENAI, model="gpt-4o", style="conventional")
        assert provider.model == "gpt-4o"
        assert provider.style == "conventional"

    def test_unsupported_provider_raises_error(self):
        """Test that unsupported provider raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_provider("invalid_provider")
        assert "Unsupported provider" in str(exc_info.value)


