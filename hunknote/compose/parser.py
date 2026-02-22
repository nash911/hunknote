"""Diff parser for hunknote compose module.

Contains functions for parsing unified diff output:
- parse_unified_diff: Parse unified diff output from git diff
- _parse_file_block: Parse a single file block from the diff
- _parse_hunks: Parse hunks from the hunk portion of a file diff
- _create_hunk_ref: Create a HunkRef from parsed hunk data
"""

import hashlib
import re
from typing import Optional

from hunknote.compose.models import FileDiff, HunkRef


def parse_unified_diff(diff_output: str) -> tuple[list[FileDiff], list[str]]:
    """Parse unified diff output from 'git diff HEAD --patch'.

    Args:
        diff_output: Raw output from git diff

    Returns:
        Tuple of (list of FileDiff objects, list of warning messages)
    """
    files: list[FileDiff] = []
    warnings: list[str] = []
    hunk_counter = 0

    if not diff_output.strip():
        return files, warnings

    # Split by file blocks
    # Each file starts with 'diff --git a/... b/...'
    file_blocks = re.split(r"(?=^diff --git )", diff_output, flags=re.MULTILINE)

    for block in file_blocks:
        if not block.strip():
            continue

        if not block.startswith("diff --git"):
            continue

        lines = block.split("\n")
        file_diff = _parse_file_block(lines, hunk_counter, warnings)
        if file_diff:
            hunk_counter += len(file_diff.hunks)
            files.append(file_diff)

    return files, warnings


def _parse_file_block(
    lines: list[str], hunk_start_id: int, warnings: list[str]
) -> Optional[FileDiff]:
    """Parse a single file block from the diff.

    Args:
        lines: Lines of the file block
        hunk_start_id: Starting ID for hunks in this file
        warnings: List to append warnings to

    Returns:
        FileDiff object or None if binary/invalid
    """
    if not lines or not lines[0].startswith("diff --git"):
        return None

    # Extract file path from diff --git line
    # Format: diff --git a/path b/path
    match = re.match(r"diff --git a/(.*) b/(.*)", lines[0])
    if not match:
        return None

    old_path = match.group(1)
    new_path = match.group(2)
    file_path = new_path

    # Collect header lines until first @@ or end
    header_lines = []
    hunk_start_idx = 0
    is_binary = False
    is_new_file = False
    is_deleted_file = False
    is_renamed = old_path != new_path

    for i, line in enumerate(lines):
        if line.startswith("@@"):
            hunk_start_idx = i
            break
        header_lines.append(line)

        # Check for binary
        if "GIT binary patch" in line or "Binary files" in line:
            is_binary = True
            warnings.append(f"Binary file skipped: {file_path}")
            return FileDiff(
                file_path=file_path,
                diff_header_lines=header_lines,
                hunks=[],
                is_binary=True,
                old_path=old_path if is_renamed else None,
            )

        # Check for new/deleted file
        if line.startswith("new file mode"):
            is_new_file = True
        if line.startswith("deleted file mode"):
            is_deleted_file = True
    else:
        # No hunks found (could be mode change only)
        return FileDiff(
            file_path=file_path,
            diff_header_lines=header_lines,
            hunks=[],
            is_new_file=is_new_file,
            is_deleted_file=is_deleted_file,
            is_renamed=is_renamed,
            old_path=old_path if is_renamed else None,
        )

    # Parse hunks
    hunks = _parse_hunks(lines[hunk_start_idx:], file_path, hunk_start_id)

    return FileDiff(
        file_path=file_path,
        diff_header_lines=header_lines,
        hunks=hunks,
        is_binary=is_binary,
        is_new_file=is_new_file,
        is_deleted_file=is_deleted_file,
        is_renamed=is_renamed,
        old_path=old_path if is_renamed else None,
    )


def _parse_hunks(lines: list[str], file_path: str, start_id: int) -> list[HunkRef]:
    """Parse hunks from the hunk portion of a file diff.

    Args:
        lines: Lines starting from first @@
        file_path: Path to the file
        start_id: Starting ID number for hunks

    Returns:
        List of HunkRef objects
    """
    hunks: list[HunkRef] = []
    current_hunk_lines: list[str] = []
    current_header: Optional[str] = None
    hunk_id = start_id

    for line in lines:
        if line.startswith("@@"):
            # Save previous hunk if exists
            if current_header is not None:
                hunk = _create_hunk_ref(
                    hunk_id, file_path, current_header, current_hunk_lines
                )
                if hunk:
                    hunks.append(hunk)
                    hunk_id += 1

            # Start new hunk
            current_header = line
            current_hunk_lines = [line]
        elif current_header is not None:
            # Continue current hunk
            current_hunk_lines.append(line)

    # Save last hunk
    if current_header is not None:
        hunk = _create_hunk_ref(hunk_id, file_path, current_header, current_hunk_lines)
        if hunk:
            hunks.append(hunk)

    return hunks


def _create_hunk_ref(
    hunk_id: int, file_path: str, header: str, lines: list[str]
) -> Optional[HunkRef]:
    """Create a HunkRef from parsed hunk data.

    Args:
        hunk_id: Numeric ID for the hunk
        file_path: Path to the file
        header: The @@ header line
        lines: All lines of the hunk including header

    Returns:
        HunkRef object or None if invalid
    """
    # Parse @@ -a,b +c,d @@ header
    # Format: @@ -old_start,old_len +new_start,new_len @@ optional context
    match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
    if not match:
        return None

    old_start = int(match.group(1))
    old_len = int(match.group(2)) if match.group(2) else 1
    new_start = int(match.group(3))
    new_len = int(match.group(4)) if match.group(4) else 1

    # Generate stable ID with hash suffix for uniqueness
    content_hash = hashlib.md5(
        "".join(lines).encode(), usedforsecurity=False
    ).hexdigest()[:6]
    stable_id = f"H{hunk_id + 1}_{content_hash}"

    return HunkRef(
        id=stable_id,
        file_path=file_path,
        header=header,
        old_start=old_start,
        old_len=old_len,
        new_start=new_start,
        new_len=new_len,
        lines=lines,
    )

