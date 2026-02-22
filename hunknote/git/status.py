"""Git status utilities.

Contains:
- get_status: Get git status output in porcelain format
- get_staged_status: Get git status filtered to only show staged files
- _get_staged_files_list: Get list of staged file paths
"""

from hunknote.git.runner import _run_git_command


def get_status() -> str:
    """Get git status output in porcelain format.

    Returns:
        The git status output.
    """
    return _run_git_command(["status", "--porcelain=v1", "-b"])


def get_staged_status() -> str:
    """Get git status filtered to only show staged files.

    The porcelain format uses two columns:
    - First column: staged status (index)
    - Second column: worktree status

    We only include lines where the first column indicates a staged change.

    Returns:
        Filtered status showing only staged files.
    """
    full_status = _run_git_command(["status", "--porcelain=v1", "-b"])
    lines = full_status.split("\n")
    filtered_lines = []

    for line in lines:
        if not line:
            continue
        # Keep the branch line (starts with ##)
        if line.startswith("##"):
            filtered_lines.append(line)
            continue
        # Skip lines that are too short
        if len(line) < 2:
            continue
        # Check first column (index/staged status)
        # If first char is not space and not '?', it's staged
        first_col = line[0]
        if first_col != " " and first_col != "?":
            filtered_lines.append(line)

    return "\n".join(filtered_lines)


def _get_staged_files_list() -> list[str]:
    """Get list of staged file paths.

    Returns:
        List of staged file paths.
    """
    output = _run_git_command(["diff", "--staged", "--name-only"])
    if not output:
        return []
    return output.split("\n")

