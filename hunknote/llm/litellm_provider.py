"""Unified LiteLLM provider implementation.

Routes all LLM calls through litellm.completion(), which provides a single
interface to Anthropic, OpenAI, Google Gemini, Mistral, Cohere, Groq,
OpenRouter, and 100+ other providers.

LiteLLM model name format per provider:
  - Anthropic:   "anthropic/<model>"        (e.g. anthropic/claude-sonnet-4-20250514)
  - OpenAI:      "openai/<model>"           (e.g. openai/gpt-4o) — prefix optional
  - Google:      "gemini/<model>"           (e.g. gemini/gemini-2.0-flash)
  - Mistral:     "mistral/<model>"          (e.g. mistral/mistral-large-latest)
  - Cohere:      "cohere_chat/<model>"      (e.g. cohere_chat/command-r-plus)
  - Groq:        "groq/<model>"             (e.g. groq/llama-3.3-70b-versatile)
  - OpenRouter:  "openrouter/<model>"       (e.g. openrouter/anthropic/claude-sonnet-4)
"""

import os

import litellm

import hunknote.config as _config
from hunknote.config import (
    API_KEY_ENV_VARS,
    LLMProvider,
)
from hunknote.llm.base import (
    SYSTEM_PROMPT,
    BaseLLMProvider,
    LLMError,
    LLMResult,
    RawLLMResult,
    MissingAPIKeyError,
    parse_json_response,
    validate_commit_json,
)

# Suppress litellm's noisy logging by default
litellm.suppress_debug_info = True

# ============================================================
# LiteLLM model prefix mapping
# ============================================================
# Maps our LLMProvider enum to the prefix litellm expects.

_LITELLM_PREFIX: dict[LLMProvider, str] = {
    LLMProvider.ANTHROPIC: "anthropic/",
    LLMProvider.OPENAI: "openai/",
    LLMProvider.GOOGLE: "gemini/",
    LLMProvider.MISTRAL: "mistral/",
    LLMProvider.COHERE: "cohere_chat/",
    LLMProvider.GROQ: "groq/",
    LLMProvider.OPENROUTER: "openrouter/",
}

# ============================================================
# API key → litellm env var mapping
# ============================================================
# LiteLLM reads specific env var names per provider. This maps
# our env var names to the names litellm expects.

_LITELLM_API_KEY_ENV: dict[LLMProvider, str] = {
    LLMProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
    LLMProvider.OPENAI: "OPENAI_API_KEY",
    LLMProvider.GOOGLE: "GEMINI_API_KEY",       # litellm uses GEMINI_API_KEY
    LLMProvider.MISTRAL: "MISTRAL_API_KEY",
    LLMProvider.COHERE: "COHERE_API_KEY",
    LLMProvider.GROQ: "GROQ_API_KEY",
    LLMProvider.OPENROUTER: "OPENROUTER_API_KEY",
}

# ============================================================
# Thinking model detection
# ============================================================
# Models that use internal "thinking" which consumes output tokens.

_THINKING_MODEL_PATTERNS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash-thinking",
    "gemini-3",            # future-proof for gemini-3-*
    "claude-3-7-sonnet",   # Claude 3.7 extended thinking
    "o1",                  # OpenAI o1 reasoning
    "o3",                  # OpenAI o3 reasoning
    "o4",                  # OpenAI o4 reasoning
]

# Multiplier for max_tokens on thinking models
_THINKING_TOKEN_MULTIPLIER = 3


def _build_litellm_model_name(provider: LLMProvider, model: str) -> str:
    """Build the litellm model identifier from provider + model name.

    Args:
        provider: The LLM provider enum.
        model: The model name (without prefix).

    Returns:
        A litellm-compatible model string (e.g. "gemini/gemini-2.0-flash").
    """
    prefix = _LITELLM_PREFIX.get(provider, "")

    # For OpenRouter, models already have a provider/ prefix (e.g. "anthropic/claude-sonnet-4").
    # LiteLLM expects "openrouter/<provider>/<model>".
    if provider == LLMProvider.OPENROUTER:
        return f"{prefix}{model}"

    # Skip prefix if the model already contains it
    if prefix and model.startswith(prefix):
        return model

    return f"{prefix}{model}"


def _is_thinking_model(model: str) -> bool:
    """Check whether a model uses internal "thinking" tokens.

    Args:
        model: The model name (may include litellm prefix).

    Returns:
        True if the model is known to use thinking/reasoning tokens.
    """
    model_lower = model.lower()
    return any(pattern in model_lower for pattern in _THINKING_MODEL_PATTERNS)


