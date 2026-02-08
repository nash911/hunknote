"""LLM provider module for aicommit.

This module provides a unified interface to multiple LLM providers.
The active provider is configured in aicommit/config.py.
"""

from dotenv import load_dotenv

from aicommit.config import ACTIVE_MODEL, ACTIVE_PROVIDER, LLMProvider
from aicommit.llm.base import (
    BaseLLMProvider,
    JSONParseError,
    LLMError,
    LLMResult,
    MissingAPIKeyError,
)

# Load environment variables from .env file
load_dotenv()

def get_provider(
    provider: LLMProvider | None = None, model: str | None = None
) -> BaseLLMProvider:
    """Get an LLM provider instance.

    Args:
        provider: The provider to use. Defaults to ACTIVE_PROVIDER from config.
        model: The model to use. Defaults to ACTIVE_MODEL from config.

    Returns:
        An instance of the appropriate LLM provider.

    Raises:
        ValueError: If the provider is not supported.
    """
    provider = provider or ACTIVE_PROVIDER
    model = model or ACTIVE_MODEL

    if provider == LLMProvider.ANTHROPIC:
        from aicommit.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=model)

    elif provider == LLMProvider.OPENAI:
        from aicommit.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(model=model)

    elif provider == LLMProvider.GOOGLE:
        from aicommit.llm.google_provider import GoogleProvider

        return GoogleProvider(model=model)

    elif provider == LLMProvider.MISTRAL:
        from aicommit.llm.mistral_provider import MistralProvider

        return MistralProvider(model=model)

    elif provider == LLMProvider.COHERE:
        from aicommit.llm.cohere_provider import CohereProvider

        return CohereProvider(model=model)

    elif provider == LLMProvider.GROQ:
        from aicommit.llm.groq_provider import GroqProvider

        return GroqProvider(model=model)

    elif provider == LLMProvider.OPENROUTER:
        from aicommit.llm.openrouter_provider import OpenRouterProvider

        return OpenRouterProvider(model=model)

    else:
        raise ValueError(f"Unsupported provider: {provider}")


def generate_commit_json(context_bundle: str) -> LLMResult:
    """Generate a commit message JSON from the git context bundle.

    This is the main entry point for generating commit messages.
    It uses the provider and model configured in config.py.

    Args:
        context_bundle: The formatted git context string from build_context_bundle().

    Returns:
        An LLMResult containing the validated CommitMessageJSON and token usage.

    Raises:
        MissingAPIKeyError: If the API key is not set.
        JSONParseError: If the LLM response cannot be parsed.
        LLMError: For other LLM-related errors.
    """
    provider = get_provider()
    return provider.generate(context_bundle)


# Export commonly used items
__all__ = [
    "BaseLLMProvider",
    "LLMError",
    "MissingAPIKeyError",
    "JSONParseError",
    "LLMResult",
    "get_provider",
    "generate_commit_json",
]
