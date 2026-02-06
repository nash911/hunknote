"""Commit message formatting and rendering."""

from pydantic import BaseModel


class CommitMessageJSON(BaseModel):
    """Pydantic model for structured commit message data."""

    title: str
    body_bullets: list[str]


def sanitize_title(title: str, max_length: int = 72) -> str:
    """Sanitize and truncate the commit title to max_length characters."""
    title = title.strip().split("\n")[0]
    if len(title) > max_length:
        title = title[: max_length - 3] + "..."
    return title


def render_commit_message(data: CommitMessageJSON) -> str:
    """Render a CommitMessageJSON into a formatted commit message string."""
    title = sanitize_title(data.title)
    bullets = "\n".join(f"- {bullet.strip()}" for bullet in data.body_bullets)
    return f"{title}\n\n{bullets}"
