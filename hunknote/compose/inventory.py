"""Hunk inventory utilities for hunknote compose module.

Contains functions for building and formatting hunk inventories:
- build_hunk_inventory: Build a mapping of hunk IDs to HunkRef objects
- format_inventory_for_llm: Format the hunk inventory for inclusion in LLM prompt
"""

import hashlib

from hunknote.compose.models import FileDiff, HunkRef

# Prefixes for synthetic hunk IDs representing file-level operations.
# These are distinct from regular hunk IDs (H<n>_<hash>) so every
# downstream component can identify them.
RENAME_PREFIX = "RENAME_"
DELETE_PREFIX = "DELETE_"


def build_hunk_inventory(file_diffs: list[FileDiff]) -> dict[str, HunkRef]:
    """Build a mapping of hunk IDs to HunkRef objects.

    Args:
        file_diffs: List of FileDiff objects

    Returns:
        Dictionary mapping hunk ID to HunkRef
    """
    inventory: dict[str, HunkRef] = {}
    for file_diff in file_diffs:
        for hunk in file_diff.hunks:
            inventory[hunk.id] = hunk
    return inventory


def build_file_ops_inventory(file_diffs: list[FileDiff]) -> dict[str, HunkRef]:
    """Create synthetic HunkRef entries for file-level operations.

    Pure renames (``git mv``, 100 % similarity, no content hunks) and
    hunkless deletions (``git rm`` of empty files) are invisible to the
    regular hunk inventory.  This function creates *synthetic* HunkRef
    entries for them so they can participate in the dependency graph,
    clustering, ordering, and patch-building phases.

    Synthetic IDs use distinct prefixes:
      - ``RENAME_<n>_<hash>`` for renames
      - ``DELETE_<n>_<hash>`` for hunkless deletions

    The ``lines`` field of each synthetic HunkRef stores the raw diff
    header lines so ``build_commit_patch`` can emit them.

    Args:
        file_diffs: All parsed file diffs.

    Returns:
        Dictionary mapping synthetic hunk ID to HunkRef.
    """
    ops: dict[str, HunkRef] = {}
    rename_idx = 1
    delete_idx = 1

    for fd in file_diffs:
        if fd.is_renamed and not fd.hunks and fd.old_path:
            short_hash = hashlib.sha256(fd.file_path.encode()).hexdigest()[:6]
            hid = f"{RENAME_PREFIX}{rename_idx}_{short_hash}"
            ops[hid] = HunkRef(
                id=hid,
                file_path=fd.file_path,
                header=f"rename {fd.old_path} → {fd.file_path}",
                old_start=0,
                old_len=0,
                new_start=0,
                new_len=0,
                # Store the diff header so build_commit_patch can emit it.
                lines=list(fd.diff_header_lines),
            )
            rename_idx += 1

        elif fd.is_deleted_file and not fd.hunks:
            short_hash = hashlib.sha256(fd.file_path.encode()).hexdigest()[:6]
            hid = f"{DELETE_PREFIX}{delete_idx}_{short_hash}"
            ops[hid] = HunkRef(
                id=hid,
                file_path=fd.file_path,
                header=f"delete {fd.file_path}",
                old_start=0,
                old_len=0,
                new_start=0,
                new_len=0,
                lines=list(fd.diff_header_lines),
            )
            delete_idx += 1

    return ops


def is_file_op_id(hunk_id: str) -> bool:
    """Return True if *hunk_id* is a synthetic rename/delete entry."""
    return hunk_id.startswith(RENAME_PREFIX) or hunk_id.startswith(DELETE_PREFIX)


def format_inventory_for_llm(
    file_diffs: list[FileDiff], max_snippet_lines: int = 5
) -> str:
    """Format the hunk inventory for inclusion in LLM prompt.

    Includes both regular hunks and synthetic file-operation entries
    (renames, hunkless deletions).

    Args:
        file_diffs: List of FileDiff objects
        max_snippet_lines: Maximum lines to show per hunk snippet

    Returns:
        Formatted string for LLM prompt
    """
    lines = ["[HUNK INVENTORY]"]

    for file_diff in file_diffs:
        if file_diff.is_binary:
            continue

        # Skip hunkless renames/deletions here — they are shown in the
        # [FILE OPERATIONS] section below.
        if not file_diff.hunks and (file_diff.is_renamed or file_diff.is_deleted_file):
            continue

        lines.append(f"\nFile: {file_diff.file_path}")
        if file_diff.is_new_file:
            lines.append("  (new file)")
        elif file_diff.is_deleted_file:
            lines.append("  (deleted file)")
        elif file_diff.is_renamed:
            lines.append(f"  (renamed from {file_diff.old_path})")

        for hunk in file_diff.hunks:
            lines.append(f"\n  Hunk {hunk.id}:")
            lines.append(f"    {hunk.header}")
            snippet = hunk.snippet(max_snippet_lines)
            for snippet_line in snippet.split("\n"):
                lines.append(f"    {snippet_line}")

    # Append file-operation section for pure renames / hunkless deletions
    file_ops = build_file_ops_inventory(file_diffs)
    if file_ops:
        lines.append("")
        lines.append("[FILE OPERATIONS]")
        lines.append(
            "The following file-level operations have no content hunks but "
            "MUST be assigned to a commit — typically the same commit as "
            "hunks that reference the affected paths."
        )
        for hid, href in file_ops.items():
            lines.append(f"\n  {hid}: {href.header}")

    return "\n".join(lines)

