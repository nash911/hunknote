"""Git diff utilities.

Contains:
- get_staged_diff: Get the staged diff, excluding ignored files
- _should_exclude_file: Check if a file should be excluded based on patterns
- DEFAULT_DIFF_EXCLUDE_PATTERNS: Default patterns for files to exclude from diff
"""

import fnmatch
from pathlib import Path

from hunknote.git.runner import _run_git_command, get_repo_root
from hunknote.git.exceptions import GitError, NoStagedChangesError
from hunknote.git.status import _get_staged_files_list
from hunknote.user_config import get_ignore_patterns


# Default files to exclude from the staged diff sent to LLM
# These are typically auto-generated and don't need commit message descriptions
# Note: This list is used as fallback; actual patterns come from .hunknote/config.yaml
DEFAULT_DIFF_EXCLUDE_PATTERNS = [
    "poetry.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
]


def _should_exclude_file(filename: str, patterns: list[str]) -> bool:
    """Check if a file should be excluded based on patterns.

    Supports glob patterns like *.lock, build/*, etc.

    Args:
        filename: The file path to check.
        patterns: List of patterns to match against.

    Returns:
        True if the file should be excluded.
    """
    for pattern in patterns:
        # Handle exact matches
        if filename == pattern:
            return True
        # Handle glob patterns
        if fnmatch.fnmatch(filename, pattern):
            return True
        # Handle patterns that might match the basename
        if fnmatch.fnmatch(Path(filename).name, pattern):
            return True
    return False


def get_staged_diff(max_chars: int = 50000, repo_root: Path = None) -> str:
    """Get the staged diff, excluding ignored files and truncating if necessary.

    Files matching patterns in .hunknote/config.yaml ignore list are excluded
    because they are typically auto-generated and inflate the diff without
    adding useful context for commit message generation.

    Args:
        max_chars: Maximum characters for the diff output.
        repo_root: The root directory of the git repository (optional).

    Returns:
        The staged diff string.

    Raises:
        NoStagedChangesError: If there are no staged changes.
    """
    # Get ignore patterns from config (or use defaults if repo_root not provided)
    if repo_root:
        ignore_patterns = get_ignore_patterns(repo_root)
    else:
        # Try to get repo root, fall back to defaults if not in a repo
        try:
            repo_root = get_repo_root()
            ignore_patterns = get_ignore_patterns(repo_root)
        except GitError:
            ignore_patterns = DEFAULT_DIFF_EXCLUDE_PATTERNS

    # Get list of staged files
    staged_files = _get_staged_files_list()

    if not staged_files:
        raise NoStagedChangesError(
            "No staged changes found. Stage your changes first with: git add <files>"
        )

    # Filter out files matching ignore patterns
    files_to_include = [
        f for f in staged_files
        if not _should_exclude_file(f, ignore_patterns)
    ]

    if not files_to_include:
        # All staged files are in the ignore list
        return "(Only ignored files staged - no code changes to describe)"

    # Build git diff command with only included files
    diff = _run_git_command(["diff", "--staged", "--"] + files_to_include)

    if not diff:
        # This shouldn't happen if files_to_include is not empty, but handle it
        raise NoStagedChangesError(
            "No staged changes found. Stage your changes first with: git add <files>"
        )

    if len(diff) > max_chars:
        diff = diff[:max_chars] + "\n...[truncated]\n"

    return diff

