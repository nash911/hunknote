"""Integration tests for file-level operations and excluded files in compose.

These tests verify that the LLM correctly handles:
  1. Pure file renames (``git mv``) — the rename and its import-updating
     hunks must be in the same commit.
  2. Empty file deletions (``git rm``) — the deletion and hunks removing
     references must be in the same commit.
  3. Empty file additions (``git add`` of ``__init__.py``, ``.gitkeep``)
     and excluded files (binary, ``poetry.lock``) — these must appear
     in the plan (either via a synthetic ID or in the residual commit).

This is NOT a unit test — it makes real API calls to the LLM.

Run:
    python integration_tests/test_file_ops_coherence.py
    python integration_tests/test_file_ops_coherence.py --case rename_with_import_update
    python integration_tests/test_file_ops_coherence.py --list
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hunknote.compose.inventory import (
    build_file_ops_inventory,
    build_hunk_inventory,
    is_file_op_id,
)
from hunknote.compose.models import ComposePlan, FileDiff, HunkRef, PlannedCommit
from hunknote.compose.prompt import COMPOSE_SYSTEM_PROMPT, build_compose_prompt
from hunknote.compose.residual import append_residual_to_plan, collect_residual_files
from hunknote.compose.validation import validate_plan
from hunknote.llm.base import parse_json_response


# ============================================================
# Data models
# ============================================================


@dataclass
class FileOpsTestCase:
    """A test case for file-level operation coherence."""

    id: str
    name: str
    description: str
    file_diffs: list[FileDiff]
    # Files (or file-op IDs) that MUST be in the same commit
    must_be_together: list[set[str]]
    # File paths that MUST appear somewhere in the plan (assigned or residual)
    must_be_present: list[str] = field(default_factory=list)


@dataclass
class TestResult:
    """Result of a single test run."""

    case_id: str
    case_name: str
    passed: bool
    coherence_ok: bool
    presence_ok: bool
    plan_valid: bool
    num_commits: int
    details: str
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: float = 0.0
    error: Optional[str] = None


# ============================================================
# Helpers
# ============================================================


def make_hunk(hunk_id: str, file_path: str, header: str, lines: list[str]) -> HunkRef:
    """Build a HunkRef from compact data."""
    import re

    m = re.match(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@", header)
    old_start = int(m.group(1)) if m else 1
    old_len = int(m.group(2)) if m else 5
    new_start = int(m.group(3)) if m else 1
    new_len = int(m.group(4)) if m else 5
    return HunkRef(
        id=hunk_id,
        file_path=file_path,
        header=header,
        old_start=old_start,
        old_len=old_len,
        new_start=new_start,
        new_len=new_len,
        lines=[header] + lines,
    )


def make_file_diff(
    file_path: str,
    hunks: list[HunkRef] | None = None,
    is_renamed: bool = False,
    old_path: str | None = None,
    is_deleted_file: bool = False,
    is_new_file: bool = False,
    is_binary: bool = False,
) -> FileDiff:
    """Build a FileDiff with proper diff header lines."""
    a_path = old_path or file_path
    header = [f"diff --git a/{a_path} b/{file_path}"]
    if is_renamed and old_path:
        header += [
            "similarity index 100%",
            f"rename from {old_path}",
            f"rename to {file_path}",
        ]
    if is_new_file:
        header += ["new file mode 100644"]
    if is_deleted_file:
        header += ["deleted file mode 100644"]
    if is_binary:
        header += ["Binary files differ"]
    if hunks and not is_binary:
        header += [f"--- a/{a_path}", f"+++ b/{file_path}"]
    return FileDiff(
        file_path=file_path,
        diff_header_lines=header,
        hunks=hunks or [],
        is_renamed=is_renamed,
        old_path=old_path if is_renamed else None,
        is_new_file=is_new_file,
        is_deleted_file=is_deleted_file,
        is_binary=is_binary,
    )


# ============================================================
# Test Case 1: Pure file rename + import update
#
# Scenario: ``git mv src/utils.py src/helpers.py``
# plus a hunk in src/main.py updating the import statement.
# The rename (R_*) and the import hunk MUST be in the
# same commit, otherwise ``from src.helpers import helper``
# fails because the file doesn't exist yet.
# ============================================================


def case_rename_with_import_update() -> FileOpsTestCase:
    """Pure rename via git mv, plus import update in another file."""
    rename_diff = make_file_diff(
        "src/helpers.py", is_renamed=True, old_path="src/utils.py",
    )

    main_hunk = make_hunk(
        "H1_aaa111", "src/main.py",
        "@@ -1,4 +1,4 @@",
        [
            "-from src.utils import helper, transform",
            "+from src.helpers import helper, transform",
            " ",
            " def run():",
            "     return helper(transform('data'))",
        ],
    )
    main_diff = make_file_diff("src/main.py", hunks=[main_hunk])

    # There's also an unrelated feature hunk in another file
    feature_hunk = make_hunk(
        "H2_bbb222", "src/features.py",
        "@@ -10,3 +10,6 @@",
        [
            " def existing_feature():",
            "     pass",
            "+",
            "+def new_feature():",
            "+    return 'new'",
        ],
    )
    feature_diff = make_file_diff("src/features.py", hunks=[feature_hunk])

    # The R_* ID will be dynamically determined
    ops = build_file_ops_inventory([rename_diff, main_diff, feature_diff])
    rename_id = list(ops.keys())[0]

    return FileOpsTestCase(
        id="rename_with_import_update",
        name="Pure rename (git mv) with import update",
        description=(
            "src/utils.py is renamed to src/helpers.py via git mv. "
            "src/main.py updates its import. The rename and the import "
            "update MUST be in the same commit."
        ),
        file_diffs=[rename_diff, main_diff, feature_diff],
        must_be_together=[{"src/helpers.py", "src/main.py"}],
    )


# ============================================================
# Test Case 2: Empty file deletion (git rm) + reference removal
#
# Scenario: An empty ``__init__.py`` is deleted alongside other
# hunks that remove the import of the package it belonged to.
# ============================================================


def case_empty_file_deletion() -> FileOpsTestCase:
    """Delete empty __init__.py via git rm, plus import removal in consumer."""
    # The deleted __init__.py has no hunks (it was empty)
    delete_diff = make_file_diff(
        "src/legacy/__init__.py", is_deleted_file=True,
    )

    # A hunk in src/app.py removes the import of the legacy package
    remove_import_hunk = make_hunk(
        "H1_ccc333", "src/app.py",
        "@@ -2,6 +2,4 @@",
        [
            " import os",
            "-from src.legacy import old_helper",
            "-from src.legacy import old_transform",
            " from src.core import new_helper",
            " ",
            " def main():",
        ],
    )

    # Also a hunk in the same file replacing usage
    replace_usage_hunk = make_hunk(
        "H2_ddd444", "src/app.py",
        "@@ -15,5 +13,5 @@",
        [
            " def process():",
            "-    result = old_helper(old_transform(data))",
            "+    result = new_helper(data)",
            "     return result",
        ],
    )

    app_diff = make_file_diff(
        "src/app.py", hunks=[remove_import_hunk, replace_usage_hunk],
    )

    # Also remove another file from the legacy package (has hunks — full content removal)
    legacy_content_hunk = make_hunk(
        "H3_eee555", "src/legacy/helpers.py",
        "@@ -1,10 +0,0 @@",
        [
            "-\"\"\"Legacy helpers — deprecated.\"\"\"",
            "-",
            "-def old_helper(data):",
            "-    return data.upper()",
            "-",
            "-def old_transform(data):",
            "-    return data.strip()",
        ],
    )
    legacy_helpers_diff = make_file_diff(
        "src/legacy/helpers.py",
        hunks=[legacy_content_hunk],
        is_deleted_file=True,
    )

    ops = build_file_ops_inventory([delete_diff, app_diff, legacy_helpers_diff])
    delete_id = list(ops.keys())[0] if ops else None

    return FileOpsTestCase(
        id="empty_file_deletion",
        name="Empty file deletion (git rm) with reference removal",
        description=(
            "src/legacy/__init__.py (empty) is deleted via git rm. "
            "src/app.py removes its imports of the legacy package. "
            "src/legacy/helpers.py is fully deleted (has content hunks). "
            "The __init__.py deletion and the import removals should be "
            "in the same commit."
        ),
        file_diffs=[delete_diff, app_diff, legacy_helpers_diff],
        must_be_together=[
            {"src/legacy/__init__.py", "src/app.py", "src/legacy/helpers.py"},
        ],
    )


# ============================================================
# Test Case 3: Empty file add + binary files + excluded files
#
# Scenario: A new package is created with __init__.py, plus
# a binary file (icon.png), a lock file (poetry.lock), and
# regular code hunks. The coherence check verifies that:
#   (a) The __init__.py is referenced in the plan or in residual
#   (b) The binary/lock file is referenced in the plan or residual
#   (c) Regular hunks are grouped coherently
# ============================================================


def case_empty_add_and_excluded_files() -> FileOpsTestCase:
    """New package with __init__.py, binary file, lock file, and code."""
    # New empty __init__.py
    init_diff = make_file_diff(
        "src/analytics/__init__.py", is_new_file=True,
    )

    # New code file with hunks
    tracker_hunk_1 = make_hunk(
        "H1_fff666", "src/analytics/tracker.py",
        "@@ -0,0 +1,12 @@",
        [
            '+"""Event tracking module."""',
            "+",
            "+from dataclasses import dataclass",
            "+",
            "+@dataclass",
            "+class Event:",
            "+    name: str",
            "+    payload: dict",
            "+",
            "+def track(event: Event) -> None:",
            "+    print(f'Tracked: {event.name}')",
        ],
    )
    tracker_diff = make_file_diff(
        "src/analytics/tracker.py", hunks=[tracker_hunk_1], is_new_file=True,
    )

    # A hunk in an existing file that imports from the new package
    app_hunk = make_hunk(
        "H2_ggg777", "src/app.py",
        "@@ -3,3 +3,5 @@",
        [
            " from src.core import process",
            "+from src.analytics.tracker import Event, track",
            " ",
            " def main():",
            "+    track(Event(name='startup', payload={}))",
            "     process()",
        ],
    )
    app_diff = make_file_diff("src/app.py", hunks=[app_hunk])

    # Binary file — icon for the analytics dashboard
    icon_diff = make_file_diff("src/analytics/icon.png", is_binary=True)

    # Lock file update (binary-like, excluded from hunk parsing)
    lock_diff = make_file_diff("poetry.lock", is_binary=True)

    return FileOpsTestCase(
        id="empty_add_and_excluded_files",
        name="New package (__init__.py) + binary + lock file + code",
        description=(
            "A new analytics package is created: __init__.py (empty), "
            "tracker.py (new code), app.py imports from it. Also includes "
            "icon.png (binary) and poetry.lock update. All the new-package "
            "files should be together, binary/lock go to residual."
        ),
        file_diffs=[init_diff, tracker_diff, app_diff, icon_diff, lock_diff],
        must_be_together=[
            {"src/analytics/tracker.py", "src/app.py"},
        ],
        must_be_present=[
            "src/analytics/__init__.py",
            "src/analytics/icon.png",
            "poetry.lock",
        ],
    )


# ============================================================
# All test cases
# ============================================================

ALL_CASES = [
    case_rename_with_import_update,
    case_empty_file_deletion,
    case_empty_add_and_excluded_files,
]


# ============================================================
# Coherence and presence checks
# ============================================================


def check_coherence(
    plan: ComposePlan,
    case: FileOpsTestCase,
    inventory: dict[str, HunkRef],
) -> tuple[bool, bool, list[str]]:
    """Check coherence and presence constraints.

    Returns:
        (coherence_ok, presence_ok, detail_lines)
    """
    details: list[str] = []

    # ── Build hunk-ID → file-path mapping (includes file-op IDs) ──
    hunk_to_file: dict[str, str] = {}
    for hid, href in inventory.items():
        hunk_to_file[hid] = href.file_path

    # ── Build commit → files mapping ──
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
        else:
            if unique_commits:
                details.append(f"  OK: {sorted(group)} all in {unique_commits.pop()}")
            else:
                # Files not found in any commit — also a failure
                coherence_ok = False
                missing = group - set(file_to_commit.keys())
                details.append(f"  MISSING: {sorted(missing)} not in any commit")

    # ── Check must_be_present ──
    presence_ok = True
    all_plan_files: set[str] = set()
    for cfiles in commit_files.values():
        all_plan_files.update(cfiles)
    # Also check residual — these files might be in the residual commit
    residual = collect_residual_files(case.file_diffs, plan, inventory)
    residual_files = {fd.file_path for fd in residual}

    for fp in case.must_be_present:
        if fp in all_plan_files:
            details.append(f"  PRESENT (plan): {fp}")
        elif fp in residual_files:
            # Present in residual — the append_residual_to_plan step
            # will capture it. This is acceptable.
            details.append(f"  PRESENT (residual): {fp}")
        else:
            presence_ok = False
            details.append(f"  ABSENT: {fp} not in plan or residual")

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


def run_test(case_fn, provider) -> TestResult:
    """Run a single test case against the LLM."""
    case = case_fn()

    # Build inventories (regular + file-ops)
    inventory = build_hunk_inventory(case.file_diffs)
    file_ops = build_file_ops_inventory(case.file_diffs)
    inventory.update(file_ops)

    # Build prompt — format_inventory_for_llm will include the
    # [FILE OPERATIONS] section automatically.
    prompt = build_compose_prompt(
        file_diffs=case.file_diffs,
        branch="feature/update",
        recent_commits=["Previous commit 1"],
        style="conventional",
        max_commits=6,
    )

    start = time.time()
    try:
        result = provider.generate_raw(
            system_prompt=COMPOSE_SYSTEM_PROMPT,
            user_prompt=prompt,
        )
        duration_ms = (time.time() - start) * 1000

        plan_data = parse_json_response(result.raw_response)
        plan = ComposePlan(**plan_data)

        # Validate
        errors = validate_plan(plan, inventory, max_commits=6)
        plan_valid = len(errors) == 0

        # Check coherence and presence
        coherence_ok, presence_ok, detail_lines = check_coherence(
            plan, case, inventory,
        )
        passed = coherence_ok and presence_ok and plan_valid

        if errors:
            detail_lines.insert(0, f"  VALIDATION ERRORS: {errors}")

        return TestResult(
            case_id=case.id,
            case_name=case.name,
            passed=passed,
            coherence_ok=coherence_ok,
            presence_ok=presence_ok,
            plan_valid=plan_valid,
            num_commits=len(plan.commits),
            details="\n".join(detail_lines),
            model=result.model,
            tokens_in=result.input_tokens,
            tokens_out=result.output_tokens,
            duration_ms=duration_ms,
        )

    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        return TestResult(
            case_id=case.id,
            case_name=case.name,
            passed=False,
            coherence_ok=False,
            presence_ok=False,
            plan_valid=False,
            num_commits=0,
            details="",
            duration_ms=duration_ms,
            error=str(e),
        )


# ============================================================
# CLI
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description="File-operations coherence integration tests",
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
        for fn in ALL_CASES:
            c = fn()
            print(f"  {c.id}: {c.name}")
            print(f"    {c.description}")
            print()
        return

    # Load config and get provider
    from hunknote.config import LLMProvider, load_config
    from hunknote.llm import get_provider

    load_config()
    prov_enum = LLMProvider(args.provider)
    provider = get_provider(provider=prov_enum, model=args.model)

    cases = ALL_CASES
    if args.case:
        cases = [fn for fn in ALL_CASES if fn().id == args.case]
        if not cases:
            print(f"Unknown case: {args.case}")
            print("Use --list to see available cases.")
            sys.exit(1)

    print("=" * 70)
    print("  File-Operations Coherence — Integration Tests")
    print(f"  LLM: {args.provider} / {args.model}")
    print("=" * 70)
    print()

    results: list[TestResult] = []

    for case_fn in cases:
        case = case_fn()
        print(f"Running: {case.name} ({case.id})")
        print(f"  {case.description}")
        print()

        result = run_test(case_fn, provider)
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
            if not result.plan_valid:
                parts.append("validation")
            reason = f" ({', '.join(parts)} failed)" if parts else ""
            print(f"  {status}{reason}")
            print(f"  Model: {result.model} ({result.tokens_in} in / {result.tokens_out} out, {result.duration_ms:.0f}ms)")
            print(f"  Commits: {result.num_commits}")
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
        print(f"  {status} {r.case_id}: {r.case_name}")
    print("=" * 70)

    # ── Save results ──
    evals_dir = Path(__file__).parent / "evals"
    evals_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    out_file = evals_dir / f"file_ops_{ts}.json"
    out_data = {
        "timestamp": ts,
        "provider": args.provider,
        "model": args.model,
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
                "plan_valid": r.plan_valid,
                "num_commits": r.num_commits,
                "model": r.model,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
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

