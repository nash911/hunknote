"""Git command runner and repository utilities.

Contains:
- _run_git_command: Run a git command and return its output
- get_repo_root: Get the root directory of the current git repository
"""

import subprocess
from pathlib import Path

from hunknote.git.exceptions import GitError


def _run_git_command(args: list[str]) -> str:
    """Run a git command and return its output.

    Args:
        args: List of arguments to pass to git.

    Returns:
        The stdout of the git command.

    Raises:
        GitError: If the command fails.
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise GitError(f"Git command failed: git {' '.join(args)}\n{e.stderr.strip()}")
    except FileNotFoundError:
        raise GitError("Git is not installed or not in PATH.")


def get_repo_root() -> Path:
    """Get the root directory of the current git repository.

    Returns:
        Path to the repository root.

    Raises:
        GitError: If not in a git repository.
    """
    try:
        root = _run_git_command(["rev-parse", "--show-toplevel"])
        return Path(root)
    except GitError:
        raise GitError("Not in a git repository. Please run this command from within a git repo.")

