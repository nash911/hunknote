"""Cohere provider implementation."""

import cohere

from hunknote.config import (
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


class CohereProvider(BaseLLMProvider):
    """Cohere LLM provider."""

    def __init__(self, model: str | None = None, style: str = "default"):
        """Initialize the Cohere provider.

        Args:
            model: The model to use. Defaults to command-r-plus.
            style: The commit style to use (default, blueprint, conventional, ticket, kernel).
        """
        self.model = model or "command-r-plus"
        self.style = style
        self.api_key_env_var = API_KEY_ENV_VARS[LLMProvider.COHERE]

    def get_api_key(self) -> str:
        """Get the Cohere API key from environment or credentials file.

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If COHERE_API_KEY is not found.
        """
        return self._get_api_key_with_fallback(self.api_key_env_var, "Cohere")

    def generate(self, context_bundle: str) -> LLMResult:
        """Generate a commit message using Cohere.

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

        # Create the Cohere client
        client = cohere.ClientV2(api_key=api_key)

        # Build the user prompt for the configured style
        user_prompt = self.build_user_prompt_for_style(context_bundle, self.style)

        try:
            # Call the Cohere API using chat endpoint
            response = client.chat(
                model=self.model,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )

            # Extract the text response
            raw_response = response.message.content[0].text

            # Extract token usage
            input_tokens = response.usage.tokens.input_tokens
            output_tokens = response.usage.tokens.output_tokens

        except MissingAPIKeyError:
            raise
        except Exception as e:
            raise LLMError(f"Cohere API call failed: {e}")

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
