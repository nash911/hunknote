"""Residual commit builder for hunknote compose module.

After the LLM-generated compose plan assigns hunks to commits,
some staged files may remain uncommitted:

  - Binary files (images, compiled assets, lock files like poetry.lock)
  - Empty new files (e.g., __init__.py, .gitkeep)
  - Mode-change-only files (chmod but no content diff)
  - Renamed files with no content changes

This module detects those residual files and creates a final
housekeeping commit so nothing staged is left behind.
"""

import logging
from typing import Optional

from hunknote.compose.models import ComposePlan, FileDiff, PlannedCommit

logger = logging.getLogger(__name__)


def collect_residual_files(
    file_diffs: list[FileDiff],
    plan: ComposePlan,
    inventory: dict,
) -> list[FileDiff]:
    """Identify staged files not covered by any commit in the plan.

    A file is "covered" if at least one of its hunks appears in a
    planned commit.  Files with no hunks (binary, empty, mode-change)
    are never covered.

    Args:
        file_diffs: All parsed file diffs (including binary/empty).
        plan: The generated compose plan.
        inventory: Hunk inventory (hunk_id → HunkRef).

    Returns:
        List of FileDiff objects for residual (uncovered) files.
    """
    # Collect all hunk IDs assigned to any commit
    assigned_hunk_ids: set[str] = set()
    for commit in plan.commits:
        assigned_hunk_ids.update(commit.hunks)

    # Collect file paths that have at least one assigned hunk
    covered_files: set[str] = set()
    for hid in assigned_hunk_ids:
        hunk = inventory.get(hid)
        if hunk:
            covered_files.add(hunk.file_path)

    # Residual = files not covered by any commit
    residual: list[FileDiff] = []
    for fd in file_diffs:
        if fd.file_path not in covered_files:
            residual.append(fd)

    return residual


def build_residual_commit(
    file_diffs: list[FileDiff],
    plan: ComposePlan,
    inventory: dict,
    max_commits: int = 8,
) -> Optional[PlannedCommit]:
    """Create a residual commit for files not covered by the plan.

    If there are uncovered files (binary, empty, mode-change-only),
    returns a PlannedCommit with type "chore" that captures them.
    The commit ID is set to C{N+1} where N is the number of existing
    commits, even if that exceeds max_commits.

    Args:
        file_diffs: All parsed file diffs.
        plan: The generated compose plan.
        inventory: Hunk inventory.
        max_commits: Max commits setting (residual may exceed by 1).

    Returns:
        A PlannedCommit for residual files, or None if nothing is left over.
    """
    residual = collect_residual_files(file_diffs, plan, inventory)

    if not residual:
        return None

    next_id = len(plan.commits) + 1

    # Categorize residual files for the commit message
    binary_files = [fd for fd in residual if fd.is_binary]
    empty_new = [fd for fd in residual if fd.is_new_file and not fd.hunks and not fd.is_binary]
    mode_change = [fd for fd in residual if not fd.is_binary and not fd.is_new_file
                   and not fd.is_deleted_file and not fd.hunks]
    deleted = [fd for fd in residual if fd.is_deleted_file and not fd.hunks]
    renamed = [fd for fd in residual if fd.is_renamed and not fd.hunks and not fd.is_binary]

    # Build descriptive bullets
    bullets: list[str] = []
    if binary_files:
        names = ", ".join(fd.file_path for fd in binary_files[:5])
        suffix = f" (+{len(binary_files) - 5} more)" if len(binary_files) > 5 else ""
        bullets.append(f"Include binary files: {names}{suffix}")
    if empty_new:
        names = ", ".join(fd.file_path for fd in empty_new[:5])
        suffix = f" (+{len(empty_new) - 5} more)" if len(empty_new) > 5 else ""
        bullets.append(f"Add empty files: {names}{suffix}")
    if deleted:
        names = ", ".join(fd.file_path for fd in deleted[:5])
        suffix = f" (+{len(deleted) - 5} more)" if len(deleted) > 5 else ""
        bullets.append(f"Remove files: {names}{suffix}")
    if renamed:
        for fd in renamed[:3]:
            bullets.append(f"Rename {fd.old_path} → {fd.file_path}")
    if mode_change:
        names = ", ".join(fd.file_path for fd in mode_change[:5])
        bullets.append(f"Update file modes: {names}")

    # Build title
    parts = []
    if binary_files:
        parts.append("binary assets")
    if empty_new:
        parts.append("empty files")
    if deleted:
        parts.append("file deletions")
    if renamed:
        parts.append("file renames")
    if mode_change:
        parts.append("mode changes")
    title = "Include " + ", ".join(parts) if parts else "Include residual files"

    # Truncate title to keep within 72-char header budget
    # "chore: " = 7 chars overhead
    max_title = 72 - len("chore: ")
    if len(title) > max_title:
        title = title[:max_title - 3] + "..."

    # The commit has no hunk IDs — the files will be staged via git add
    commit = PlannedCommit(
        id=f"C{next_id}",
        type="chore",
        title=title,
        bullets=bullets,
        hunks=[],  # No hunks — files are staged directly
    )

    logger.info(
        "Residual commit C%d: %d file(s) — %s",
        next_id,
        len(residual),
        title,
    )

    return commit


def append_residual_to_plan(
    plan: ComposePlan,
    file_diffs: list[FileDiff],
    inventory: dict,
    max_commits: int = 8,
) -> list[FileDiff]:
    """Append a residual commit to the plan if needed.

    Modifies the plan in-place by appending the residual commit.

    Args:
        plan: The compose plan (modified in place).
        file_diffs: All parsed file diffs.
        inventory: Hunk inventory.
        max_commits: Max commits setting.

    Returns:
        List of residual FileDiff objects (empty if none).
    """
    residual_files = collect_residual_files(file_diffs, plan, inventory)
    if not residual_files:
        return []

    residual_commit = build_residual_commit(file_diffs, plan, inventory, max_commits)
    if residual_commit is None:
        return []

    plan.commits.append(residual_commit)
    return residual_files


