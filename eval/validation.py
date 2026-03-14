"""Mechanical validation engine.

Applies the agent's proposed commits in a worktree and runs layered
validation using the target venv:
  1. git apply --check (patch applies?)
  2. py_compile on touched .py files
  3. python -c "import X" for each touched module
  4. pytest (optional)
"""

import logging
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from hunknote.compose.models import ComposePlan, HunkRef, FileDiff
from hunknote.compose.patch import build_commit_patch
from eval.environment import TargetEnv
from eval.models import (
    CommitValidation,
    MechanicalResult,
    TestCase,
)

logger = logging.getLogger(__name__)


def validate_agent_plan(
    test_case: TestCase,
    agent_plan: ComposePlan,
    target_env: TargetEnv,
    repo_dir: Path,
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
) -> MechanicalResult:
    """Validate the agent's proposed commit sequence.

    Uses a git worktree to apply commits one at a time and run
    validation at each checkpoint.

    Args:
        test_case: The test case being evaluated.
        agent_plan: The agent's proposed ComposePlan.
        target_env: Isolated venv for running validation commands.
        repo_dir: Path to the extracted repo.
        inventory: Hunk ID -> HunkRef mapping.
        file_diffs: Parsed file diffs.

    Returns:
        MechanicalResult with per-commit validation details.
    """
    worktree_dir = repo_dir / ".eval_worktree"
    worktree_branch = "eval_validation_tmp"
    per_commit: list[CommitValidation] = []
    first_failure: Optional[int] = None
    final_state_matches: Optional[bool] = None
    final_state_diff: Optional[str] = None

    try:
        # Create a worktree for validation
        _create_worktree(repo_dir, worktree_dir, worktree_branch)

        for i, commit in enumerate(agent_plan.commits):
            # Build the patch for this commit
            try:
                patch_content = build_commit_patch(commit, inventory, file_diffs)
            except Exception as e:
                logger.error("Failed to build patch for %s: %s", commit.id, e)
                validation = CommitValidation(
                    commit_index=i,
                    commit_id=commit.id,
                    patch_applies=False,
                    syntax_valid=False,
                    compile_passes=False,
                    import_resolves=False,
                    errors=[f"Patch build failed: {e}"],
                )
                per_commit.append(validation)
                if first_failure is None:
                    first_failure = i
                continue

            # Layer 1: Patch applies?
            patch_ok = _check_patch_applies(worktree_dir, patch_content)

            if not patch_ok:
                validation = CommitValidation(
                    commit_index=i,
                    commit_id=commit.id,
                    patch_applies=False,
                    syntax_valid=False,
                    compile_passes=False,
                    import_resolves=False,
                    errors=["Patch does not apply cleanly"],
                )
                per_commit.append(validation)
                if first_failure is None:
                    first_failure = i
                continue

            # Apply the patch
            _apply_patch(worktree_dir, patch_content)

            # Get files touched by this commit
            touched_files = _get_touched_files(commit, inventory)

            # Layer 2: Syntax check (py_compile)
            syntax_ok, syntax_errors = _check_syntax(
                worktree_dir, touched_files, test_case.build_system.check_command, target_env
            )

            # Layer 3: Import resolution
            import_ok = True
            import_errors: list[str] = []
            if test_case.build_system.import_check:
                import_ok, import_errors = _check_imports(
                    worktree_dir, touched_files, target_env
                )

            # Layer 4: Tests (optional) — only if earlier checks passed
            tests_pass: Optional[bool] = None
            test_errors: list[str] = []
            if (
                test_case.build_system.test_enabled
                and test_case.build_system.test_command
                and syntax_ok
                and import_ok
            ):
                tests_pass, test_errors = _run_tests(
                    worktree_dir,
                    test_case.build_system.test_command,
                    target_env,
                )

            all_errors = syntax_errors + import_errors + test_errors
            compile_ok = syntax_ok
            commit_valid = patch_ok and syntax_ok and import_ok
            if tests_pass is False:
                commit_valid = False

            if not commit_valid and first_failure is None:
                first_failure = i

            validation = CommitValidation(
                commit_index=i,
                commit_id=commit.id,
                patch_applies=True,
                syntax_valid=syntax_ok,
                compile_passes=compile_ok,
                import_resolves=import_ok,
                tests_pass=tests_pass,
                errors=all_errors,
            )
            per_commit.append(validation)

            # Stage the applied changes in the worktree for the next commit
            _stage_and_commit_worktree(worktree_dir, commit.id)

        # ── Layer 5: Final-state verification ──
        # After all plan commits are applied, verify that the worktree
        # matches the expected after-state (i.e. the staged.patch).
        final_state_matches, final_state_diff = _check_final_state(
            worktree_dir, test_case.case_dir / "staged.patch"
        )

    finally:
        _cleanup_worktree(repo_dir, worktree_dir, worktree_branch)

    # Compute aggregate rates
    total = len(per_commit)
    if total == 0:
        return MechanicalResult(
            full_sequence_valid=False,
            build_pass_rate=0.0,
            patch_apply_rate=0.0,
            import_integrity_rate=0.0,
        )

    patch_pass = sum(1 for c in per_commit if c.patch_applies)
    compile_pass = sum(1 for c in per_commit if c.compile_passes)
    import_pass = sum(1 for c in per_commit if c.import_resolves)
    all_valid = all(
        c.patch_applies and c.syntax_valid and c.import_resolves
        and c.tests_pass is not False
        for c in per_commit
    )

    test_pass_rate: Optional[float] = None
    if test_case.build_system.test_enabled:
        test_results = [c for c in per_commit if c.tests_pass is not None]
        if test_results:
            test_pass_rate = sum(1 for c in test_results if c.tests_pass) / len(test_results)

    return MechanicalResult(
        full_sequence_valid=all_valid and final_state_matches is True,
        build_pass_rate=compile_pass / total,
        patch_apply_rate=patch_pass / total,
        import_integrity_rate=import_pass / total,
        test_pass_rate=test_pass_rate,
        final_state_matches=final_state_matches,
        final_state_diff=final_state_diff,
        per_commit=per_commit,
        first_failure_index=first_failure,
    )


