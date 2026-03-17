"""Patch builder for hunknote compose module.

Contains:
- build_commit_patch: Build a patch file for a single commit
"""

from hunknote.compose.inventory import is_file_op_id
from hunknote.compose.models import FileDiff, HunkRef, PlannedCommit


def build_commit_patch(
    commit: PlannedCommit,
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
) -> str:
    """Build a patch file for a single commit.

    Handles both regular hunks and synthetic file-operation entries
    (``R_*``, ``D_*``).  For file-ops the stored diff-header
    lines are emitted directly — ``git apply --cached`` understands
    rename and deletion headers without content hunks.

    Args:
        commit: The planned commit
        inventory: Dictionary of hunk ID to HunkRef
        file_diffs: Original file diffs for header information

    Returns:
        Patch content as string
    """
    # Separate regular hunks from file-operation entries
    hunks_by_file: dict[str, list[HunkRef]] = {}
    file_op_lines: list[str] = []

    for hunk_id in commit.hunks:
        hunk = inventory.get(hunk_id)
        if not hunk:
            continue

        if is_file_op_id(hunk_id):
            # Synthetic entry — emit its stored diff header lines
            file_op_lines.extend(hunk.lines)
        else:
            if hunk.file_path not in hunks_by_file:
                hunks_by_file[hunk.file_path] = []
            hunks_by_file[hunk.file_path].append(hunk)

    # Build patch: file-ops first (renames before content changes),
    # then regular hunks preserving original file order.
    patch_lines: list[str] = list(file_op_lines)

    for file_diff in file_diffs:
        if file_diff.file_path not in hunks_by_file:
            continue

        # Add file header
        patch_lines.extend(file_diff.diff_header_lines)

        # Add hunks in original order
        file_hunks = hunks_by_file[file_diff.file_path]
        # Sort by original order (old_start)
        file_hunks.sort(key=lambda h: h.old_start)

        for hunk in file_hunks:
            patch_lines.extend(hunk.lines)

    # git apply requires the patch to end with a newline
    return "\n".join(patch_lines) + "\n"

