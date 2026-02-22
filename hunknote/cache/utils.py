"""Cache utility functions for hunknote.

Contains utility functions for caching:
- compute_context_hash: Compute SHA256 hash of context bundle
- extract_staged_files: Extract list of staged files from git status
- get_diff_preview: Get truncated diff preview
"""

import hashlib


def compute_context_hash(context_bundle: str) -> str:
    """Compute SHA256 hash of the context bundle.

    Args:
        context_bundle: The full git context string.

    Returns:
        SHA256 hex digest of the context.
    """
    return hashlib.sha256(context_bundle.encode()).hexdigest()


def extract_staged_files(status_output: str) -> list[str]:
    """Extract list of staged files from git status output.

    Args:
        status_output: Output from git status --porcelain=v1 -b

    Returns:
        List of staged file paths.
    """
    staged_files = []
    for line in status_output.split("\n"):
        if not line or line.startswith("##"):
            continue
        # Porcelain format: XY filename
        # X = index status, Y = worktree status
        # If X is not space or ?, file is staged
        if len(line) >= 3:
            index_status = line[0]
            if index_status not in (" ", "?"):
                # Handle renamed files: R  old -> new
                filename = line[3:]
                if " -> " in filename:
                    filename = filename.split(" -> ")[1]
                staged_files.append(filename)
    return staged_files


def get_diff_preview(diff: str, max_chars: int = 500) -> str:
    """Get a preview of the diff, truncated if necessary.

    Args:
        diff: The full staged diff.
        max_chars: Maximum characters for the preview.

    Returns:
        Truncated diff preview.
    """
    if len(diff) <= max_chars:
        return diff
    return diff[:max_chars] + "\n...[truncated]"

