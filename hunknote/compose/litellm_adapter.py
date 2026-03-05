"""LiteLLM adapter for compose ReAct agents."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import litellm

from hunknote.config import API_KEY_ENV_VARS, LLMProvider

logger = logging.getLogger(__name__)

_PROVIDER_PREFIX: dict[str, str] = {
    "google": "gemini",
    "anthropic": "anthropic",
    "openai": "",
    "mistral": "mistral",
    "cohere": "cohere_chat",
    "groq": "groq",
    "openrouter": "openrouter",
}


def to_litellm_model(provider: str, model: str) -> str:
    """Map hunknote provider/model to a LiteLLM model string."""
    prefix = _PROVIDER_PREFIX.get((provider or "").lower(), "")
    if not prefix:
        return model
    return f"{prefix}/{model}"


def setup_litellm_api_keys(provider: str | None = None) -> None:
    """Make provider keys visible to LiteLLM via environment variables."""
    try:
        from hunknote.global_config import get_credential
    except Exception:
        logger.debug("global_config unavailable; relying on env vars for LiteLLM")
        return

    providers = [provider.lower()] if provider else [p.value for p in LLMProvider]

    for provider_name in providers:
        try:
            enum_val = LLMProvider(provider_name)
        except ValueError:
            continue

        env_var = API_KEY_ENV_VARS.get(enum_val)
        if not env_var or os.getenv(env_var):
            continue

        try:
            key = get_credential(env_var)
            if key:
                os.environ[env_var] = key
        except Exception:
            continue


def litellm_completion(
    *,
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
    temperature: float = 0.1,
    max_tokens: int = 8192,
) -> Any:
    """Thin wrapper around ``litellm.completion``."""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice

    litellm.suppress_debug_info = True
    return litellm.completion(**kwargs)


def parse_tool_arguments(arguments: str | dict | None) -> dict:
    """Parse tool-call arguments from LiteLLM response payload."""
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str):
        return {}
    try:
        return json.loads(arguments)
    except Exception:
        logger.warning("Failed to parse tool arguments: %s", arguments[:200])
        return {}


def extract_usage(response: Any) -> tuple[int, int, int]:
    """Return ``(input_tokens, output_tokens, thinking_tokens)``."""
    usage = getattr(response, "usage", None)
    if not usage:
        return (0, 0, 0)
    return (
        getattr(usage, "prompt_tokens", 0) or 0,
        getattr(usage, "completion_tokens", 0) or 0,
        getattr(usage, "reasoning_tokens", 0) or 0,
    )
