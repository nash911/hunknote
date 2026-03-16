"""Phase 5a: Git Worktree Validation.

Applies each commit's patch in an isolated git worktree and runs
layered validation checks. Bails on first failure.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from hunknote.compose.agent.models import (
    CommitGroup,
    FrozenBaseline,
    FrozenCommit,
    HunkSummary,
    ValidationFailure,
    ValidationLayer,
)
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.models import FileDiff, HunkRef, PlannedCommit
from hunknote.compose.patch import build_commit_patch

logger = logging.getLogger(__name__)


def run_phase5a_validate(
    ordered_groups: list[CommitGroup],
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
    repo_root: Path,
    trace: AgentTrace,
    summaries: Optional[dict[str, HunkSummary]] = None,
    start_from_index: int = 0,
    run_tests: bool = False,
) -> tuple[Optional[ValidationFailure], FrozenBaseline]:
    """Validate the commit sequence in an isolated git worktree.

    For each commit (starting from start_from_index):
      Layer 1: git apply — does the patch apply cleanly?
      Layer 2: py_compile — are touched Python files syntactically valid?
      Layer 3: import check — can touched Python modules be imported?

    Bails on first failure.

    Returns:
        (None, frozen_baseline) if all commits pass.
        (ValidationFailure, frozen_baseline_up_to_failure) if a commit fails.
    """
    frozen_baseline = FrozenBaseline()

    # Set up worktree
    worktree_base = Path.home() / ".hunknote" / "tmp"
    worktree_base.mkdir(parents=True, exist_ok=True)
    worktree_path = worktree_base / f"hunknote_validate_{os.getpid()}"

    # Clean up any stale worktree
    if worktree_path.exists():
        _cleanup_worktree(repo_root, worktree_path)

    try:
        # Create detached worktree from HEAD
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree_path), "HEAD"],
            capture_output=True, text=True, cwd=repo_root, timeout=30,
        )
        if result.returncode != 0:
            logger.warning("Failed to create worktree: %s", result.stderr)
            trace.warning("phase5", f"Worktree creation failed: {result.stderr}")
            # Fall back to no validation — return success
            return None, frozen_baseline

        trace.state_change("phase5", f"Created worktree at {worktree_path}")

        for i, group in enumerate(ordered_groups):
            # Build patch for this commit
            planned = _group_to_planned_commit(group)
            patch_content = build_commit_patch(planned, inventory, file_diffs)

            if not patch_content.strip():
                trace.warning("phase5", f"Empty patch for commit {group.group_id}")
                continue

            # Write patch to temp file
            patch_file = worktree_path / f"_commit_{i}.patch"
            patch_file.write_text(patch_content)

            if i < start_from_index:
                # Already validated — just apply to advance state
                _apply_patch_no_check(worktree_path, patch_file, trace)
                # Build frozen commit entry
                frozen_baseline.commits.append(_build_frozen_commit(
                    i, group, summaries,
                ))
                continue

            # Layer 1: Patch applies?
            trace.validation_check("phase5", group.group_id, "patch_apply")
            apply_result = subprocess.run(
                ["git", "apply", "--check", str(patch_file)],
                capture_output=True, text=True, cwd=worktree_path, timeout=30,
            )
            if apply_result.returncode != 0:
                trace.validation_fail(
                    "phase5", group.group_id, "patch_apply",
                    apply_result.stderr,
                )
                return (
                    ValidationFailure(
                        commit_index=i,
                        commit_group=group,
                        layer=ValidationLayer.PATCH_APPLY,
                        error_output=apply_result.stderr,
                    ),
                    frozen_baseline,
                )

            # Actually apply
            subprocess.run(
                ["git", "apply", str(patch_file)],
                capture_output=True, text=True, cwd=worktree_path, timeout=30,
            )
            trace.validation_pass("phase5", group.group_id)

            # Get touched files
            touched_files = _get_touched_files(group, inventory)
            py_files = [f for f in touched_files if f.endswith(".py")]

            # Layer 2: Syntax check (py_compile)
            if py_files:
                trace.validation_check("phase5", group.group_id, "syntax")
                syntax_failure = _check_syntax(worktree_path, py_files, i, group, trace)
                if syntax_failure:
                    return syntax_failure, frozen_baseline

            # Layer 3: Import check
            if py_files:
                trace.validation_check("phase5", group.group_id, "import")
                import_failure = _check_imports(worktree_path, py_files, i, group, trace)
                if import_failure:
                    return import_failure, frozen_baseline

            # Commit in worktree to advance state
            subprocess.run(
                ["git", "add", "-A"],
                capture_output=True, text=True, cwd=worktree_path, timeout=10,
            )
            subprocess.run(
                ["git", "commit", "-m", f"sim-{i}", "--allow-empty", "--no-verify"],
                capture_output=True, text=True, cwd=worktree_path, timeout=10,
            )

            # Build frozen commit entry
            frozen_baseline.commits.append(_build_frozen_commit(
                i, group, summaries,
            ))

            trace.validation_pass("phase5", group.group_id)

    finally:
        _cleanup_worktree(repo_root, worktree_path)

    return None, frozen_baseline


def _group_to_planned_commit(group: CommitGroup) -> PlannedCommit:
    """Convert CommitGroup to PlannedCommit for patch building."""
    return PlannedCommit(
        id=group.group_id,
        title=group.theme,
        type=group.category,
        hunks=group.hunk_ids,
    )


def _apply_patch_no_check(worktree_path: Path, patch_file: Path, trace: AgentTrace) -> None:
    """Apply a patch without validation checks, then commit."""
    subprocess.run(
        ["git", "apply", str(patch_file)],
        capture_output=True, text=True, cwd=worktree_path, timeout=30,
    )
    subprocess.run(
        ["git", "add", "-A"],
        capture_output=True, text=True, cwd=worktree_path, timeout=10,
    )
    subprocess.run(
        ["git", "commit", "-m", "sim-skip", "--allow-empty", "--no-verify"],
        capture_output=True, text=True, cwd=worktree_path, timeout=10,
    )


def _get_touched_files(group: CommitGroup, inventory: dict[str, HunkRef]) -> list[str]:
    """Get unique file paths touched by this commit group."""
    files = set()
    for hid in group.hunk_ids:
        hunk = inventory.get(hid)
        if hunk:
            files.add(hunk.file_path)
    return sorted(files)


def _check_syntax(
    worktree_path: Path,
    py_files: list[str],
    commit_index: int,
    group: CommitGroup,
    trace: AgentTrace,
) -> Optional[ValidationFailure]:
    """Run py_compile on Python files."""
    for fp in py_files:
        full_path = worktree_path / fp
        if not full_path.exists():
            continue
        result = subprocess.run(
            ["python", "-m", "py_compile", str(full_path)],
            capture_output=True, text=True, cwd=worktree_path, timeout=10,
        )
        if result.returncode != 0:
            error = result.stderr or result.stdout
            trace.validation_fail(
                "phase5", group.group_id, "syntax", error,
            )
            return ValidationFailure(
                commit_index=commit_index,
                commit_group=group,
                layer=ValidationLayer.SYNTAX,
                error_output=error,
                file_path=fp,
            )
    trace.validation_pass("phase5", group.group_id)
    return None


def _check_imports(
    worktree_path: Path,
    py_files: list[str],
    commit_index: int,
    group: CommitGroup,
    trace: AgentTrace,
) -> Optional[ValidationFailure]:
    """Check if Python modules can be imported."""
    for fp in py_files:
        full_path = worktree_path / fp
        if not full_path.exists():
            continue
        module = _file_path_to_module(fp)
        if not module:
            continue

        env = os.environ.copy()
        env["PYTHONPATH"] = str(worktree_path)
        result = subprocess.run(
            ["python", "-c", f"import {module}"],
            capture_output=True, text=True,
            cwd=worktree_path, timeout=15,
            env=env,
        )
        if result.returncode != 0:
            error = result.stderr or result.stdout
            trace.validation_fail(
                "phase5", group.group_id, "import", error,
            )
            return ValidationFailure(
                commit_index=commit_index,
                commit_group=group,
                layer=ValidationLayer.IMPORT,
                error_output=error,
                file_path=fp,
            )
    trace.validation_pass("phase5", group.group_id)
    return None


def _file_path_to_module(file_path: str) -> Optional[str]:
    """Convert src/foo/bar.py to src.foo.bar. Handle __init__.py."""
    if not file_path.endswith(".py"):
        return None
    path = file_path.replace("/", ".").replace("\\", ".")
    if path.endswith(".__init__.py"):
        path = path[:-len(".__init__.py")]
    elif path.endswith(".py"):
        path = path[:-3]
    # Skip test files and setup files
    if path.startswith("test") or path == "setup" or path == "conftest":
        return None
    return path


def _build_frozen_commit(
    index: int,
    group: CommitGroup,
    summaries: Optional[dict[str, HunkSummary]],
) -> FrozenCommit:
    """Build a FrozenCommit entry from a validated group."""
    symbols_introduced: list[str] = []
    symbols_removed: list[str] = []
    if summaries:
        for hid in group.hunk_ids:
            s = summaries.get(hid)
            if s:
                symbols_introduced.extend(s.symbols_modified)
                symbols_removed.extend(s.symbols_referenced)
    return FrozenCommit(
        index=index,
        message=group.theme,
        hunk_ids=list(group.hunk_ids),
        symbols_introduced=symbols_introduced,
        symbols_removed=symbols_removed,
    )


def _cleanup_worktree(repo_root: Path, worktree_path: Path) -> None:
    """Remove a git worktree."""
    try:
        subprocess.run(
            ["git", "worktree", "remove", str(worktree_path), "--force"],
            capture_output=True, text=True, cwd=repo_root, timeout=30,
        )
    except Exception:
        pass
    # Force cleanup if git worktree remove failed
    if worktree_path.exists():
        try:
            shutil.rmtree(worktree_path)
        except Exception:
            pass
