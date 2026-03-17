"""Integration tests for the Compose Agent (AgentOrchestrator) with file-level operations.

Unlike the single-shot coherence tests, these tests exercise the full 6-phase
agent pipeline (Summarize → Dependency → Cluster → Order → Validate → Messages)
against real git repositories with actual staged changes.

Each test:
  1. Creates a real git repo under ``~/.hunknote/tmp/``
  2. Commits initial files
  3. Makes changes (renames, deletions, additions) and stages them
  4. Runs the full agent pipeline with real LLM calls
  5. Asserts the generated plan is coherent
  6. Cleans up the test repo

This is NOT a unit test — it makes real API calls to the LLM.

Run:
    python integration_tests/test_agent_file_ops.py
    python integration_tests/test_agent_file_ops.py --case rename_with_import_update
    python integration_tests/test_agent_file_ops.py --list
    python integration_tests/test_agent_file_ops.py --provider google --model gemini-2.5-flash
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hunknote.compose.agent.orchestrator import AgentOrchestrator, OrchestratorConfig
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.inventory import build_file_ops_inventory, build_hunk_inventory, is_file_op_id
from hunknote.compose.models import ComposePlan, FileDiff
from hunknote.compose.parser import parse_unified_diff
from hunknote.llm.base import RawLLMResult


# ============================================================
# Constants
# ============================================================

TEST_REPO_BASE = Path.home() / ".hunknote" / "tmp"


# ============================================================
# Data models
# ============================================================


@dataclass
class AgentTestCase:
    """A test case for the Compose Agent file-ops integration tests."""

    id: str
    name: str
    description: str
    # Files that MUST be in the same commit for correctness
    must_be_together: list[set[str]]
    # File paths that MUST appear somewhere in the plan
    must_be_present: list[str] = field(default_factory=list)


@dataclass
class TestResult:
    """Result of a single test run."""

    case_id: str
    case_name: str
    passed: bool
    coherence_ok: bool
    presence_ok: bool
    num_commits: int
    details: str
    model: str = ""
    duration_ms: float = 0.0
    error: Optional[str] = None


# ============================================================
# Git helpers
# ============================================================


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in the test repo."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True, text=True, cwd=repo, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {repo}:\n{result.stderr}"
        )
    return result


def _init_repo(repo: Path) -> None:
    """Initialize a git repo with standard config."""
    repo.mkdir(parents=True, exist_ok=True)
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "test@hunknote.dev")
    _run_git(repo, "config", "user.name", "Hunknote Test")


def _write_file(repo: Path, rel_path: str, content: str) -> None:
    """Write a file in the repo, creating parent dirs as needed."""
    full = repo / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


def _commit(repo: Path, message: str) -> None:
    """Stage all and commit."""
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-m", message, "--allow-empty")


def _get_staged_diff(repo: Path) -> str:
    """Return the staged diff."""
    result = _run_git(repo, "diff", "--cached")
    return result.stdout


def _cleanup_repo(repo: Path) -> None:
    """Remove the test repo directory, cleaning up any worktrees first."""
    if not repo.exists():
        return
    # Clean up any git worktrees that may have been created during validation
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True, text=True, cwd=repo, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("worktree ") and str(repo) not in line:
                    wt_path = line.split("worktree ", 1)[1].strip()
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", wt_path],
                        capture_output=True, text=True, cwd=repo, timeout=10,
                    )
    except Exception:
        pass
    shutil.rmtree(repo, ignore_errors=True)


# ============================================================
# LLM call function builder
# ============================================================


def build_llm_call_fn(provider_name: str, model_name: str) -> Callable[[str, str], RawLLMResult]:
    """Build a real LLM call function."""
    from hunknote.config import LLMProvider, load_config
    from hunknote.llm import get_provider

    load_config()
    prov_enum = LLMProvider(provider_name)
    provider = get_provider(provider=prov_enum, model=model_name)

    def llm_call_fn(system_prompt: str, user_prompt: str) -> RawLLMResult:
        return provider.generate_raw(system_prompt, user_prompt)

    return llm_call_fn


# ============================================================
# Test Case 1: Pure file rename + import update
#
# ``git mv src/utils.py src/helpers.py`` — the file is renamed,
# and another file updates its import. The R_* entry and the
# import-updating hunk MUST end up in the same commit.
# ============================================================


def setup_rename_with_import_update(repo: Path) -> AgentTestCase:
    """Set up a repo with a file rename and import update."""

    # Initial state: two source files + an unrelated features file
    _write_file(repo, "src/__init__.py", "")
    _write_file(repo, "src/utils.py", (
        '"""Utility functions."""\n'
        '\n'
        'def helper(data: str) -> str:\n'
        '    """Transform data."""\n'
        '    return data.upper()\n'
        '\n'
        'def transform(data: str) -> str:\n'
        '    """Secondary transform."""\n'
        '    return data.strip()\n'
    ))
    _write_file(repo, "src/main.py", (
        '"""Main entry point."""\n'
        '\n'
        'from src.utils import helper, transform\n'
        '\n'
        'def run():\n'
        '    result = helper(transform("  hello  "))\n'
        '    print(result)\n'
        '    return result\n'
    ))
    _write_file(repo, "src/features.py", (
        '"""Feature module."""\n'
        '\n'
        'def existing_feature():\n'
        '    return "existing"\n'
    ))
    _commit(repo, "Initial commit")

    # Now: rename utils.py → helpers.py and update imports
    _run_git(repo, "mv", "src/utils.py", "src/helpers.py")
    # Update imports in main.py
    _write_file(repo, "src/main.py", (
        '"""Main entry point."""\n'
        '\n'
        'from src.helpers import helper, transform\n'
        '\n'
        'def run():\n'
        '    result = helper(transform("  hello  "))\n'
        '    print(result)\n'
        '    return result\n'
    ))
    # Also add an unrelated feature (to force multi-commit plan)
    _write_file(repo, "src/features.py", (
        '"""Feature module."""\n'
        '\n'
        'def existing_feature():\n'
        '    return "existing"\n'
        '\n'
        'def new_feature():\n'
        '    """A brand new feature."""\n'
        '    return "new"\n'
    ))
    _run_git(repo, "add", "-A")

    return AgentTestCase(
        id="rename_with_import_update",
        name="Pure rename (git mv) with import update",
        description=(
            "src/utils.py is renamed to src/helpers.py via git mv. "
            "src/main.py updates its import. The rename and the import "
            "update MUST be in the same commit."
        ),
        must_be_together=[{"src/helpers.py", "src/main.py"}],
    )


# ============================================================
# Test Case 2: Empty file deletion (git rm) + reference removal
#
# An empty ``__init__.py`` under a legacy package is deleted,
# and files that imported from that package remove the imports.
# ============================================================


def setup_empty_file_deletion(repo: Path) -> AgentTestCase:
    """Set up a repo with an empty file deletion and reference removal."""

    # Initial state: legacy package with __init__.py + helpers
    _write_file(repo, "src/__init__.py", "")
    _write_file(repo, "src/legacy/__init__.py", "")
    _write_file(repo, "src/legacy/helpers.py", (
        '"""Legacy helpers — deprecated."""\n'
        '\n'
        'def old_helper(data):\n'
        '    """Old helper function."""\n'
        '    return data.upper()\n'
        '\n'
        'def old_transform(data):\n'
        '    """Old transform function."""\n'
        '    return data.strip()\n'
    ))
    _write_file(repo, "src/core.py", (
        '"""Core module."""\n'
        '\n'
        'def new_helper(data):\n'
        '    """New helper function."""\n'
        '    return data.lower()\n'
    ))
    _write_file(repo, "src/app.py", (
        '"""Application entry point."""\n'
        '\n'
        'import os\n'
        'from src.legacy.helpers import old_helper, old_transform\n'
        'from src.core import new_helper\n'
        '\n'
        'def main():\n'
        '    data = "  Hello World  "\n'
        '    result = old_helper(old_transform(data))\n'
        '    print(result)\n'
        '    return result\n'
    ))
    _commit(repo, "Initial commit with legacy package")

    # Now: remove the legacy package entirely
    _run_git(repo, "rm", "src/legacy/__init__.py")
    _run_git(repo, "rm", "src/legacy/helpers.py")

    # Update app.py to use core instead of legacy
    _write_file(repo, "src/app.py", (
        '"""Application entry point."""\n'
        '\n'
        'import os\n'
        'from src.core import new_helper\n'
        '\n'
        'def main():\n'
        '    data = "  Hello World  "\n'
        '    result = new_helper(data)\n'
        '    print(result)\n'
        '    return result\n'
    ))
    _run_git(repo, "add", "-A")

    return AgentTestCase(
        id="empty_file_deletion",
        name="Empty file deletion (git rm) with reference removal",
        description=(
            "src/legacy/__init__.py (empty) and src/legacy/helpers.py "
            "are deleted. src/app.py removes its legacy imports and "
            "switches to src.core. All legacy removal changes should "
            "be in the same commit."
        ),
        must_be_together=[
            {"src/legacy/__init__.py", "src/legacy/helpers.py", "src/app.py"},
        ],
    )


# ============================================================
# Test Case 3: Empty file add + binary + excluded files
#
# A new package is created with an empty __init__.py, code,
# a binary file (simulated), and a lock file update.
# The agent must assign code hunks coherently while binary/empty
# files go to residual or the same commit.
# ============================================================


def setup_empty_add_and_excluded(repo: Path) -> AgentTestCase:
    """Set up a repo with new empty files, binary, and lock file."""

    # Initial state
    _write_file(repo, "src/__init__.py", "")
    _write_file(repo, "src/app.py", (
        '"""Application entry point."""\n'
        '\n'
        'from src.core import process\n'
        '\n'
        'def main():\n'
        '    process()\n'
    ))
    _write_file(repo, "src/core.py", (
        '"""Core module."""\n'
        '\n'
        'def process():\n'
        '    print("processing")\n'
    ))
    _write_file(repo, "pyproject.toml", (
        '[tool.poetry]\n'
        'name = "testproject"\n'
        'version = "0.1.0"\n'
        '\n'
        '[tool.poetry.dependencies]\n'
        'python = "^3.10"\n'
    ))
    _commit(repo, "Initial commit")

    # Now: create a new analytics package
    _write_file(repo, "src/analytics/__init__.py", "")
    _write_file(repo, "src/analytics/tracker.py", (
        '"""Event tracking module."""\n'
        '\n'
        'from dataclasses import dataclass\n'
        '\n'
        '@dataclass\n'
        'class Event:\n'
        '    """An analytics event."""\n'
        '    name: str\n'
        '    payload: dict\n'
        '\n'
        'def track(event: Event) -> None:\n'
        '    """Track an event."""\n'
        '    print(f"Tracked: {event.name}")\n'
    ))

    # Update app.py to import from analytics
    _write_file(repo, "src/app.py", (
        '"""Application entry point."""\n'
        '\n'
        'from src.core import process\n'
        'from src.analytics.tracker import Event, track\n'
        '\n'
        'def main():\n'
        '    track(Event(name="startup", payload={}))\n'
        '    process()\n'
    ))

    # Simulate a lock file update (treated as binary by git diff)
    _write_file(repo, "pyproject.toml", (
        '[tool.poetry]\n'
        'name = "testproject"\n'
        'version = "0.1.0"\n'
        '\n'
        '[tool.poetry.dependencies]\n'
        'python = "^3.10"\n'
        'analytics-sdk = "^1.0.0"\n'
    ))

    _run_git(repo, "add", "-A")

    return AgentTestCase(
        id="empty_add_and_excluded",
        name="New package (__init__.py) + code + excluded files",
        description=(
            "A new analytics package is created: __init__.py (empty), "
            "tracker.py (new code), app.py imports from it, and "
            "pyproject.toml is updated. The new-package code files "
            "should be in the same commit."
        ),
        must_be_together=[
            {"src/analytics/tracker.py", "src/app.py"},
        ],
    )


# ============================================================
# All test cases: (setup_function, case_id)
# ============================================================

ALL_CASE_SETUPS = [
    ("rename_with_import_update", setup_rename_with_import_update),
    ("empty_file_deletion", setup_empty_file_deletion),
    ("empty_add_and_excluded", setup_empty_add_and_excluded),
]


# ============================================================
# Coherence checker
# ============================================================


def check_coherence(
    plan: ComposePlan,
    case: AgentTestCase,
    inventory: dict,
) -> tuple[bool, bool, list[str]]:
    """Check that the plan satisfies coherence and presence constraints.

    Returns:
        (coherence_ok, presence_ok, detail_lines)
    """
    details: list[str] = []

    # Build hunk-ID → file-path mapping (includes file-op IDs)
    hunk_to_file: dict[str, str] = {}
    for hid, href in inventory.items():
        hunk_to_file[hid] = href.file_path

    # Build commit → files mapping
    commit_files: dict[str, set[str]] = {}
    for commit in plan.commits:
        files: set[str] = set()
        for hid in commit.hunks:
            fp = hunk_to_file.get(hid)
            if fp:
                files.add(fp)
        commit_files[commit.id] = files

    # ── Check must_be_together ──
    coherence_ok = True
    for group in case.must_be_together:
        file_to_commit: dict[str, str] = {}
        for cid, cfiles in commit_files.items():
            for f in cfiles:
                if f in group:
                    file_to_commit[f] = cid

        unique_commits = set(file_to_commit.values())
        if len(unique_commits) > 1:
            coherence_ok = False
            details.append(f"  SPLIT: {sorted(group)} split across {sorted(unique_commits)}")
            for f, cid in sorted(file_to_commit.items()):
                details.append(f"    {f} → {cid}")
        elif unique_commits:
            details.append(f"  OK: {sorted(group)} all in {unique_commits.pop()}")
        else:
            missing = group - set(file_to_commit.keys())
            if missing:
                coherence_ok = False
                details.append(f"  MISSING: {sorted(missing)} not in any commit")

    # ── Check must_be_present ──
    presence_ok = True
    all_plan_files: set[str] = set()
    for cfiles in commit_files.values():
        all_plan_files.update(cfiles)

    for fp in case.must_be_present:
        if fp in all_plan_files:
            details.append(f"  PRESENT (plan): {fp}")
        else:
            presence_ok = False
            details.append(f"  ABSENT: {fp} not in any commit")

    # ── Show plan summary ──
    details.append("")
    details.append("  Plan summary:")
    for commit in plan.commits:
        files = sorted(commit_files.get(commit.id, set()))
        ctype = commit.type or ""
        scope = f"({commit.scope})" if commit.scope else ""
        details.append(f"    {commit.id}: {ctype}{scope}: {commit.title}")
        details.append(f"         hunks: {commit.hunks}")
        details.append(f"         files: {files}")

    return coherence_ok, presence_ok, details


# ============================================================
# Test runner
# ============================================================


def run_single_test(
    case_id: str,
    setup_fn: Callable,
    llm_call_fn: Callable,
) -> TestResult:
    """Run a single test case: set up repo, run agent, check coherence."""
    repo = TEST_REPO_BASE / f"agent_test_{case_id}_{os.getpid()}"

    try:
        # ── Set up repo ──
        _cleanup_repo(repo)
        _init_repo(repo)
        case = setup_fn(repo)

        # ── Get staged diff and parse ──
        diff = _get_staged_diff(repo)
        if not diff.strip():
            return TestResult(
                case_id=case_id, case_name=case.name,
                passed=False, coherence_ok=False, presence_ok=False,
                num_commits=0, details="",
                error="No staged diff found after setup",
            )

        file_diffs, warnings = parse_unified_diff(diff)
        inventory = build_hunk_inventory(file_diffs)
        file_ops = build_file_ops_inventory(file_diffs)
        inventory.update(file_ops)

        # ── Run agent ──
        config = OrchestratorConfig(
            max_retries=2,
            max_commits=6,
            run_tests=False,
        )
        trace = AgentTrace()
        orchestrator = AgentOrchestrator(
            file_diffs=file_diffs,
            inventory=inventory,
            repo_root=repo,
            llm_call_fn=llm_call_fn,
            config=config,
            trace=trace,
        )

        start = time.time()
        plan = orchestrator.run()
        duration_ms = (time.time() - start) * 1000

        # ── Check coherence ──
        # Use the orchestrator's inventory (which includes the file-ops
        # it merged in its __init__).
        coherence_ok, presence_ok, detail_lines = check_coherence(
            plan, case, orchestrator.inventory,
        )
        passed = coherence_ok and presence_ok

        return TestResult(
            case_id=case_id, case_name=case.name,
            passed=passed, coherence_ok=coherence_ok,
            presence_ok=presence_ok,
            num_commits=len(plan.commits),
            details="\n".join(detail_lines),
            duration_ms=duration_ms,
        )

    except Exception as e:
        import traceback
        return TestResult(
            case_id=case_id, case_name=case.name if 'case' in dir() else case_id,
            passed=False, coherence_ok=False, presence_ok=False,
            num_commits=0, details="",
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
        )
    finally:
        _cleanup_repo(repo)


# ============================================================
# CLI
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description="Compose Agent file-operations integration tests (real LLM calls)",
    )
    parser.add_argument(
        "--case", type=str, default=None,
        help="Run a specific case by ID",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all available test cases",
    )
    parser.add_argument(
        "--provider", type=str, default="google",
        help="LLM provider (default: google)",
    )
    parser.add_argument(
        "--model", type=str, default="gemini-2.5-flash",
        help="LLM model (default: gemini-2.5-flash)",
    )
    args = parser.parse_args()

    if args.list:
        print("Available test cases:")
        for cid, setup_fn in ALL_CASE_SETUPS:
            # Create a temporary repo to get the case description
            tmp_repo = TEST_REPO_BASE / f"_list_tmp_{cid}"
            try:
                _init_repo(tmp_repo)
                case = setup_fn(tmp_repo)
                print(f"  {case.id}: {case.name}")
                print(f"    {case.description}")
                print()
            finally:
                _cleanup_repo(tmp_repo)
        return

    # Build LLM call function
    llm_call_fn = build_llm_call_fn(args.provider, args.model)

    # Filter cases
    cases = ALL_CASE_SETUPS
    if args.case:
        cases = [(cid, fn) for cid, fn in ALL_CASE_SETUPS if cid == args.case]
        if not cases:
            print(f"Unknown case: {args.case}")
            print("Use --list to see available cases.")
            sys.exit(1)

    print("=" * 70)
    print("  Compose Agent — File-Operations Integration Tests")
    print(f"  LLM: {args.provider} / {args.model}")
    print(f"  Pipeline: Full 6-phase agent (Summarize → Dep → Cluster → Order → Validate → Messages)")
    print("=" * 70)
    print()

    results: list[TestResult] = []

    for case_id, setup_fn in cases:
        # Peek at case for printing
        tmp_repo = TEST_REPO_BASE / f"_peek_tmp_{case_id}"
        try:
            _init_repo(tmp_repo)
            case = setup_fn(tmp_repo)
            print(f"Running: {case.name} ({case.id})")
            print(f"  {case.description}")
            print()
        finally:
            _cleanup_repo(tmp_repo)

        result = run_single_test(case_id, setup_fn, llm_call_fn)
        results.append(result)

        if result.error:
            print(f"  ❌ ERROR: {result.error}")
        else:
            status = "✅ PASSED" if result.passed else "❌ FAILED"
            parts = []
            if not result.coherence_ok:
                parts.append("coherence")
            if not result.presence_ok:
                parts.append("presence")
            reason = f" ({', '.join(parts)} failed)" if parts else ""
            print(f"  {status}{reason}")
            print(f"  Commits: {result.num_commits}")
            print(f"  Duration: {result.duration_ms:.0f}ms")
            print(result.details)

        print()
        print("-" * 70)
        print()

    # ── Summary ──
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print("=" * 70)
    print(f"  SUMMARY: {passed}/{total} passed, {failed}/{total} failed")
    print()
    for r in results:
        status = "✅" if r.passed else "❌"
        extra = f" — {r.error[:80]}..." if r.error else ""
        print(f"  {status} {r.case_id}: {r.case_name}{extra}")
    print("=" * 70)

    # ── Save results ──
    evals_dir = Path(__file__).parent / "evals"
    evals_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    out_file = evals_dir / f"agent_file_ops_{ts}.json"
    out_data = {
        "timestamp": ts,
        "provider": args.provider,
        "model": args.model,
        "pipeline": "agent_6_phase",
        "total": total,
        "passed": passed,
        "failed": failed,
        "results": [
            {
                "case_id": r.case_id,
                "case_name": r.case_name,
                "passed": r.passed,
                "coherence_ok": r.coherence_ok,
                "presence_ok": r.presence_ok,
                "num_commits": r.num_commits,
                "duration_ms": r.duration_ms,
                "error": r.error,
                "details": r.details,
            }
            for r in results
        ],
    }
    out_file.write_text(json.dumps(out_data, indent=2))
    print(f"\nResults saved to {out_file}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

