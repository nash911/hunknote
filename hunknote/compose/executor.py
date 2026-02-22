"""Executor utilities for hunknote compose module.

Contains:
- ComposeSnapshot: Snapshot of git state before compose execution
- ComposeExecutionError: Error during compose execution
- create_snapshot: Create a snapshot of current git state
- restore_from_snapshot: Attempt to restore git state from snapshot
- execute_commit: Execute a single commit in the plan
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from hunknote.compose.models import PlannedCommit


class ComposeExecutionError(Exception):
    """Error during compose execution."""

    pass


@dataclass
class ComposeSnapshot:
    """Snapshot of git state before compose execution."""

    pre_head: str
    pre_staged_patch: str
    patch_file: Optional[Path] = None
    head_file: Optional[Path] = None


def create_snapshot(repo_root: Path, pid: int) -> ComposeSnapshot:
    """Create a snapshot of current git state.

    Args:
        repo_root: Repository root path
        pid: Process ID for unique filenames

    Returns:
        ComposeSnapshot with saved state
    """
    tmp_dir = repo_root / ".tmp"
    tmp_dir.mkdir(exist_ok=True)

    # Get current HEAD
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    pre_head = result.stdout.strip() if result.returncode == 0 else ""

    # Get current staged changes
    result = subprocess.run(
        ["git", "diff", "--cached"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    pre_staged_patch = result.stdout if result.returncode == 0 else ""

    # Save to files
    head_file = tmp_dir / f"hunknote_compose_pre_head_{pid}.txt"
    patch_file = tmp_dir / f"hunknote_compose_pre_staged_{pid}.patch"

    head_file.write_text(pre_head)
    if pre_staged_patch:
        patch_file.write_text(pre_staged_patch)

    return ComposeSnapshot(
        pre_head=pre_head,
        pre_staged_patch=pre_staged_patch,
        patch_file=patch_file if pre_staged_patch else None,
        head_file=head_file,
    )


def restore_from_snapshot(
    repo_root: Path, snapshot: ComposeSnapshot, commits_created: int
) -> tuple[bool, str]:
    """Attempt to restore git state from snapshot.

    Args:
        repo_root: Repository root path
        snapshot: The snapshot to restore from
        commits_created: Number of commits already created

    Returns:
        Tuple of (success, message)
    """
    messages = []

    # Reset index to HEAD
    result = subprocess.run(
        ["git", "reset"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        return False, f"Failed to reset index: {result.stderr}"

    messages.append("Reset index to HEAD")

    # Re-apply pre-staged changes if any
    if snapshot.patch_file and snapshot.patch_file.exists():
        result = subprocess.run(
            ["git", "apply", "--cached", str(snapshot.patch_file)],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if result.returncode == 0:
            messages.append("Restored pre-staged changes")
        else:
            messages.append(f"Warning: Could not restore staged changes: {result.stderr}")

    # Provide manual recovery instructions if commits were created
    if commits_created > 0:
        messages.append("")
        messages.append("MANUAL RECOVERY (if needed):")
        messages.append(f"  To undo the {commits_created} commit(s) created:")
        messages.append(f"  git reset --soft {snapshot.pre_head}")

    return True, "\n".join(messages)


def execute_commit(
    repo_root: Path,
    commit: PlannedCommit,
    patch_content: str,
    message: str,
    pid: int,
    debug: bool = False,
) -> None:
    """Execute a single commit in the plan.

    Args:
        repo_root: Repository root path
        commit: The planned commit
        patch_content: Patch content to apply
        message: Rendered commit message
        pid: Process ID for unique filenames
        debug: Whether to print debug output

    Raises:
        ComposeExecutionError: If commit fails
    """
    tmp_dir = repo_root / ".tmp"
    tmp_dir.mkdir(exist_ok=True)

    # Write patch file
    patch_file = tmp_dir / f"hunknote_compose_patch_{commit.id}_{pid}.patch"
    patch_file.write_text(patch_content)

    if debug:
        print(f"  Patch file: {patch_file}")
        print(f"  Patch size: {len(patch_content)} chars")

    # Apply patch to index
    result = subprocess.run(
        ["git", "apply", "--cached", str(patch_file)],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        raise ComposeExecutionError(
            f"Failed to apply patch for {commit.id}: {result.stderr}"
        )

    # Verify something is staged
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if not result.stdout.strip():
        raise ComposeExecutionError(f"No changes staged after applying {commit.id}")

    if debug:
        staged_files = result.stdout.strip().split("\n")
        print(f"  Staged files: {len(staged_files)}")

    # Write message file
    msg_file = tmp_dir / f"hunknote_compose_msg_{commit.id}_{pid}.txt"
    msg_file.write_text(message)

    # Commit
    result = subprocess.run(
        ["git", "commit", "-F", str(msg_file)],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        raise ComposeExecutionError(
            f"Failed to commit {commit.id}: {result.stderr}"
        )

    if debug:
        print(f"  Commit created: {commit.id}")

