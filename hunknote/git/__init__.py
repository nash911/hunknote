"""Git context collector module for hunknote.

This package provides modular git context collection with:
- exceptions: GitError, NoStagedChangesError
- runner: _run_git_command, get_repo_root
- branch: get_branch, get_last_commits
- merge: is_merge_in_progress, get_merge_head, get_merge_source_branch,
         has_unresolved_conflicts, get_conflicted_files, get_merge_state
- status: get_status, get_staged_status, _get_staged_files_list
- diff: get_staged_diff, _should_exclude_file, DEFAULT_DIFF_EXCLUDE_PATTERNS
- context: build_context_bundle, _parse_file_changes, _format_merge_state
"""

# Exceptions
from hunknote.git.exceptions import (
    GitError,
    NoStagedChangesError,
)

# Runner utilities
from hunknote.git.runner import (
    _run_git_command,
    get_repo_root,
)

# Branch utilities
from hunknote.git.branch import (
    get_branch,
    get_last_commits,
)

# Merge state utilities
from hunknote.git.merge import (
    is_merge_in_progress,
    get_merge_head,
    get_merge_source_branch,
    has_unresolved_conflicts,
    get_conflicted_files,
    get_merge_state,
)

# Status utilities
from hunknote.git.status import (
    get_status,
    get_staged_status,
    _get_staged_files_list,
)

# Diff utilities
from hunknote.git.diff import (
    get_staged_diff,
    _should_exclude_file,
    DEFAULT_DIFF_EXCLUDE_PATTERNS,
)

# Context bundle builder
from hunknote.git.context import (
    build_context_bundle,
    _parse_file_changes,
    _format_merge_state,
)


__all__ = [
    # Exceptions
    "GitError",
    "NoStagedChangesError",
    # Runner
    "_run_git_command",
    "get_repo_root",
    # Branch
    "get_branch",
    "get_last_commits",
    # Merge
    "is_merge_in_progress",
    "get_merge_head",
    "get_merge_source_branch",
    "has_unresolved_conflicts",
    "get_conflicted_files",
    "get_merge_state",
    # Status
    "get_status",
    "get_staged_status",
    "_get_staged_files_list",
    # Diff
    "get_staged_diff",
    "_should_exclude_file",
    "DEFAULT_DIFF_EXCLUDE_PATTERNS",
    # Context
    "build_context_bundle",
    "_parse_file_changes",
    "_format_merge_state",
]

