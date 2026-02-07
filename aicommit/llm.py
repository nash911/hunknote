"""LLM integration for generating commit messages."""

import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from anthropic import Anthropic

from aicommit.formatters import CommitMessageJSON

# Load environment variables from .env file
load_dotenv()


class LLMError(Exception):
    """Custom exception for LLM-related errors."""
    pass


class MissingAPIKeyError(LLMError):
    """Raised when ANTHROPIC_API_KEY is not set."""
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


# System prompt for the LLM
SYSTEM_PROMPT = """You are an expert software engineer. Write concise, high-signal git commit messages."""

# User prompt template
USER_PROMPT_TEMPLATE = """Given the following git context, produce a JSON object with exactly these keys:
- "title": string (imperative mood, <=72 chars)
- "body_bullets": array of 2-7 strings (each concise, describe what changed and why)

Rules:
- Output ONLY valid JSON. No markdown fences. No extra keys. No commentary before or after.
- Do not mention "diff", "git", or tool instructions.
- Prefer user-visible impact and rationale over implementation minutiae.
- Title must be in imperative mood (e.g., "Add feature" not "Added feature").

GIT CONTEXT:
{context_bundle}"""


def _get_api_key() -> str:
    """Get the Anthropic API key from environment.

    Returns:
        The API key string.

    Raises:
        MissingAPIKeyError: If ANTHROPIC_API_KEY is not set.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise MissingAPIKeyError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Please set it with: export ANTHROPIC_API_KEY=your_key"
        )
    return api_key


def _get_model() -> str:
    """Get the model name from environment or use default.

    Returns:
        The model name string.
    """
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")


def _parse_json_response(raw_response: str) -> dict:
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

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise JSONParseError(
            f"Failed to parse LLM response as JSON.\n"
            f"Error: {e}\n"
            f"Raw response:\n{raw_response}"
        )


def generate_commit_json(context_bundle: str) -> LLMResult:
    """Generate a commit message JSON from the git context bundle.

    Args:
        context_bundle: The formatted git context string from build_context_bundle().

    Returns:
        An LLMResult containing the validated CommitMessageJSON and token usage.

    Raises:
        MissingAPIKeyError: If ANTHROPIC_API_KEY is not set.
        JSONParseError: If the LLM response cannot be parsed.
        LLMError: For other LLM-related errors.
    """
    api_key = _get_api_key()
    model = _get_model()

    # Create the Anthropic client
    client = Anthropic(api_key=api_key)

    # Build the user prompt
    user_prompt = USER_PROMPT_TEMPLATE.format(context_bundle=context_bundle)

    try:
        # Call the Anthropic API
        message = client.messages.create(
            model=model,
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

        # Extract the text response
        raw_response = message.content[0].text

        # Extract token usage
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens

    except Exception as e:
        raise LLMError(f"Anthropic API call failed: {e}")

    # Parse the JSON response
    parsed = _parse_json_response(raw_response)

    # Validate with Pydantic model
    try:
        commit_json = CommitMessageJSON(**parsed)
    except Exception as e:
        raise JSONParseError(
            f"LLM response does not match expected schema.\n"
            f"Error: {e}\n"
            f"Parsed JSON: {parsed}"
        )

    return LLMResult(
        commit_json=commit_json,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

