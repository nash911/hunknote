"""LLM provider module for hunknote.

This module provides a unified interface to multiple LLM providers.
The active provider is configured in hunknote/config.py.
"""

from dotenv import load_dotenv

from hunknote.config import ACTIVE_MODEL, ACTIVE_PROVIDER, LLMProvider
from hunknote.llm.base import (
    BaseLLMProvider,
    JSONParseError,
    LLMError,
    LLMResult,
    MissingAPIKeyError,
)

# Load environment variables from .env file
load_dotenv()

def get_provider(
    provider: LLMProvider | None = None,
    model: str | None = None,
    style: str | None = None,
) -> BaseLLMProvider:
    """Get an LLM provider instance.

    Args:
        provider: The provider to use. Defaults to ACTIVE_PROVIDER from config.
        model: The model to use. Defaults to ACTIVE_MODEL from config.
        style: The commit style to use (default, blueprint, conventional, ticket, kernel).

    Returns:
        An instance of the appropriate LLM provider.

    Raises:
        ValueError: If the provider is not supported.
    """
    provider = provider or ACTIVE_PROVIDER
    model = model or ACTIVE_MODEL
    style = style or "default"

    if provider == LLMProvider.ANTHROPIC:
        from hunknote.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=model, style=style)

    elif provider == LLMProvider.OPENAI:
        from hunknote.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(model=model, style=style)

    elif provider == LLMProvider.GOOGLE:
        from hunknote.llm.google_provider import GoogleProvider

        return GoogleProvider(model=model, style=style)

    elif provider == LLMProvider.MISTRAL:
        from hunknote.llm.mistral_provider import MistralProvider

        return MistralProvider(model=model, style=style)

    elif provider == LLMProvider.COHERE:
        from hunknote.llm.cohere_provider import CohereProvider

        return CohereProvider(model=model, style=style)

    elif provider == LLMProvider.GROQ:
        from hunknote.llm.groq_provider import GroqProvider

        return GroqProvider(model=model, style=style)

    elif provider == LLMProvider.OPENROUTER:
        from hunknote.llm.openrouter_provider import OpenRouterProvider

        return OpenRouterProvider(model=model, style=style)

    else:
        raise ValueError(f"Unsupported provider: {provider}")


def generate_commit_json(context_bundle: str, style: str = "default") -> LLMResult:
    """Generate a commit message JSON from the git context bundle.

    This is the main entry point for generating commit messages.
    It uses the provider and model configured in config.py.

    Args:
        context_bundle: The formatted git context string from build_context_bundle().
        style: The commit style (default, blueprint, conventional, ticket, kernel).

    Returns:
        An LLMResult containing the validated ExtendedCommitJSON and token usage.
        The ExtendedCommitJSON supports all style formats (default, blueprint,
        conventional, ticket, kernel).

    Raises:
        MissingAPIKeyError: If the API key is not set.
        JSONParseError: If the LLM response cannot be parsed.
        LLMError: For other LLM-related errors.
    """
    provider = get_provider(style=style)
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
