"""Google Gemini provider implementation."""

import os

from google import genai
from google.genai import types

from aicommit.config import (
    API_KEY_ENV_VARS,
    LLMProvider,
    MAX_TOKENS,
    TEMPERATURE,
)
from aicommit.llm.base import (
    SYSTEM_PROMPT,
    BaseLLMProvider,
    LLMError,
    LLMResult,
    MissingAPIKeyError,
    parse_json_response,
    validate_commit_json,
)

# Models that have built-in "thinking" which consumes output tokens
# These models use internal reasoning that counts against max_output_tokens
# even without explicit thinking config, so we need a higher budget
THINKING_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash-thinking",
]

# Multiplier for max_output_tokens on thinking models
# Thinking can use 10-20x more tokens than the actual output
THINKING_TOKEN_MULTIPLIER = 3


class GoogleProvider(BaseLLMProvider):
    """Google Gemini LLM provider."""

    def __init__(self, model: str | None = None):
        """Initialize the Google provider.

        Args:
            model: The model to use. Defaults to gemini-2.0-flash.
        """
        self.model = model or "gemini-2.0-flash"
        self.api_key_env_var = API_KEY_ENV_VARS[LLMProvider.GOOGLE]

    def get_api_key(self) -> str:
        """Get the Google API key from environment.

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If GOOGLE_API_KEY is not set.
        """
        api_key = os.environ.get(self.api_key_env_var)
        if not api_key:
            raise MissingAPIKeyError(
                f"{self.api_key_env_var} environment variable is not set. "
                f"Please set it with: export {self.api_key_env_var}=your_key"
            )
        return api_key

    def _is_thinking_model(self) -> bool:
        """Check if the current model is a thinking model.

        Returns:
            True if the model supports/uses thinking feature.
        """
        return any(thinking_model in self.model.lower() for thinking_model in THINKING_MODELS)

    def generate(self, context_bundle: str) -> LLMResult:
        """Generate a commit message using Google Gemini.

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

        # Create the client with API key
        client = genai.Client(api_key=api_key)

        # Build the user prompt with system prompt embedded
        user_prompt = self.build_user_prompt(context_bundle)
        full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

        # For thinking models, we need a higher max_output_tokens budget
        # because internal "thinking" consumes tokens from this budget
        # even though it's not visible in the output
        effective_max_tokens = MAX_TOKENS
        if self._is_thinking_model():
            effective_max_tokens = MAX_TOKENS * THINKING_TOKEN_MULTIPLIER

        # Build base generation config
        base_config_kwargs = {
            "max_output_tokens": effective_max_tokens,
            "temperature": TEMPERATURE,
        }

        # Try to generate response, with fallback for thinking config errors
        response = self._generate_with_fallback(
            client, full_prompt, base_config_kwargs
        )

        try:
            # Check if response has candidates
            if not response.candidates:
                raise LLMError("Google Gemini returned no candidates in response")

            # Check finish reason - if it's not STOP, there might be an issue
            candidate = response.candidates[0]
            if hasattr(candidate, "finish_reason"):
                finish_reason = str(candidate.finish_reason)
                if "SAFETY" in finish_reason:
                    raise LLMError(f"Google Gemini blocked response due to safety filters: {finish_reason}")
                elif "MAX_TOKENS" in finish_reason:
                    raise LLMError("Google Gemini response was truncated due to max tokens limit. Try reducing diff size.")

            # Extract the text response
            raw_response = response.text

            if not raw_response or not raw_response.strip():
                raise LLMError("Google Gemini returned empty response")

            # Get token counts from usage metadata
            input_tokens = 0
            output_tokens = 0
            thoughts_tokens = 0

            if hasattr(response, "usage_metadata") and response.usage_metadata:
                if hasattr(response.usage_metadata, "prompt_token_count"):
                    input_tokens = response.usage_metadata.prompt_token_count or 0
                if hasattr(response.usage_metadata, "candidates_token_count"):
                    output_tokens = response.usage_metadata.candidates_token_count or 0
                # Track thinking tokens separately (these consume max_output_tokens budget)
                if hasattr(response.usage_metadata, "thoughts_token_count"):
                    thoughts_tokens = response.usage_metadata.thoughts_token_count or 0

            # For thinking models, add thoughts to output count for accurate budget tracking
            # since thoughts consume from max_output_tokens
            if thoughts_tokens > 0:
                output_tokens = output_tokens + thoughts_tokens

            # Fallback estimation if no token counts available
            if input_tokens == 0:
                input_tokens = len(full_prompt) // 4
            if output_tokens == 0:
                output_tokens = len(raw_response) // 4

        except MissingAPIKeyError:
            raise
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Google Gemini API call failed: {e}")

        # Parse and validate the JSON response
        parsed = parse_json_response(raw_response)
        commit_json = validate_commit_json(parsed, raw_response)

        return LLMResult(
            commit_json=commit_json,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _generate_with_fallback(self, client, full_prompt: str, base_config_kwargs: dict):
        """Generate content, handling API errors gracefully.

        Note: For thinking models (gemini-2.5-*), the max_output_tokens is already
        increased in the caller to account for internal thinking token consumption.

        Args:
            client: The Gemini client.
            full_prompt: The full prompt to send.
            base_config_kwargs: Base configuration kwargs.

        Returns:
            The API response.

        Raises:
            LLMError: If the API call fails.
        """
        try:
            return client.models.generate_content(
                model=self.model,
                contents=full_prompt,
                config=types.GenerateContentConfig(**base_config_kwargs),
            )
        except Exception as e:
            raise LLMError(f"Google Gemini API call failed: {e}")

