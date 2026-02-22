"""Git branch and commit utilities.

Contains:
- get_branch: Get the current branch name
- get_last_commits: Get the last n commit subjects
"""

from hunknote.git.runner import _run_git_command
from hunknote.git.exceptions import GitError


def get_branch() -> str:
    """Get the current branch name.

    Returns:
        The current branch name, or 'HEAD' if in detached state.
    """
    branch = _run_git_command(["branch", "--show-current"])
    if not branch:
        # Detached HEAD state
        return "HEAD (detached)"
    return branch


def get_last_commits(n: int = 5) -> list[str]:
    """Get the last n commit subjects.

    Args:
        n: Number of commits to retrieve.

    Returns:
        List of commit subject lines.
    """
    try:
        output = _run_git_command(["log", f"-n{n}", "--pretty=%s"])
        if not output:
            return []
        return output.split("\n")
    except GitError:
        # No commits yet in the repo
        return []

