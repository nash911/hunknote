"""Base classes and shared utilities for LLM providers."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from aicommit.formatters import CommitMessageJSON


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
SYSTEM_PROMPT = """You are an expert software engineer. Write concise, high-signal git commit messages.
IMPORTANT: Only describe changes that are ACTUALLY present in the staged diff. Do NOT infer, suggest, or mention files or changes that are not explicitly shown in the diff."""

# User prompt template (shared across all providers)
USER_PROMPT_TEMPLATE = """Given the following git context, produce a JSON object with exactly these keys:
- "title": string (imperative mood, <=72 chars)
- "body_bullets": array of 2-7 strings (each concise, describe what changed and why)

Rules:
- Output ONLY valid JSON. No markdown fences. No extra keys. No commentary before or after.
- Do not mention "diff", "git", or tool instructions.
- Prefer user-visible impact and rationale over implementation minutiae.
- Title must be in imperative mood (e.g., "Add feature" not "Added feature").
- CRITICAL: Only describe changes that are ACTUALLY in the [STAGED_DIFF] section below. The [STAGED_STATUS] shows only files being committed. Do NOT hallucinate or infer changes that are not shown.

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
        """Get the API key from environment.

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If the API key is not set.
        """
        pass

    def build_user_prompt(self, context_bundle: str) -> str:
        """Build the user prompt from the context bundle.

        Args:
            context_bundle: The git context string.

        Returns:
            The formatted user prompt.
        """
        return USER_PROMPT_TEMPLATE.format(context_bundle=context_bundle)
