"""OpenRouter provider implementation.

OpenRouter provides unified access to 200+ models through a single API.
It uses an OpenAI-compatible API format.
"""

import os

from openai import OpenAI

from hunknote.config import (
    ACTIVE_MODEL,
    API_KEY_ENV_VARS,
    LLMProvider,
    MAX_TOKENS,
    TEMPERATURE,
)
from hunknote.llm.base import (
    SYSTEM_PROMPT,
    BaseLLMProvider,
    LLMError,
    LLMResult,
    MissingAPIKeyError,
    parse_json_response,
    validate_commit_json,
)

# OpenRouter API base URL
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter LLM provider (unified access to 200+ models)."""

    def __init__(self, model: str | None = None, style: str = "default"):
        """Initialize the OpenRouter provider.

        Args:
            model: The model to use. Defaults to anthropic/claude-sonnet-4.
                   Use format: provider/model-name (e.g., openai/gpt-4o)
            style: The commit style to use (default, blueprint, conventional, ticket, kernel).
        """
        self.model = model or "anthropic/claude-sonnet-4"
        self.style = style
        self.api_key_env_var = API_KEY_ENV_VARS[LLMProvider.OPENROUTER]

    def get_api_key(self) -> str:
        """Get the OpenRouter API key from environment or credentials file.

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If OPENROUTER_API_KEY is not found.
        """
        return self._get_api_key_with_fallback(self.api_key_env_var, "OpenRouter")

    def generate(self, context_bundle: str) -> LLMResult:
        """Generate a commit message using OpenRouter.

        Args:
            context_bundle: The formatted git context string.

        Returns:
            An LLMResult containing the commit message and metadata.

        Raises:
            MissingAPIKeyError: If the API key is not set.
            JSONParseError: If the response cannot be parsed.
            LLMError: For other LLM-related errors.
        """
        api_key = self.get_api_key()

        # Create an OpenAI client pointing to OpenRouter
        client = OpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
        )

        # Build the user prompt for the configured style
        user_prompt = self.build_user_prompt_for_style(context_bundle, self.style)

        try:
            # Call the OpenRouter API (OpenAI-compatible)
            response = client.chat.completions.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                extra_headers={
                    "HTTP-Referer": "https://github.com/hunknote",
                    "X-Title": "hunknote",
                },
            )

            # Extract the text response
            raw_response = response.choices[0].message.content

            # Extract token usage
            input_tokens = response.usage.prompt_tokens if response.usage else 0
            output_tokens = response.usage.completion_tokens if response.usage else 0

        except MissingAPIKeyError:
            raise
        except Exception as e:
            raise LLMError(f"OpenRouter API call failed: {e}")

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
        )
