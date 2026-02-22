"""Hunk inventory utilities for hunknote compose module.

Contains functions for building and formatting hunk inventories:
- build_hunk_inventory: Build a mapping of hunk IDs to HunkRef objects
- format_inventory_for_llm: Format the hunk inventory for inclusion in LLM prompt
"""

from hunknote.compose.models import FileDiff, HunkRef


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


def format_inventory_for_llm(
    file_diffs: list[FileDiff], max_snippet_lines: int = 5
) -> str:
    """Format the hunk inventory for inclusion in LLM prompt.

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

    return "\n".join(lines)

