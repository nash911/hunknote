"""JSON parsing and validation utilities for LLM responses.

Contains functions for parsing and validating LLM responses:
- parse_json_response: Parse raw LLM response as JSON
- validate_commit_json: Validate parsed JSON against ExtendedCommitJSON schema
- _normalize_commit_json: Normalize different style formats to common schema
"""

import json

from hunknote.styles import ExtendedCommitJSON
from hunknote.llm.exceptions import JSONParseError


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


def validate_commit_json(parsed: dict, raw_response: str) -> ExtendedCommitJSON:
    """Validate parsed JSON against the ExtendedCommitJSON schema.

    This validates the LLM response and converts it to ExtendedCommitJSON,
    which supports all style formats (default, blueprint, conventional, ticket, kernel).

    Args:
        parsed: The parsed JSON dictionary.
        raw_response: The original raw response (for error messages).

    Returns:
        A validated ExtendedCommitJSON object.

    Raises:
        JSONParseError: If validation fails.
    """
    try:
        # Normalize the parsed data to handle different style formats
        normalized = _normalize_commit_json(parsed)
        return ExtendedCommitJSON(**normalized)
    except Exception as e:
        raise JSONParseError(
            f"LLM response does not match expected schema.\n"
            f"Error: {e}\n"
            f"Parsed JSON: {parsed}"
        )


def _normalize_commit_json(parsed: dict) -> dict:
    """Normalize parsed JSON to handle different style formats.

    Different styles use different field names:
    - default: title, body_bullets
    - blueprint: type, scope, title, summary, sections
    - conventional: type, scope, subject, body_bullets, breaking_change, footers
    - ticket: ticket, subject, scope, body_bullets
    - kernel: subsystem (mapped to scope), subject, body_bullets

    Args:
        parsed: The raw parsed JSON dictionary.

    Returns:
        Normalized dictionary compatible with ExtendedCommitJSON.
    """
    result = dict(parsed)  # Copy to avoid modifying original

    # Handle kernel style: subsystem -> scope
    if "subsystem" in result and "scope" not in result:
        result["scope"] = result.pop("subsystem")

    # Ensure we have either title or subject
    # If only subject is provided, also set title for backward compatibility
    if "subject" in result and "title" not in result:
        result["title"] = result["subject"]
    elif "title" in result and "subject" not in result:
        result["subject"] = result["title"]

    # Ensure body_bullets exists (may be empty for blueprint style)
    if "body_bullets" not in result:
        result["body_bullets"] = []

    # Handle sections for blueprint style - convert dicts to BlueprintSection
    if "sections" in result:
        sections = []
        for section in result["sections"]:
            if isinstance(section, dict):
                sections.append(section)
            else:
                sections.append(section)
        result["sections"] = sections

    return result

