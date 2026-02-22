"""Git-related exception classes.

Contains all exception classes for Git operations:
- GitError: Base exception for git-related errors
- NoStagedChangesError: Raised when there are no staged changes
"""


class GitError(Exception):
    """Custom exception for git-related errors."""

    pass


class NoStagedChangesError(GitError):
    """Raised when there are no staged changes."""

    pass