def _create_worktree(repo_dir: Path, worktree_dir: Path, branch: str) -> None:
    """Create a git worktree for validation."""
    if worktree_dir.exists():
        _cleanup_worktree(repo_dir, worktree_dir, branch)

    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_dir), "HEAD"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )


def _cleanup_worktree(repo_dir: Path, worktree_dir: Path, branch: str) -> None:
    """Remove the validation worktree and branch."""
    if worktree_dir.exists():
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_dir)],
            cwd=repo_dir,
            capture_output=True,
        )
    # Clean up the branch
    subprocess.run(
        ["git", "branch", "-D", branch],
        cwd=repo_dir,
        capture_output=True,
    )


def _check_patch_applies(worktree_dir: Path, patch_content: str) -> bool:
    """Check if a patch applies cleanly (dry run)."""
    result = subprocess.run(
        ["git", "apply", "--check", "-"],
        input=patch_content,
        cwd=worktree_dir,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _check_final_state(
    worktree_dir: Path, staged_patch_path: Path
) -> tuple[Optional[bool], Optional[str]]:
    """Verify the worktree matches the expected after-state.

    After all plan commits have been applied, the cumulative change
    should be identical to the ``staged.patch`` file.  We verify this
    by reverse-applying the staged patch: if the worktree becomes
    clean (no diff vs. the original HEAD), the state matches.

    Returns:
        Tuple of (matches: bool, diff_summary: str | None).
        ``diff_summary`` is a short ``git diff --stat`` output when
        there is a mismatch, or None when it matches.
    """
    if not staged_patch_path.exists():
        logger.warning("No staged.patch found at %s — skipping final-state check", staged_patch_path)
        return None, None

    staged_patch = staged_patch_path.read_text()

    # Try reverse-applying the staged patch.
    # If the worktree is exactly at the after-state, this brings it
    # back to the before-state with no residual diff.
    result = subprocess.run(
        ["git", "apply", "-R", "--check", "-"],
        input=staged_patch,
        cwd=worktree_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, None

    # The reverse-apply failed — the plan didn't reproduce the full diff.
    # Generate a diff summary showing what's different.
    # First, get the cumulative diff of the worktree vs its initial state.
    diff_result = subprocess.run(
        ["git", "diff", "--stat", "HEAD~" + str(_count_commits(worktree_dir))],
        cwd=worktree_dir,
        capture_output=True,
        text=True,
    )
    # Fallback: just diff vs initial commit
    if diff_result.returncode != 0:
        diff_result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=worktree_dir,
            capture_output=True,
            text=True,
        )

    diff_summary = diff_result.stdout[:2000] if diff_result.stdout else result.stderr[:500]
    return False, diff_summary


def _count_commits(worktree_dir: Path) -> int:
    """Count commits on the current branch in the worktree."""
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=worktree_dir,
        capture_output=True,
        text=True,
    )
    try:
        return int(result.stdout.strip())
    except (ValueError, AttributeError):
        return 1


def _apply_patch(worktree_dir: Path, patch_content: str) -> None:
    """Apply a patch to the worktree."""
    subprocess.run(
        ["git", "apply", "-"],
        input=patch_content,
        cwd=worktree_dir,
        capture_output=True,
        text=True,
        check=True,
    )


def _stage_and_commit_worktree(worktree_dir: Path, commit_id: str) -> None:
    """Stage and commit changes in the worktree."""
    subprocess.run(
        ["git", "add", "-A"],
        cwd=worktree_dir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"eval: {commit_id}", "--allow-empty"],
        cwd=worktree_dir,
        capture_output=True,
    )


