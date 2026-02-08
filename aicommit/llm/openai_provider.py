"""OpenAI GPT provider implementation."""

import os

from openai import OpenAI

from aicommit.config import (
    ACTIVE_MODEL,
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


class OpenAIProvider(BaseLLMProvider):
    """OpenAI GPT LLM provider."""

    def __init__(self, model: str | None = None):
        """Initialize the OpenAI provider.

        Args:
            model: The model to use. Defaults to gpt-4o.
        """
        self.model = model or "gpt-4o"
        self.api_key_env_var = API_KEY_ENV_VARS[LLMProvider.OPENAI]

    def get_api_key(self) -> str:
        """Get the OpenAI API key from environment.

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If OPENAI_API_KEY is not set.
        """
        api_key = os.environ.get(self.api_key_env_var)
        if not api_key:
            raise MissingAPIKeyError(
                f"{self.api_key_env_var} environment variable is not set. "
                f"Please set it with: export {self.api_key_env_var}=your_key"
            )
        return api_key

    def generate(self, context_bundle: str) -> LLMResult:
        """Generate a commit message using OpenAI GPT.

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

        # Create the OpenAI client
        client = OpenAI(api_key=api_key)

        # Build the user prompt
        user_prompt = self.build_user_prompt(context_bundle)

        try:
            # Call the OpenAI API
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
            raise LLMError(f"OpenAI API call failed: {e}")

        # Parse and validate the JSON response
        parsed = parse_json_response(raw_response)
        commit_json = validate_commit_json(parsed, raw_response)

        return LLMResult(
            commit_json=commit_json,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
