"""Anthropic Claude provider implementation."""

import os

from anthropic import Anthropic

from hunknote.config import (
    ACTIVE_MODEL,
    API_KEY_ENV_VARS,
    LLMProvider,
    MAX_TOKENS,
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


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude LLM provider."""

    def __init__(self, model: str | None = None, style: str = "default"):
        """Initialize the Anthropic provider.

        Args:
            model: The model to use. Defaults to ACTIVE_MODEL from config.
            style: The commit style to use (default, blueprint, conventional, ticket, kernel).
        """
        self.model = model or ACTIVE_MODEL
        self.style = style
        self.api_key_env_var = API_KEY_ENV_VARS[LLMProvider.ANTHROPIC]

    def get_api_key(self) -> str:
        """Get the Anthropic API key from environment or credentials file.

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If ANTHROPIC_API_KEY is not found.
        """
        return self._get_api_key_with_fallback(self.api_key_env_var, "Anthropic")

    def generate(self, context_bundle: str) -> LLMResult:
        """Generate a commit message using Anthropic Claude.

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

        # Create the Anthropic client
        client = Anthropic(api_key=api_key)

        # Build the user prompt for the configured style
        user_prompt = self.build_user_prompt_for_style(context_bundle, self.style)

        try:
            # Call the Anthropic API
            message = client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Extract the text response
            raw_response = message.content[0].text

            # Extract token usage
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens

        except MissingAPIKeyError:
            raise
        except Exception as e:
            raise LLMError(f"Anthropic API call failed: {e}")

        # Parse and validate the JSON response
        parsed = parse_json_response(raw_response)
        commit_json = validate_commit_json(parsed, raw_response)

        return LLMResult(
            commit_json=commit_json,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw_response=raw_response,
        )
