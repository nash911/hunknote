"""Git context collector functions."""

from pathlib import Path


def get_repo_root() -> Path:
    """Get the root directory of the current git repository."""
    raise NotImplementedError("Will be implemented in Milestone 1")


def get_branch() -> str:
    """Get the current branch name."""
    raise NotImplementedError("Will be implemented in Milestone 1")


def get_status() -> str:
    """Get git status output."""
    raise NotImplementedError("Will be implemented in Milestone 1")


def get_last_commits(n: int = 5) -> list[str]:
    """Get the last n commit subjects."""
    raise NotImplementedError("Will be implemented in Milestone 1")


def get_staged_diff(max_chars: int = 50000) -> str:
    """Get the staged diff, truncated if necessary."""
    raise NotImplementedError("Will be implemented in Milestone 1")


def build_context_bundle(max_chars: int = 50000) -> str:
    """Build the complete context bundle for the LLM."""
    raise NotImplementedError("Will be implemented in Milestone 1")
