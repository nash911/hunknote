"""Patch builder for hunknote compose module.

Contains:
- build_commit_patch: Build a patch file for a single commit
"""

from hunknote.compose.models import FileDiff, HunkRef, PlannedCommit


def build_commit_patch(
    commit: PlannedCommit,
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
) -> str:
    """Build a patch file for a single commit.

    Args:
        commit: The planned commit
        inventory: Dictionary of hunk ID to HunkRef
        file_diffs: Original file diffs for header information

    Returns:
        Patch content as string
    """
    # Group hunks by file
    hunks_by_file: dict[str, list[HunkRef]] = {}
    for hunk_id in commit.hunks:
        hunk = inventory.get(hunk_id)
        if hunk:
            if hunk.file_path not in hunks_by_file:
                hunks_by_file[hunk.file_path] = []
            hunks_by_file[hunk.file_path].append(hunk)

    # Build patch preserving original file order
    patch_lines: list[str] = []

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

