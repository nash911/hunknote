"""LLM-related exception classes.

Contains all exception classes for LLM operations:
- LLMError: Base exception for LLM-related errors
- MissingAPIKeyError: Raised when API key is not set
- JSONParseError: Raised when LLM response cannot be parsed
"""


class LLMError(Exception):
    """Base exception for LLM-related errors."""

    pass


class MissingAPIKeyError(LLMError):
    """Raised when the required API key is not set."""

    pass


class JSONParseError(LLMError):
    """Raised when the LLM response cannot be parsed as valid JSON."""

    pass

