"""Base classes and shared utilities for LLM providers."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from hunknote.formatters import CommitMessageJSON


class LLMError(Exception):
    """Base exception for LLM-related errors."""

    pass


class MissingAPIKeyError(LLMError):
    """Raised when the required API key is not set."""

    pass


class JSONParseError(LLMError):
    """Raised when the LLM response cannot be parsed as valid JSON."""

    pass


@dataclass
class LLMResult:
    """Result from an LLM generation call, including token usage."""

    commit_json: CommitMessageJSON
    model: str
    input_tokens: int
    output_tokens: int


# System prompt for the LLM (shared across all providers)
SYSTEM_PROMPT = """You are an expert software engineer writing git commit messages.
Be precise: only describe changes actually shown in the diff.
The [FILE_CHANGES] section tells you which files are NEW vs MODIFIED - use this to write accurate descriptions."""

# User prompt template (shared across all providers)
USER_PROMPT_TEMPLATE = """Given the following git context, produce a JSON object with exactly these keys:
- "title": string (imperative mood, <=72 chars)
- "body_bullets": array of 2-7 strings (each concise, describe what changed and why)

Rules:
- Output ONLY valid JSON. No markdown fences. No extra keys. No commentary.
- Title in imperative mood (e.g., "Add feature" not "Added feature").
- Only describe changes shown in the diff. Do not infer or assume other changes.
- [FILE_CHANGES] shows:
  * NEW files (created in this commit)
  * MODIFIED files (already existed)
  * DELETED files (removed in this commit)
  * RENAMED files (moved/renamed in this commit).
  Use these to write accurate descriptions.

GIT CONTEXT:
{context_bundle}"""


def parse_json_response(raw_response: str) -> dict:
    """Parse the LLM response as JSON.

    Args:
        raw_response: The raw text response from the LLM.

    Returns:
        The parsed JSON as a dictionary.

    Raises:
        JSONParseError: If parsing fails.
    """
    # Clean up the response - remove any markdown fences if present
    cleaned = raw_response.strip()

    # Remove markdown code fences if the model included them despite instructions
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line (```json or ```)
        lines = lines[1:]
        # Remove last line if it's ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    # Try to extract JSON object if there's extra content
    # Find the first { and last }
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        cleaned = cleaned[first_brace:last_brace + 1]

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise JSONParseError(
            f"Failed to parse LLM response as JSON.\n"
            f"Error: {e}\n"
            f"Raw response:\n{raw_response}"
        )


def validate_commit_json(parsed: dict, raw_response: str) -> CommitMessageJSON:
    """Validate parsed JSON against the CommitMessageJSON schema.

    Args:
        parsed: The parsed JSON dictionary.
        raw_response: The original raw response (for error messages).

    Returns:
        A validated CommitMessageJSON object.

    Raises:
        JSONParseError: If validation fails.
    """
    try:
        return CommitMessageJSON(**parsed)
    except Exception as e:
        raise JSONParseError(
            f"LLM response does not match expected schema.\n"
            f"Error: {e}\n"
            f"Parsed JSON: {parsed}"
        )


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def generate(self, context_bundle: str) -> LLMResult:
        """Generate a commit message from the git context bundle.

        Args:
            context_bundle: The formatted git context string.

        Returns:
            An LLMResult containing the commit message and metadata.

        Raises:
            MissingAPIKeyError: If the API key is not set.
            JSONParseError: If the response cannot be parsed.
            LLMError: For other LLM-related errors.
        """
        pass

    @abstractmethod
    def get_api_key(self) -> str:
        """Get the API key from environment or credentials file.

        Checks in order:
        1. Environment variable
        2. ~/.hunknote/credentials file
        3. Repo-level .env file (if loaded)

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If the API key is not found.
        """
        pass

    def _get_api_key_with_fallback(self, env_var_name: str, provider_name: str) -> str:
        """Helper to get API key with fallback to credentials file.

        Args:
            env_var_name: Environment variable name to check.
            provider_name: Human-readable provider name for error messages.

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If the API key is not found.
        """
        import os

        # First check environment variable
        api_key = os.getenv(env_var_name)
        if api_key:
            return api_key

        # Then check credentials file
        try:
            from hunknote.global_config import get_credential
            api_key = get_credential(env_var_name)
            if api_key:
                return api_key
        except Exception:
            # If global_config isn't available, continue to error
            pass

        # Not found anywhere
        raise MissingAPIKeyError(
            f"{provider_name} API key not found. Set it using:\n"
            f"  1. Environment variable: export {env_var_name}=your_key_here\n"
            f"  2. Run: hunknote config set-key {provider_name.lower()}\n"
            f"  3. Manually add to ~/.hunknote/credentials"
        )

    def build_user_prompt(self, context_bundle: str) -> str:
        """Build the user prompt from the context bundle.

        Args:
            context_bundle: The git context string.

        Returns:
            The formatted user prompt.
        """
        return USER_PROMPT_TEMPLATE.format(context_bundle=context_bundle)
