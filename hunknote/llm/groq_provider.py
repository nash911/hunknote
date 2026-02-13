"""Groq provider implementation."""

import os

from groq import Groq

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


class GroqProvider(BaseLLMProvider):
    """Groq LLM provider (fast inference for open-source models)."""

    def __init__(self, model: str | None = None):
        """Initialize the Groq provider.

        Args:
            model: The model to use. Defaults to llama-3.3-70b-versatile.
        """
        self.model = model or "llama-3.3-70b-versatile"
        self.api_key_env_var = API_KEY_ENV_VARS[LLMProvider.GROQ]

    def get_api_key(self) -> str:
        """Get the Groq API key from environment or credentials file.

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If GROQ_API_KEY is not found.
        """
        return self._get_api_key_with_fallback(self.api_key_env_var, "Groq")

    def generate(self, context_bundle: str) -> LLMResult:
        """Generate a commit message using Groq.

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

        # Create the Groq client
        client = Groq(api_key=api_key)

        # Build the user prompt
        user_prompt = self.build_user_prompt(context_bundle)

        try:
            # Call the Groq API (OpenAI-compatible)
            response = client.chat.completions.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )

            # Extract the text response
            raw_response = response.choices[0].message.content

            # Extract token usage
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens

        except MissingAPIKeyError:
            raise
        except Exception as e:
            raise LLMError(f"Groq API call failed: {e}")

        # Parse and validate the JSON response
        parsed = parse_json_response(raw_response)
        commit_json = validate_commit_json(parsed, raw_response)

        return LLMResult(
            commit_json=commit_json,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
