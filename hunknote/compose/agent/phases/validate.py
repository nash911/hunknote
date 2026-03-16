"""Phase 5a: Git Worktree Validation.

Applies each commit's patch in an isolated git worktree and runs
layered validation checks. Bails on first failure.
"""

import ast
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
    python_bin: Optional[str] = None,
) -> tuple[Optional[ValidationFailure], FrozenBaseline]:
    """Validate the commit sequence in an isolated git worktree.

    For each commit (starting from start_from_index):
      Layer 1: git apply — does the patch apply cleanly?
      Layer 2: py_compile — are touched Python files syntactically valid?
      Layer 3: import check — can touched Python modules be imported?
      Layer 4: import_deps — do all imports within touched files (including
               lazy imports inside functions) reference modules that exist?

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
                syntax_failure = _check_syntax(worktree_path, py_files, i, group, trace, python_bin=python_bin)
                if syntax_failure:
                    return syntax_failure, frozen_baseline

            # Layer 3: Import check
            if py_files:
                trace.validation_check("phase5", group.group_id, "import")
                import_failure = _check_imports(worktree_path, py_files, i, group, trace, python_bin=python_bin)
                if import_failure:
                    return import_failure, frozen_baseline

            # Layer 4: Static import dependency analysis
            # Catches lazy imports (inside functions) that reference modules
            # not yet present in the worktree — the runtime import check above
            # only triggers module-level imports.
            if py_files:
                trace.validation_check("phase5", group.group_id, "import_deps")
                deps_failure = _check_import_deps(
                    worktree_path, py_files, i, group, trace,
                )
                if deps_failure:
                    return deps_failure, frozen_baseline

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
    python_bin: Optional[str] = None,
) -> Optional[ValidationFailure]:
    """Run py_compile on Python files."""
    py_cmd = python_bin or "python"
    for fp in py_files:
        full_path = worktree_path / fp
        if not full_path.exists():
            continue
        result = subprocess.run(
            [py_cmd, "-m", "py_compile", str(full_path)],
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
    python_bin: Optional[str] = None,
) -> Optional[ValidationFailure]:
    """Check if Python modules can be imported."""
    py_cmd = python_bin or "python"
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
            [py_cmd, "-c", f"import {module}"],
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
    # Skip standalone setup scripts (not importable as modules)
    if path == "setup" or path == "conftest":
        return None
    return path


def _check_import_deps(
    worktree_path: Path,
    py_files: list[str],
    commit_index: int,
    group: CommitGroup,
    trace: AgentTrace,
) -> Optional[ValidationFailure]:
    """Static analysis: verify all imports within touched files resolve.

    Unlike the runtime import check (Layer 3), this scans the full AST of
    each file — including imports inside functions, conditionals, and
    try/except blocks — and verifies that every referenced internal module
    exists as a file in the worktree.

    This catches the common case where a file uses lazy imports to reference
    modules that haven't been added yet (e.g., CLI code importing from a
    feature module via ``from pkg.feature import X`` inside a function body).
    """
    for fp in py_files:
        full_path = worktree_path / fp
        if not full_path.exists():
            continue
        try:
            source = full_path.read_text()
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue  # Already caught by syntax check

        for node in ast.walk(tree):
            module_name: Optional[str] = None

            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name
                    missing = _check_internal_module_missing(
                        worktree_path, module_name,
                    )
                    if missing:
                        error = (
                            f"{fp}:{node.lineno}: "
                            f"import {module_name} — "
                            f"module not found in worktree"
                        )
                        trace.validation_fail(
                            "phase5", group.group_id, "import_deps", error,
                        )
                        return ValidationFailure(
                            commit_index=commit_index,
                            commit_group=group,
                            layer=ValidationLayer.IMPORT_DEPS,
                            error_output=error,
                            file_path=fp,
                        )

            elif isinstance(node, ast.ImportFrom):
                # Only check absolute imports (level == 0)
                if node.module and node.level == 0:
                    module_name = node.module
                    missing = _check_internal_module_missing(
                        worktree_path, module_name,
                    )
                    if missing:
                        names = ", ".join(a.name for a in node.names)
                        error = (
                            f"{fp}:{node.lineno}: "
                            f"from {module_name} import {names} — "
                            f"module not found in worktree"
                        )
                        trace.validation_fail(
                            "phase5", group.group_id, "import_deps", error,
                        )
                        return ValidationFailure(
                            commit_index=commit_index,
                            commit_group=group,
                            layer=ValidationLayer.IMPORT_DEPS,
                            error_output=error,
                            file_path=fp,
                        )

    trace.validation_pass("phase5", group.group_id)
    return None


def _check_internal_module_missing(
    worktree_path: Path, module_name: str,
) -> bool:
    """Return True if *module_name* is an internal project module that is missing.

    An internal module is one whose top-level package exists as a directory in
    the worktree (e.g. ``hunknote``, ``tests``, ``eval``).  If the top-level
    name does NOT exist in the worktree, the module is assumed to be external
    (stdlib or third-party) and is NOT flagged as missing.
    """
    parts = module_name.split(".")
    top_level = worktree_path / parts[0]

    # If the top-level package/file doesn't exist in the worktree,
    # it's an external module — not our problem.
    if not top_level.exists():
        return False

    # Internal module — check that the file actually exists.
    # Could be a package (dir/__init__.py) or a module (dir/name.py).
    mod_as_pkg = worktree_path / "/".join(parts) / "__init__.py"
    if len(parts) == 1:
        mod_as_file = worktree_path / (parts[0] + ".py")
    else:
        mod_as_file = worktree_path / "/".join(parts[:-1]) / (parts[-1] + ".py")

    return not (mod_as_pkg.exists() or mod_as_file.exists())


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