def _get_touched_files(commit, inventory: dict[str, HunkRef]) -> list[str]:
    """Get list of files touched by a commit."""
    files = set()
    for hunk_id in commit.hunks:
        if hunk_id in inventory:
            files.add(inventory[hunk_id].file_path)
    return sorted(files)


def _check_syntax(
    worktree_dir: Path,
    touched_files: list[str],
    check_command: str,
    target_env: TargetEnv,
) -> tuple[bool, list[str]]:
    """Run syntax check (py_compile) on touched files.

    Returns:
        Tuple of (all_ok, list of error messages).
    """
    errors: list[str] = []
    py_files = [f for f in touched_files if f.endswith(".py")]

    for file_path in py_files:
        full_path = worktree_dir / file_path
        if not full_path.exists():
            continue  # File was deleted

        cmd_str = check_command.format(file=file_path)
        parts = shlex.split(cmd_str)
        result = target_env.run(parts, cwd=worktree_dir, timeout=30)

        if result.returncode != 0:
            errors.append(f"Syntax error in {file_path}: {result.stderr.strip()}")

    return len(errors) == 0, errors


def _check_imports(
    worktree_dir: Path,
    touched_files: list[str],
    target_env: TargetEnv,
) -> tuple[bool, list[str]]:
    """Run import resolution checks on touched modules.

    Skips test files, doc configs, and scripts — they often have
    optional/test-only dependencies that are not installed in the
    target venv and are not relevant to build integrity.

    Returns:
        Tuple of (all_ok, list of error messages).
    """
    errors: list[str] = []
    py_files = [f for f in touched_files if f.endswith(".py")]

    # Prefixes/directories to skip during import checks
    _SKIP_PREFIXES = ("tests/", "test/", "docs/", "scripts/", "benchmarks/", "examples/")

    for file_path in py_files:
        # Skip test and non-library files
        if any(file_path.startswith(prefix) for prefix in _SKIP_PREFIXES):
            continue
        basename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
        if basename.startswith("test_") or basename == "conftest.py":
            continue

        # Skip deleted files — they were touched (removed) by this commit
        full_path = worktree_dir / file_path
        if not full_path.exists():
            continue

        module_name = _file_path_to_module(file_path, worktree_dir)
        if module_name is None:
            continue

        result = target_env.run(
            ["python", "-c", f"import {module_name}"],
            cwd=worktree_dir,
            timeout=30,
            env_override={"PYTHONPATH": str(worktree_dir)},
        )

        if result.returncode != 0:
            errors.append(f"Import failed for {module_name}: {result.stderr.strip()}")

    return len(errors) == 0, errors


def _run_tests(
    worktree_dir: Path,
    test_command: str,
    target_env: TargetEnv,
) -> tuple[bool, list[str]]:
    """Run the full test suite after a commit is applied.

    Called for every commit in the proposed plan when ``test_enabled``
    is True and the earlier mechanical checks (syntax, import) passed.

    Returns:
        Tuple of (passed, list of error messages).
    """
    parts = shlex.split(test_command)
    result = target_env.run(parts, cwd=worktree_dir, timeout=300)

    if result.returncode != 0:
        # Truncate test output to avoid huge error messages
        stderr = result.stderr[:2000] if result.stderr else ""
        stdout = result.stdout[:2000] if result.stdout else ""
        return False, [f"Tests failed:\n{stderr}\n{stdout}"]

    return True, []


def _file_path_to_module(file_path: str, repo_dir: Path) -> Optional[str]:
    """Convert a file path to a Python module name.

    Examples:
        "httpx/_models.py"          -> "httpx._models"
        "httpx/__init__.py"         -> "httpx"
        "tests/test_models.py"      -> "tests.test_models"
        "setup.py"                  -> None (top-level script)
        "docs/conf.py"              -> None (not importable)

    Returns None if the file is not importable (no __init__.py chain,
    or is a top-level script).
    """
    if not file_path.endswith(".py"):
        return None

    path = Path(file_path)
    parts = list(path.parts)

    # Top-level .py files are not modules
    if len(parts) == 1:
        return None

    # Check __init__.py chain exists
    for i in range(len(parts) - 1):
        init_path = repo_dir / Path(*parts[: i + 1]) / "__init__.py"
        if not init_path.exists():
            return None

    # Convert to module name
    if parts[-1] == "__init__.py":
        return ".".join(parts[:-1])
    else:
        module_parts = parts[:-1] + [path.stem]
        # Skip files whose name parts are not valid Python identifiers
        # (e.g., "unicode10-0-0.py" — hyphens make import impossible)
        if not all(p.isidentifier() for p in module_parts):
            return None
        return ".".join(module_parts)