class LiteLLMProvider(BaseLLMProvider):
    """Unified LLM provider backed by litellm.

    Handles all supported providers through a single ``litellm.completion()``
    call, eliminating the need for separate per-provider implementations.
    """

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        style: str = "default",
    ):
        """Initialize the LiteLLM provider.

        Args:
            provider: The LLMProvider enum (ANTHROPIC, OPENAI, GOOGLE, etc.).
            model: The model name (e.g. "gemini-2.0-flash", "gpt-4o").
            style: The commit style to use (default, blueprint, conventional, ticket, kernel).
        """
        self.provider = provider
        self.model = model
        self.style = style
        self.api_key_env_var = API_KEY_ENV_VARS[provider]

        # Build the litellm model identifier once
        self._litellm_model = _build_litellm_model_name(provider, model)

    # ------------------------------------------------------------------
    # API key resolution
    # ------------------------------------------------------------------

    def get_api_key(self) -> str:
        """Get the API key from system keychain or environment.

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If the API key is not found.
        """
        provider_name = self.provider.value.capitalize()
        if self.provider == LLMProvider.OPENROUTER:
            provider_name = "OpenRouter"
        return self._get_api_key_with_fallback(self.api_key_env_var, provider_name)

    def _inject_api_key_for_litellm(self) -> str:
        """Resolve the API key and set it in the environment so litellm can find it.

        LiteLLM reads API keys from well-known env vars. For most providers the
        var name matches ours, but for Google we store ``GOOGLE_API_KEY`` while
        litellm reads ``GEMINI_API_KEY``. This helper bridges the gap.

        Returns:
            The resolved API key string.

        Raises:
            MissingAPIKeyError: If the API key is not found anywhere.
        """
        api_key = self.get_api_key()

        # Set the env var litellm expects (if different from ours)
        litellm_env_var = _LITELLM_API_KEY_ENV.get(self.provider)
        if litellm_env_var and litellm_env_var != self.api_key_env_var:
            os.environ[litellm_env_var] = api_key

        return api_key

    # ------------------------------------------------------------------
    # Token budget helpers
    # ------------------------------------------------------------------

    def _effective_max_tokens(self, *, for_raw: bool = False) -> int:
        """Compute the effective max_tokens, accounting for thinking models.

        Args:
            for_raw: If True, use a higher base budget suitable for compose/raw
                     generation (at least 8192).

        Returns:
            The effective max token count.
        """
        base = _config.MAX_TOKENS
        if for_raw:
            base = max(base, 16384)

        if _is_thinking_model(self._litellm_model):
            return base * _THINKING_TOKEN_MULTIPLIER
        return base

    # ------------------------------------------------------------------
    # generate() — commit message JSON generation
    # ------------------------------------------------------------------

    def generate(self, context_bundle: str) -> LLMResult:
        """Generate a commit message using litellm.

        Args:
            context_bundle: The formatted git context string.

        Returns:
            An LLMResult containing the commit message and metadata.

        Raises:
            MissingAPIKeyError: If the API key is not set.
            JSONParseError: If the response cannot be parsed.
            LLMError: For other LLM-related errors.
        """
        api_key = self._inject_api_key_for_litellm()

        # Build the user prompt for the configured style
        user_prompt = self.build_user_prompt_for_style(context_bundle, self.style)

        try:
            response = litellm.completion(
                model=self._litellm_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self._effective_max_tokens(),
                temperature=_config.TEMPERATURE,
                api_key=api_key,
            )

            # Extract the text response
            raw_response = response.choices[0].message.content

            # Extract token usage (litellm normalises this to OpenAI format)
            input_tokens = 0
            output_tokens = 0
            thinking_tokens = 0
            if response.usage:
                input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(response.usage, "completion_tokens", 0) or 0

            # Some providers report thinking/reasoning tokens in usage
            if hasattr(response.usage, "completion_tokens_details") and response.usage.completion_tokens_details:
                details = response.usage.completion_tokens_details
                thinking_tokens = getattr(details, "reasoning_tokens", 0) or 0

        except MissingAPIKeyError:
            raise
        except Exception as e:
            raise LLMError(f"LLM API call failed ({self.provider.value}/{self.model}): {e}")

        # Parse and validate the JSON response
        parsed = parse_json_response(raw_response)
        commit_json = validate_commit_json(parsed, raw_response)

        # Calculate character counts
        input_chars = len(context_bundle)
        prompt_chars = len(SYSTEM_PROMPT) + len(user_prompt)
        output_chars = len(raw_response)

        return LLMResult(
            commit_json=commit_json,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw_response=raw_response,
            input_chars=input_chars,
            prompt_chars=prompt_chars,
            output_chars=output_chars,
            thinking_tokens=thinking_tokens,
        )

    # ------------------------------------------------------------------
    # generate_raw() — raw text generation (for compose mode, etc.)
    # ------------------------------------------------------------------

    def generate_raw(
        self, system_prompt: str, user_prompt: str
    ) -> RawLLMResult:
        """Generate a raw LLM response without JSON parsing.

        Args:
            system_prompt: The system prompt to use.
            user_prompt: The user prompt to use.

        Returns:
            A RawLLMResult containing the raw response and token usage.

        Raises:
            MissingAPIKeyError: If the API key is not set.
            LLMError: For other LLM-related errors.
        """
        api_key = self._inject_api_key_for_litellm()

        try:
            response = litellm.completion(
                model=self._litellm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self._effective_max_tokens(for_raw=True),
                temperature=_config.TEMPERATURE,
                api_key=api_key,
            )

            raw_response = response.choices[0].message.content

            if not raw_response or not raw_response.strip():
                raise LLMError(
                    f"LLM returned empty response ({self.provider.value}/{self.model})"
                )

            # Extract token usage
            input_tokens = 0
            output_tokens = 0
            thinking_tokens = 0
            if response.usage:
                input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(response.usage, "completion_tokens", 0) or 0

            if hasattr(response.usage, "completion_tokens_details") and response.usage.completion_tokens_details:
                details = response.usage.completion_tokens_details
                thinking_tokens = getattr(details, "reasoning_tokens", 0) or 0

        except MissingAPIKeyError:
            raise
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"LLM API call failed ({self.provider.value}/{self.model}): {e}")

        return RawLLMResult(
            raw_response=raw_response,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
        )

