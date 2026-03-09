"""LLM provider module for hunknote.

This module provides a unified interface to multiple LLM providers
via LiteLLM. All providers (Anthropic, OpenAI, Google, Mistral,
Cohere, Groq, OpenRouter) are routed through a single LiteLLMProvider.

The active provider is configured in hunknote/config.py.
"""

from dotenv import load_dotenv

import hunknote.config as _config
from hunknote.config import LLMProvider
from hunknote.llm.base import (
    BaseLLMProvider,
    JSONParseError,
    LLMError,
    LLMResult,
    RawLLMResult,
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

    All providers are routed through LiteLLMProvider, which uses litellm
    to provide a unified interface to every supported LLM backend.

    Args:
        provider: The provider to use. Defaults to ACTIVE_PROVIDER from config.
        model: The model to use. Defaults to ACTIVE_MODEL from config.
        style: The commit style to use (default, blueprint, conventional, ticket, kernel).

    Returns:
        A LiteLLMProvider instance configured for the requested provider.

    Raises:
        ValueError: If the provider is not supported.
    """
    from hunknote.llm.litellm_provider import LiteLLMProvider

    # Read config values at call time (not import time) so that
    # load_config() updates are visible even if this module was
    # imported before load_config() ran.
    provider = provider or _config.ACTIVE_PROVIDER
    model = model or _config.ACTIVE_MODEL
    style = style or "default"

    # Validate provider
    if not isinstance(provider, LLMProvider):
        raise ValueError(f"Unsupported provider: {provider}")

    return LiteLLMProvider(provider=provider, model=model, style=style)


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
    "RawLLMResult",
    "get_provider",
    "generate_commit_json",
]
