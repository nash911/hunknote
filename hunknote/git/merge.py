"""Git merge state detection utilities.

Contains functions for detecting and inspecting merge state:
- is_merge_in_progress: Check if a merge is currently in progress
- get_merge_head: Get the commit hash being merged (MERGE_HEAD)
- get_merge_source_branch: Get the name of the branch being merged
- has_unresolved_conflicts: Check if there are unresolved merge conflicts
- get_conflicted_files: Get list of files with unresolved conflicts
- get_merge_state: Get comprehensive merge state information
"""

import re
from pathlib import Path

from hunknote.git.runner import _run_git_command, get_repo_root
from hunknote.git.exceptions import GitError


def is_merge_in_progress(repo_root: Path = None) -> bool:
    """Check if a merge is currently in progress.

    A merge is in progress when .git/MERGE_HEAD exists.

    Args:
        repo_root: The root directory of the git repository (optional).

    Returns:
        True if a merge is in progress, False otherwise.
    """
    if repo_root is None:
        try:
            repo_root = get_repo_root()
        except GitError:
            return False

    merge_head = repo_root / ".git" / "MERGE_HEAD"
    return merge_head.exists()


def get_merge_head(repo_root: Path = None) -> str | None:
    """Get the commit hash being merged (MERGE_HEAD).

    Args:
        repo_root: The root directory of the git repository (optional).

    Returns:
        The commit hash being merged, or None if no merge in progress.
    """
    if repo_root is None:
        try:
            repo_root = get_repo_root()
        except GitError:
            return None

    merge_head_file = repo_root / ".git" / "MERGE_HEAD"
    if merge_head_file.exists():
        return merge_head_file.read_text().strip()
    return None


def has_unresolved_conflicts(repo_root: Path = None) -> bool:
    """Check if there are unresolved merge conflicts.

    Unresolved conflicts are indicated by files with 'U' status in git status.

    Args:
        repo_root: The root directory of the git repository (optional).

    Returns:
        True if there are unresolved conflicts, False otherwise.
    """
    try:
        status = _run_git_command(["status", "--porcelain=v1"])
        for line in status.split("\n"):
            if len(line) >= 2:
                # Check for unmerged states: UU, AA, DD, AU, UA, DU, UD
                xy = line[:2]
                if "U" in xy or xy in ("AA", "DD"):
                    return True
        return False
    except GitError:
        return False


def get_conflicted_files() -> list[str]:
    """Get list of files with unresolved conflicts.

    Returns:
        List of file paths with conflicts.
    """
    conflicted = []
    try:
        status = _run_git_command(["status", "--porcelain=v1"])
        for line in status.split("\n"):
            if len(line) >= 3:
                xy = line[:2]
                # Check for unmerged states
                if "U" in xy or xy in ("AA", "DD"):
                    filename = line[3:]
                    conflicted.append(filename)
    except GitError:
        pass
    return conflicted


def get_merge_source_branch(repo_root: Path = None) -> str | None:
    """Get the name of the branch being merged.

    Attempts to determine the source branch from:
    1. .git/MERGE_MSG (contains "Merge branch 'branch-name'")
    2. git name-rev of MERGE_HEAD

    Args:
        repo_root: The root directory of the git repository (optional).

    Returns:
        The source branch name, or None if cannot be determined.
    """
    if repo_root is None:
        try:
            repo_root = get_repo_root()
        except GitError:
            return None

    # Try to get branch name from MERGE_MSG
    merge_msg_file = repo_root / ".git" / "MERGE_MSG"
    if merge_msg_file.exists():
        try:
            merge_msg = merge_msg_file.read_text()
            # Parse "Merge branch 'branch-name'" or "Merge branch 'branch-name' into target"
            match = re.search(r"Merge branch '([^']+)'", merge_msg)
            if match:
                return match.group(1)
            # Also try without quotes: "Merge branch branch-name"
            match = re.search(r"Merge branch (\S+)", merge_msg)
            if match:
                return match.group(1)
        except Exception:
            pass

    # Fallback: try to get branch name from MERGE_HEAD using name-rev
    merge_head = get_merge_head(repo_root)
    if merge_head:
        try:
            # git name-rev gives something like "abc123 remotes/origin/branch-name" or "abc123 branch-name"
            name_rev = _run_git_command(["name-rev", "--name-only", merge_head])
            if name_rev and name_rev != "undefined":
                # Clean up the name (remove ~N suffixes, remotes/origin/ prefix)
                branch = name_rev.split("~")[0].split("^")[0]
                if branch.startswith("remotes/origin/"):
                    branch = branch[len("remotes/origin/"):]
                return branch
        except GitError:
            pass

    return None


def get_merge_state(repo_root: Path = None) -> dict:
    """Get comprehensive merge state information.

    Args:
        repo_root: The root directory of the git repository (optional).

    Returns:
        Dictionary with merge state information:
        - is_merge: True if merge is in progress
        - merge_head: Commit hash being merged (or None)
        - source_branch: Name of branch being merged (or None)
        - has_conflicts: True if there are unresolved conflicts
        - conflicted_files: List of files with conflicts
        - state: 'normal', 'merge', or 'merge-conflict'
    """
    if repo_root is None:
        try:
            repo_root = get_repo_root()
        except GitError:
            return {
                "is_merge": False,
                "merge_head": None,
                "source_branch": None,
                "has_conflicts": False,
                "conflicted_files": [],
                "state": "normal",
            }

    is_merge = is_merge_in_progress(repo_root)
    merge_head = get_merge_head(repo_root) if is_merge else None
    source_branch = get_merge_source_branch(repo_root) if is_merge else None
    has_conflicts_flag = has_unresolved_conflicts(repo_root)
    conflicted_files = get_conflicted_files() if has_conflicts_flag else []

    # Determine state
    if has_conflicts_flag:
        state = "merge-conflict"
    elif is_merge:
        state = "merge"
    else:
        state = "normal"

    return {
        "is_merge": is_merge,
        "merge_head": merge_head,
        "source_branch": source_branch,
        "has_conflicts": has_conflicts_flag,
        "conflicted_files": conflicted_files,
        "state": state,
    }

