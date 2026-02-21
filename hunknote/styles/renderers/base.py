"""Base utilities for style renderers.

Contains common functions used across all style renderers:
- wrap_text: Wrap text to specified width
- sanitize_subject: Sanitize and truncate subject lines
- strip_type_prefix: Remove conventional commit type prefix from subject
"""

import textwrap

from hunknote.styles.constants import CONVENTIONAL_TYPES


def wrap_text(text: str, width: int = 72, initial_indent: str = "", subsequent_indent: str = "") -> str:
    """Wrap text to specified width.

    Args:
        text: Text to wrap.
        width: Maximum line width.
        initial_indent: Indent for first line.
        subsequent_indent: Indent for subsequent lines.

    Returns:
        Wrapped text.
    """
    return textwrap.fill(
        text,
        width=width,
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        break_long_words=False,
        break_on_hyphens=False,
    )


def strip_type_prefix(subject: str, types: list[str] | None = None) -> str:
    """Strip conventional commit type prefix from subject if present.

    Handles formats like:
    - "feat: Add feature" -> "Add feature"
    - "feat(scope): Add feature" -> "Add feature"
    - "fix: Fix bug" -> "Fix bug"

    Args:
        subject: The subject string that may contain a type prefix.
        types: List of valid types. Defaults to CONVENTIONAL_TYPES.

    Returns:
        Subject with type prefix removed, or original if no prefix found.
    """
    if types is None:
        types = CONVENTIONAL_TYPES

    subject = subject.strip()

    # Pattern: type: subject or type(scope): subject
    for commit_type in types:
        # Check for "type: " prefix
        prefix = f"{commit_type}: "
        if subject.lower().startswith(prefix.lower()):
            return subject[len(prefix):].strip()

        # Check for "type(scope): " prefix
        if subject.lower().startswith(f"{commit_type}("):
            # Find the closing ) and :
            paren_end = subject.find(")")
            if paren_end != -1 and len(subject) > paren_end + 1:
                if subject[paren_end + 1] == ":":
                    return subject[paren_end + 2:].strip()

    return subject


def sanitize_subject(subject: str, max_length: int = 72) -> str:
    """Sanitize and truncate the subject line.

    Args:
        subject: The raw subject string.
        max_length: Maximum allowed length.

    Returns:
        A sanitized single-line subject, truncated if necessary.
    """
    # Strip whitespace and take only the first line
    subject = subject.strip().split("\n")[0].strip()

    if len(subject) > max_length:
        # Truncate and add ellipsis
        subject = subject[: max_length - 3].rstrip() + "..."

    return subject

