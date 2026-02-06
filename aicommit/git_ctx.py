"""Git context collector functions."""

import subprocess
from pathlib import Path


class GitError(Exception):
    """Custom exception for git-related errors."""
    pass


class NoStagedChangesError(GitError):
    """Raised when there are no staged changes."""
    pass


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


def get_status() -> str:
    """Get git status output in porcelain format.

    Returns:
        The git status output.
    """
    return _run_git_command(["status", "--porcelain=v1", "-b"])


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


def get_staged_diff(max_chars: int = 50000) -> str:
    """Get the staged diff, truncated if necessary.

    Args:
        max_chars: Maximum characters for the diff output.

    Returns:
        The staged diff string.

    Raises:
        NoStagedChangesError: If there are no staged changes.
    """
    diff = _run_git_command(["diff", "--staged"])

    if not diff:
        raise NoStagedChangesError(
            "No staged changes found. Stage your changes first with: git add <files>"
        )

    if len(diff) > max_chars:
        diff = diff[:max_chars] + "\n...[truncated]\n"

    return diff


def build_context_bundle(max_chars: int = 50000) -> str:
    """Build the complete context bundle for the LLM.

    Args:
        max_chars: Maximum characters for the staged diff.

    Returns:
        A formatted string containing all git context sections.

    Raises:
        NoStagedChangesError: If there are no staged changes.
        GitError: If not in a git repository.
    """
    # Get all context pieces
    branch = get_branch()
    status = get_status()
    last_commits = get_last_commits(n=5)
    staged_diff = get_staged_diff(max_chars=max_chars)

    # Format commits as bullet list
    commits_formatted = "\n".join(f"- {commit}" for commit in last_commits) if last_commits else "- (no commits yet)"

    # Build the context bundle
    bundle = f"""[BRANCH]
{branch}

[STATUS]
{status}

[LAST_5_COMMITS]
{commits_formatted}

[STAGED_DIFF]
{staged_diff}"""

    return bundle
