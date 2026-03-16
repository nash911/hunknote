"""LiteLLM integration for the Compose Agent pipeline.

Uses LiteLLM as a unified interface for all 7 providers, eliminating
per-provider boilerplate. Only imported when --agent is used.
"""

import time
from typing import Callable

from hunknote.llm.base import RawLLMResult

# Map hunknote provider names to LiteLLM model prefixes
PROVIDER_PREFIX_MAP = {
    "anthropic": "",
    "openai": "",
    "google": "gemini/",
    "mistral": "mistral/",
    "cohere": "command-r-plus",
    "groq": "groq/",
    "openrouter": "openrouter/",
}


def get_litellm_model_name(provider: str, model: str) -> str:
    """Convert hunknote provider+model to LiteLLM model string."""
    prefix = PROVIDER_PREFIX_MAP.get(provider, "")
    return f"{prefix}{model}" if prefix else model


def create_llm_call_fn(
    provider: str,
    model: str,
    api_key: str,
    temperature: float = 0.3,
) -> Callable[[str, str], RawLLMResult]:
    """Create a (system_prompt, user_prompt) -> RawLLMResult callable.

    Args:
        provider: Hunknote provider name (e.g. "anthropic", "google").
        model: Model name (e.g. "claude-sonnet-4-20250514", "gemini-2.0-flash").
        api_key: API key for the provider.
        temperature: Sampling temperature.

    Returns:
        A callable that takes (system_prompt, user_prompt) and returns RawLLMResult.
    """
    import litellm
    from hunknote.llm import LLMError, MissingAPIKeyError

    litellm_model = get_litellm_model_name(provider, model)

    def llm_call_fn(system_prompt: str, user_prompt: str) -> RawLLMResult:
        start_time = time.time()
        try:
            response = litellm.completion(
                model=litellm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                api_key=api_key,
                temperature=temperature,
                max_tokens=8192,
            )
        except litellm.AuthenticationError as e:
            raise MissingAPIKeyError(f"API key error for {provider}: {e}")
        except Exception as e:
            raise LLMError(f"LLM call failed ({provider}/{model}): {e}")

        raw_response = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        thinking_tokens = 0
        if usage and hasattr(usage, "reasoning_tokens"):
            thinking_tokens = usage.reasoning_tokens or 0

        return RawLLMResult(
            raw_response=raw_response,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
        )

    return llm_call_fn
