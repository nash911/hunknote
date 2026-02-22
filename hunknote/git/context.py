"""Git context bundle builder.

Contains:
- build_context_bundle: Build the complete context bundle for the LLM
- _parse_file_changes: Parse git status into a human-readable file change summary
- _format_merge_state: Format merge state dictionary into human-readable text
"""

from hunknote.git.runner import get_repo_root
from hunknote.git.branch import get_branch, get_last_commits
from hunknote.git.status import get_staged_status
from hunknote.git.diff import get_staged_diff
from hunknote.git.merge import get_merge_state


def build_context_bundle(max_chars: int = 50000) -> str:
    """Build the complete context bundle for the LLM.

    Args:
        max_chars: Maximum characters for the staged diff.

    Returns:
        A formatted string containing all git context sections.

    Raises:
        NoStagedChangesError: If there are no staged changes.
        GitError: If not in a git repository.
    """
    # Get repo root for merge state detection
    repo_root = get_repo_root()

    # Get all context pieces
    branch = get_branch()
    # Use staged-only status to avoid confusing LLM with unstaged/untracked files
    status = get_staged_status()
    last_commits = get_last_commits(n=5)
    staged_diff = get_staged_diff(max_chars=max_chars)

    # Get merge state information
    merge_state_info = get_merge_state(repo_root)

    # Format commits as bullet list
    commits_formatted = "\n".join(f"- {commit}" for commit in last_commits) if last_commits else "- (no commits yet)"

    # Parse status to create a clear file change summary
    file_changes = _parse_file_changes(status)

    # Format merge state section
    merge_section = _format_merge_state(merge_state_info)

    # Build the context bundle
    bundle = f"""[BRANCH]
{branch}

[MERGE_STATE]
{merge_section}

[FILE_CHANGES]
{file_changes}

[LAST_5_COMMITS]
{commits_formatted}

[STAGED_DIFF]
{staged_diff}"""

    return bundle


def _format_merge_state(merge_state: dict) -> str:
    """Format merge state dictionary into human-readable text.

    Args:
        merge_state: Dictionary from get_merge_state().

    Returns:
        Formatted merge state string.
    """
    if merge_state["state"] == "normal":
        return "No merge in progress"

    lines = []
    if merge_state["state"] == "merge":
        lines.append("MERGE IN PROGRESS")
        if merge_state["source_branch"]:
            lines.append(f"Merging branch: {merge_state['source_branch']}")
        if merge_state["merge_head"]:
            lines.append(f"Merging commit: {merge_state['merge_head'][:12]}")
    elif merge_state["state"] == "merge-conflict":
        lines.append("MERGE CONFLICT - Resolving conflicts")
        if merge_state["source_branch"]:
            lines.append(f"Merging branch: {merge_state['source_branch']}")
        if merge_state["merge_head"]:
            lines.append(f"Merging commit: {merge_state['merge_head'][:12]}")
        if merge_state["conflicted_files"]:
            lines.append("Files with resolved conflicts:")
            for f in merge_state["conflicted_files"]:
                lines.append(f"  ! {f}")

    return "\n".join(lines)


def _parse_file_changes(status: str) -> str:
    """Parse git status into a human-readable file change summary.

    This helps the LLM understand which files are NEW (didn't exist before)
    versus MODIFIED (already existed and are being changed).

    Args:
        status: Git status in porcelain format.

    Returns:
        Human-readable summary of file changes.
    """
    new_files = []
    modified_files = []
    deleted_files = []
    renamed_files = []

    for line in status.split("\n"):
        if not line or line.startswith("##"):
            continue
        if len(line) < 3:
            continue

        status_code = line[0]
        filename = line[3:]

        # Handle renames: "R  old -> new"
        if " -> " in filename:
            old_name, new_name = filename.split(" -> ")
            renamed_files.append(f"{old_name} -> {new_name}")
            continue

        if status_code == "A":
            new_files.append(filename)
        elif status_code == "M":
            modified_files.append(filename)
        elif status_code == "D":
            deleted_files.append(filename)

    # Build summary
    lines = []
    if new_files:
        lines.append("New files (did not exist before this commit):")
        for f in new_files:
            lines.append(f"  + {f}")
    if modified_files:
        lines.append("Modified files (already existed, now changed):")
        for f in modified_files:
            lines.append(f"  ~ {f}")
    if deleted_files:
        lines.append("Deleted files:")
        for f in deleted_files:
            lines.append(f"  - {f}")
    if renamed_files:
        lines.append("Renamed files:")
        for f in renamed_files:
            lines.append(f"  > {f}")

    return "\n".join(lines) if lines else "(no files)"

