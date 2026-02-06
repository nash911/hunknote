"""Commit message formatting and rendering."""

from pydantic import BaseModel, field_validator


class CommitMessageJSON(BaseModel):
    """Pydantic model for structured commit message data.

    Attributes:
        title: The commit message title (imperative mood, max 72 chars recommended).
        body_bullets: List of bullet points describing changes (2-7 items recommended).
    """

    title: str
    body_bullets: list[str]

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, v: str) -> str:
        """Ensure title is not empty."""
        if not v or not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip()

    @field_validator("body_bullets")
    @classmethod
    def bullets_must_not_be_empty(cls, v: list[str]) -> list[str]:
        """Ensure body_bullets list is not empty and items are not empty."""
        if not v:
            raise ValueError("body_bullets cannot be empty")
        # Filter out empty bullets and strip whitespace
        cleaned = [bullet.strip() for bullet in v if bullet and bullet.strip()]
        if not cleaned:
            raise ValueError("body_bullets must contain at least one non-empty item")
        return cleaned


def sanitize_title(title: str, max_length: int = 72) -> str:
    """Sanitize and truncate the commit title to max_length characters.

    Args:
        title: The raw title string.
        max_length: Maximum allowed length (default 72 for git best practices).

    Returns:
        A sanitized single-line title, truncated if necessary.
    """
    # Strip whitespace and take only the first line
    title = title.strip().split("\n")[0].strip()

    if len(title) > max_length:
        # Truncate and add ellipsis
        title = title[: max_length - 3].rstrip() + "..."

    return title


def render_commit_message(data: CommitMessageJSON) -> str:
    """Render a CommitMessageJSON into a formatted commit message string.

    Args:
        data: The structured commit message data.

    Returns:
        A formatted commit message string with title, blank line, and bullet points.

    Example output:
        Add user authentication feature

        - Implement login and logout endpoints
        - Add session management middleware
        - Create user model with password hashing
    """
    title = sanitize_title(data.title)

    # Format bullets with proper prefix and stripping
    bullets = "\n".join(f"- {bullet.strip()}" for bullet in data.body_bullets)

    return f"{title}\n\n{bullets}"
