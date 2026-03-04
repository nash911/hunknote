"""LiteLLM adapter for the ReAct Compose Agent.

Bridges hunknote's provider/model naming and credential system to LiteLLM's
unified API. Used ONLY by the ReAct agent for multi-turn tool-calling
conversations.  The existing BaseLLMProvider / generate_raw() interface is
unchanged for non-agent paths.
"""

import json
import logging
import os
from typing import Any, Optional

import litellm

from hunknote.config import API_KEY_ENV_VARS, LLMProvider

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# Model Name Mapping
# ────────────────────────────────────────────────────────────

_PROVIDER_PREFIX: dict[str, str] = {
    "google": "gemini",
    "anthropic": "anthropic",
    "openai": "",          # LiteLLM uses OpenAI names directly
    "mistral": "mistral",
    "cohere": "cohere_chat",
    "groq": "groq",
    "openrouter": "openrouter",
}


def to_litellm_model(provider: str, model: str) -> str:
    """Convert hunknote provider/model to a LiteLLM model string.

    Examples:
        ("google",    "gemini-2.5-flash")  → "gemini/gemini-2.5-flash"
        ("anthropic", "claude-sonnet-4-…") → "anthropic/claude-sonnet-4-…"
        ("openai",    "gpt-4o")            → "gpt-4o"
        ("groq",      "llama-3.3-70b-…")  → "groq/llama-3.3-70b-…"

    Args:
        provider: Hunknote provider name (lower-case).
        model: Model name as configured in hunknote.

    Returns:
        A LiteLLM-compatible model string.
    """
    prefix = _PROVIDER_PREFIX.get(provider.lower(), "")
    if not prefix:
        return model
    return f"{prefix}/{model}"


# ────────────────────────────────────────────────────────────
# API Key Bridging
# ────────────────────────────────────────────────────────────

def setup_litellm_api_keys(provider: Optional[str] = None) -> None:
    """Ensure LiteLLM can find the API key(s) it needs.

    Hunknote stores API keys in the system keychain (primary) with an
    environment-variable fallback.  LiteLLM reads keys from env vars, so
    we copy them from the keychain into the process environment if they
    are not already set.

    If *provider* is given, only that provider's key is set up.
    Otherwise, all known providers' keys are attempted.

    Args:
        provider: Optional provider name to limit key setup.
    """
    try:
        from hunknote.global_config import get_credential
    except ImportError:
        logger.debug("global_config not available, relying on env vars for LiteLLM")
        return

    if provider:
        providers = [provider.lower()]
    else:
        providers = [p.value for p in LLMProvider]

    for prov_name in providers:
        try:
            prov_enum = LLMProvider(prov_name)
        except ValueError:
            continue
        env_var = API_KEY_ENV_VARS.get(prov_enum)
        if not env_var:
            continue
        # Skip if already set
        if os.environ.get(env_var):
            continue
        # Try keychain
        try:
            key = get_credential(env_var)
            if key:
                os.environ[env_var] = key
                logger.debug("Injected %s into env for LiteLLM", env_var)
        except Exception:
            pass


# ────────────────────────────────────────────────────────────
# Convenience wrapper
# ────────────────────────────────────────────────────────────

def litellm_completion(
    model: str,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    tool_choice: str = "auto",
    temperature: float = 0.3,
    max_tokens: int = 8192,
    stream: bool = False,
    response_format: Optional[dict] = None,
) -> Any:
    """Thin wrapper around litellm.completion with sensible defaults.

    Args:
        model: LiteLLM model string (use to_litellm_model to convert).
        messages: Chat messages list.
        tools: Optional tool definitions for function calling.
        tool_choice: Tool choice strategy ("auto", "none", etc.).
        temperature: Sampling temperature.
        max_tokens: Maximum output tokens.
        stream: Whether to stream the response.
        response_format: Optional response format hint (e.g., {"type": "json_object"}).

    Returns:
        LiteLLM completion response.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice
    if response_format:
        kwargs["response_format"] = response_format

    # Suppress LiteLLM's verbose logging
    litellm.suppress_debug_info = True

    return litellm.completion(**kwargs)


# ────────────────────────────────────────────────────────────
# Token Budget Calculator
# ────────────────────────────────────────────────────────────

def calculate_token_budget(
    num_hunks: int,
    total_diff_lines: int,
    base_budget: int = 16384,
) -> int:
    """Calculate a dynamic token budget based on diff size.

    Prevents runaway costs on very large diffs while allowing enough
    room for complex plans.

    Args:
        num_hunks: Number of hunks in the diff.
        total_diff_lines: Total number of changed lines.
        base_budget: Minimum token budget.

    Returns:
        Computed token budget.
    """
    # ~4 tokens per line of diff, plus overhead for reasoning
    estimated_input = total_diff_lines * 4
    # Each sub-agent call adds overhead
    estimated_overhead = num_hunks * 200  # ~200 tokens per hunk in prompts/tools
    # Cap at a reasonable maximum
    budget = max(base_budget, estimated_input + estimated_overhead)
    return min(budget, 131072)  # Absolute cap: 128K tokens


def parse_tool_arguments(arguments: str) -> dict:
    """Safely parse tool call arguments from LiteLLM response.

    Args:
        arguments: JSON string of tool arguments.

    Returns:
        Parsed dictionary, or empty dict on failure.
    """
    try:
        return json.loads(arguments) if arguments else {}
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse tool arguments: %s", arguments[:200])
        return {}

