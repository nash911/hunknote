"""LLM integration for generating commit messages."""

from aicommit.formatters import CommitMessageJSON


def generate_commit_json(context_bundle: str) -> CommitMessageJSON:
    """Generate a commit message JSON from the git context bundle."""
    raise NotImplementedError("Will be implemented in Milestone 3")
