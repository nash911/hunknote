"""Integration tests for compose plan coherence with file relationships.

Tests that the LLM correctly groups causally dependent hunks into the same
commit when provided with [FILE RELATIONSHIPS] in the prompt. Uses real
LLM API calls with synthetic diffs loaded from JSON test case files.

Test cases cover: Python, TypeScript, Go, Rust, Java, C/C++, Ruby.
Scenarios include: function removal, rename, parameter addition, transitive
chains, interleaved features, multi-consumer renames, and mixed changesets.

Run:
    python integration_tests/test_compose_coherence.py
    python integration_tests/test_compose_coherence.py --provider google --model gemini-2.5-flash
    python integration_tests/test_compose_coherence.py --provider anthropic --model claude-sonnet-4-20250514
    python integration_tests/test_compose_coherence.py --case py_remove_func_test_import
    python integration_tests/test_compose_coherence.py --list

Results are stored under integration_tests/evals/<timestamp>/.
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

from hunknote.compose.models import ComposePlan, FileDiff, HunkRef
from hunknote.compose.prompt import COMPOSE_SYSTEM_PROMPT, build_compose_prompt
from hunknote.compose.relationships import FileRelationship
from hunknote.llm.base import parse_json_response

# Directories
DATA_DIR = Path(__file__).parent / "data"
EVALS_DIR = Path(__file__).parent / "evals"


# ============================================================
# Data Models
# ============================================================

@dataclass
class TestCaseData:
    """A test case loaded from a JSON file."""

    id: str
    language: str
    name: str
    description: str
    difficulty: str
    category: str
    num_files: int
    num_hunks: int
    file_diffs: list[FileDiff]
    file_relationships: list[FileRelationship]
    must_be_together: list[set[str]]
    must_be_ordered: list[list[str]]  # [[A, B]] means A's commit must come before B's
    hunk_to_file: dict[str, str]
    source_file: str  # Path to the JSON file


@dataclass
class TestResult:
    """Result of a single test case evaluation."""

    case_id: str
    case_name: str
    language: str
    difficulty: str
    category: str
    passed: bool
    num_files: int
    num_hunks: int
    num_commits_generated: int
    model: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    coherence_details: str
    plan_summary: list[dict]
    error: Optional[str] = None


@dataclass
class EvalSummary:
    """Overall evaluation summary."""

    timestamp: str
    provider: str
    model: str
    total_cases: int
    passed: int
    failed: int
    errors: int
    pass_rate: float
    total_input_tokens: int
    total_output_tokens: int
    total_latency_seconds: float
    results_by_language: dict = field(default_factory=dict)
    results_by_difficulty: dict = field(default_factory=dict)
    results_by_category: dict = field(default_factory=dict)


# ============================================================
# JSON Test Case Loader
# ============================================================

def load_test_case(json_path: Path) -> TestCaseData:
    """Load a test case from a JSON file.

    Args:
        json_path: Path to the JSON file.

    Returns:
        A TestCaseData object.
    """
    with open(json_path) as f:
        data = json.load(f)

    # Build FileDiff objects
    file_diffs = []
    for fd_data in data["file_diffs"]:
        hunks = []
        for i, hd in enumerate(fd_data["hunks"]):
            hunks.append(HunkRef(
                id=hd["id"],
                file_path=fd_data["file_path"],
                header=hd.get("header", f"@@ -{i*10+1},5 +{i*10+1},8 @@"),
                old_start=i * 10 + 1,
                old_len=5,
                new_start=i * 10 + 1,
                new_len=8,
                lines=hd["lines"],
            ))
        file_diffs.append(FileDiff(
            file_path=fd_data["file_path"],
            diff_header_lines=[f"diff --git a/{fd_data['file_path']} b/{fd_data['file_path']}"],
            hunks=hunks,
        ))

    # Build FileRelationship objects
    relationships = []
    for rel_data in data.get("file_relationships", []):
        relationships.append(FileRelationship(
            source=rel_data["source"],
            target=rel_data["target"],
            kind=rel_data["kind"],
            via=rel_data.get("via"),
        ))

    # Build must_be_together sets
    must_be_together = [set(group) for group in data.get("must_be_together", [])]

    # Build must_be_ordered pairs: [[A, B]] means A must be committed before B
    must_be_ordered = data.get("must_be_ordered", [])

    return TestCaseData(
        id=data["id"],
        language=data["language"],
        name=data["name"],
        description=data["description"],
        difficulty=data["difficulty"],
        category=data["category"],
        num_files=data["num_files"],
        num_hunks=data["num_hunks"],
        file_diffs=file_diffs,
        file_relationships=relationships,
        must_be_together=must_be_together,
        must_be_ordered=must_be_ordered,
        hunk_to_file=data["hunk_to_file"],
        source_file=str(json_path),
    )


def load_all_test_cases() -> list[TestCaseData]:
    """Load all test cases from the data directory.

    Returns:
        List of TestCaseData sorted by language, then difficulty.
    """
    difficulty_order = {"easy": 0, "medium": 1, "hard": 2, "very_hard": 3, "super_hard": 4, "hyper_hard": 5}
    cases = []
    for json_file in sorted(DATA_DIR.glob("*.json")):
        try:
            cases.append(load_test_case(json_file))
        except Exception as e:
            print(f"  WARNING: Failed to load {json_file.name}: {e}")
    cases.sort(key=lambda c: (c.language, difficulty_order.get(c.difficulty, 99)))
    return cases


# ============================================================
# Coherence Checker
# ============================================================

def check_coherence(
    plan: ComposePlan,
    must_be_together: list[set[str]],
    must_be_ordered: list[list[str]],
    file_diffs: list[FileDiff],
) -> tuple[bool, str, list[dict]]:
    """Check if a plan satisfies coherence constraints.

    Two types of constraints:
    - must_be_together: Files that must share at least one common commit.
    - must_be_ordered: [[A, B]] means A must appear in an equal or earlier
      commit than B (A's commit index <= B's commit index).

    Args:
        plan: The compose plan from the LLM.
        must_be_together: List of sets of file paths that must share a commit.
        must_be_ordered: List of [dependency, consumer] pairs.
        file_diffs: The file diffs to map hunk IDs to file paths.

    Returns:
        Tuple of (passed, details_string, plan_summary).
    """
    # Build hunk_id -> file_path mapping
    hunk_to_file: dict[str, str] = {}
    for fd in file_diffs:
        for hunk in fd.hunks:
            hunk_to_file[hunk.id] = fd.file_path

    # For each commit, find which files it touches
    commit_files: dict[str, set[str]] = {}
    for commit in plan.commits:
        files_in_commit: set[str] = set()
        for hunk_id in commit.hunks:
            if hunk_id in hunk_to_file:
                files_in_commit.add(hunk_to_file[hunk_id])
        commit_files[commit.id] = files_in_commit

    # Build commit order: commit_id -> index (0-based)
    commit_order: dict[str, int] = {}
    for i, commit in enumerate(plan.commits):
        commit_order[commit.id] = i

    # Check each must-be-together group
    all_passed = True
    details_lines = []

    for group in must_be_together:
        # For each file in the group, collect which commits contain it
        file_to_commits: dict[str, set[str]] = {}
        for f in group:
            file_to_commits[f] = set()
        for cid, cfiles in commit_files.items():
            for f in cfiles:
                if f in group:
                    file_to_commits[f].add(cid)

        # The group is coherent if there exists at least one commit
        # that contains ALL files in the group
        all_commit_sets = [file_to_commits[f] for f in group if file_to_commits[f]]
        if all_commit_sets:
            common_commits = set.intersection(*all_commit_sets)
        else:
            common_commits = set()

        if common_commits:
            details_lines.append(
                f"  OK: {sorted(group)} share commit(s) {sorted(common_commits)}"
            )
        else:
            all_passed = False
            details_lines.append(f"  SPLIT: {sorted(group)} have no common commit")
            for f in sorted(group):
                cids = sorted(file_to_commits.get(f, set()))
                details_lines.append(f"    {f} -> {cids}")

    # Check each must-be-ordered pair
    for pair in must_be_ordered:
        if len(pair) != 2:
            continue
        dep_file, consumer_file = pair[0], pair[1]

        # Find the earliest commit index for the dependency file
        dep_commits = set()
        consumer_commits = set()
        for cid, cfiles in commit_files.items():
            if dep_file in cfiles:
                dep_commits.add(cid)
            if consumer_file in cfiles:
                consumer_commits.add(cid)

        if not dep_commits or not consumer_commits:
            details_lines.append(
                f"  WARN: order check skipped — {dep_file} or {consumer_file} not in plan"
            )
            continue

        # Dependency is satisfied if the earliest commit containing the
        # dependency file comes at or before the earliest commit containing
        # the consumer file (or they share a commit)
        dep_min_idx = min(commit_order.get(c, 999) for c in dep_commits)
        consumer_min_idx = min(commit_order.get(c, 999) for c in consumer_commits)

        if dep_min_idx <= consumer_min_idx:
            details_lines.append(
                f"  OK (order): {dep_file} (idx {dep_min_idx}) <= "
                f"{consumer_file} (idx {consumer_min_idx})"
            )
        else:
            all_passed = False
            details_lines.append(
                f"  BAD ORDER: {dep_file} (idx {dep_min_idx}) > "
                f"{consumer_file} (idx {consumer_min_idx}) — "
                f"consumer committed before its dependency"
            )

    # Build plan summary
    plan_summary = []
    for commit in plan.commits:
        files = sorted(commit_files.get(commit.id, set()))
        plan_summary.append({
            "id": commit.id,
            "type": commit.type,
            "scope": commit.scope,
            "title": commit.title,
            "hunks": commit.hunks,
            "files": files,
        })

    details_lines.append("")
    details_lines.append("  Plan:")
    for ps in plan_summary:
        details_lines.append(f"    {ps['id']}: {ps['type']}({ps['scope']}): {ps['title']}")
        details_lines.append(f"         files: {ps['files']}")
        details_lines.append(f"         hunks: {ps['hunks']}")

    return all_passed, "\n".join(details_lines), plan_summary


# ============================================================
# Single Test Runner
# ============================================================

def run_single_test(case: TestCaseData, provider) -> TestResult:
    """Run a single test case against the LLM.

    Args:
        case: The test case data.
        provider: The LLM provider instance.

    Returns:
        A TestResult object.
    """
    # Build prompt WITH file relationships
    prompt = build_compose_prompt(
        file_diffs=case.file_diffs,
        branch="feature/update",
        recent_commits=["Previous commit 1", "Previous commit 2"],
        style="blueprint",
        max_commits=6,
        file_relationships=case.file_relationships,
    )

    start_time = time.time()

    try:
        result = provider.generate_raw(
            system_prompt=COMPOSE_SYSTEM_PROMPT,
            user_prompt=prompt,
        )
        latency = time.time() - start_time

        plan_data = parse_json_response(result.raw_response)
        plan = ComposePlan(**plan_data)

        passed, details, plan_summary = check_coherence(
            plan, case.must_be_together, case.must_be_ordered, case.file_diffs,
        )

        return TestResult(
            case_id=case.id,
            case_name=case.name,
            language=case.language,
            difficulty=case.difficulty,
            category=case.category,
            passed=passed,
            num_files=case.num_files,
            num_hunks=case.num_hunks,
            num_commits_generated=len(plan.commits),
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_seconds=round(latency, 2),
            coherence_details=details,
            plan_summary=plan_summary,
        )

    except Exception as e:
        latency = time.time() - start_time
        return TestResult(
            case_id=case.id,
            case_name=case.name,
            language=case.language,
            difficulty=case.difficulty,
            category=case.category,
            passed=False,
            num_files=case.num_files,
            num_hunks=case.num_hunks,
            num_commits_generated=0,
            model=getattr(provider, "model", "unknown"),
            input_tokens=0,
            output_tokens=0,
            latency_seconds=round(latency, 2),
            coherence_details="",
            plan_summary=[],
            error=str(e),
        )


# ============================================================
# Results Storage
# ============================================================

def save_results(
    eval_dir: Path,
    results: list[TestResult],
    summary: EvalSummary,
) -> None:
    """Save detailed results and summary to the eval directory.

    Args:
        eval_dir: The timestamped eval directory.
        results: List of individual test results.
        summary: The overall summary.
    """
    eval_dir.mkdir(parents=True, exist_ok=True)

    # Save individual results
    for result in results:
        result_file = eval_dir / f"{result.case_id}.json"
        result_dict = {
            "case_id": result.case_id,
            "case_name": result.case_name,
            "language": result.language,
            "difficulty": result.difficulty,
            "category": result.category,
            "passed": result.passed,
            "num_files": result.num_files,
            "num_hunks": result.num_hunks,
            "num_commits_generated": result.num_commits_generated,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "latency_seconds": result.latency_seconds,
            "coherence_details": result.coherence_details,
            "plan_summary": result.plan_summary,
            "error": result.error,
        }
        result_file.write_text(json.dumps(result_dict, indent=2))

    # Save summary
    summary_file = eval_dir / "summary.json"
    summary_dict = {
        "timestamp": summary.timestamp,
        "provider": summary.provider,
        "model": summary.model,
        "total_cases": summary.total_cases,
        "passed": summary.passed,
        "failed": summary.failed,
        "errors": summary.errors,
        "pass_rate": summary.pass_rate,
        "total_input_tokens": summary.total_input_tokens,
        "total_output_tokens": summary.total_output_tokens,
        "total_latency_seconds": summary.total_latency_seconds,
        "results_by_language": summary.results_by_language,
        "results_by_difficulty": summary.results_by_difficulty,
        "results_by_category": summary.results_by_category,
        "results": [
            {
                "case_id": r.case_id,
                "case_name": r.case_name,
                "language": r.language,
                "difficulty": r.difficulty,
                "passed": r.passed,
                "error": r.error,
            }
            for r in results
        ],
    }
    summary_file.write_text(json.dumps(summary_dict, indent=2))


def build_summary(
    results: list[TestResult],
    provider_name: str,
    model_name: str,
    timestamp: str,
) -> EvalSummary:
    """Build an EvalSummary from a list of test results.

    Args:
        results: List of test results.
        provider_name: Name of the LLM provider.
        model_name: Name of the model.
        timestamp: Timestamp string.

    Returns:
        An EvalSummary object.
    """
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    errors = sum(1 for r in results if r.error)
    failed = total - passed

    # Group by language
    by_lang: dict[str, dict] = {}
    for r in results:
        lang = r.language
        if lang not in by_lang:
            by_lang[lang] = {"total": 0, "passed": 0, "failed": 0}
        by_lang[lang]["total"] += 1
        if r.passed:
            by_lang[lang]["passed"] += 1
        else:
            by_lang[lang]["failed"] += 1

    # Group by difficulty
    by_diff: dict[str, dict] = {}
    for r in results:
        diff = r.difficulty
        if diff not in by_diff:
            by_diff[diff] = {"total": 0, "passed": 0, "failed": 0}
        by_diff[diff]["total"] += 1
        if r.passed:
            by_diff[diff]["passed"] += 1
        else:
            by_diff[diff]["failed"] += 1

    # Group by category
    by_cat: dict[str, dict] = {}
    for r in results:
        cat = r.category
        if cat not in by_cat:
            by_cat[cat] = {"total": 0, "passed": 0, "failed": 0}
        by_cat[cat]["total"] += 1
        if r.passed:
            by_cat[cat]["passed"] += 1
        else:
            by_cat[cat]["failed"] += 1

    return EvalSummary(
        timestamp=timestamp,
        provider=provider_name,
        model=model_name,
        total_cases=total,
        passed=passed,
        failed=failed,
        errors=errors,
        pass_rate=round(passed / total * 100, 1) if total > 0 else 0.0,
        total_input_tokens=sum(r.input_tokens for r in results),
        total_output_tokens=sum(r.output_tokens for r in results),
        total_latency_seconds=round(sum(r.latency_seconds for r in results), 2),
        results_by_language=by_lang,
        results_by_difficulty=by_diff,
        results_by_category=by_cat,
    )


# ============================================================
# Pretty Printer
# ============================================================

def print_summary(summary: EvalSummary, results: list[TestResult]) -> None:
    """Print the evaluation summary to stdout."""
    print()
    print("=" * 72)
    print("  COMPOSE COHERENCE EVALUATION — SUMMARY")
    print("=" * 72)
    print()
    print(f"  Provider:  {summary.provider}")
    print(f"  Model:     {summary.model}")
    print(f"  Timestamp: {summary.timestamp}")
    print(f"  Cases:     {summary.total_cases}")
    print()

    # Results table
    print(f"  {'Status':<6}  {'Lang':<12}  {'Diff':<10}  {'Name'}")
    print(f"  {'------':<6}  {'----':<12}  {'----':<10}  {'----'}")
    for r in results:
        status = "PASS" if r.passed else ("ERR" if r.error else "FAIL")
        icon = "\u2705" if r.passed else ("\u26a0\ufe0f " if r.error else "\u274c")
        print(f"  {icon} {status:<4}  {r.language:<12}  {r.difficulty:<10}  {r.case_name}")
    print()

    # Overall
    print(f"  Overall: {summary.passed}/{summary.total_cases} passed "
          f"({summary.pass_rate}%)")
    if summary.errors > 0:
        print(f"  Errors:  {summary.errors}")
    print()

    # By language
    print("  By Language:")
    for lang, stats in sorted(summary.results_by_language.items()):
        rate = round(stats["passed"] / stats["total"] * 100) if stats["total"] > 0 else 0
        print(f"    {lang:<12}  {stats['passed']}/{stats['total']} ({rate}%)")
    print()

    # By difficulty
    print("  By Difficulty:")
    for diff, stats in sorted(summary.results_by_difficulty.items(),
                               key=lambda x: {"easy": 0, "medium": 1, "hard": 2, "very_hard": 3, "super_hard": 4, "hyper_hard": 5}.get(x[0], 99)):
        rate = round(stats["passed"] / stats["total"] * 100) if stats["total"] > 0 else 0
        print(f"    {diff:<12}  {stats['passed']}/{stats['total']} ({rate}%)")
    print()

    # Token usage
    print(f"  Tokens:  {summary.total_input_tokens:,} input / "
          f"{summary.total_output_tokens:,} output")
    print(f"  Latency: {summary.total_latency_seconds:.1f}s total "
          f"({summary.total_latency_seconds / max(summary.total_cases, 1):.1f}s avg)")
    print()
    print("=" * 72)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Compose coherence integration tests with live LLM API calls",
    )
    parser.add_argument(
        "--provider", default="google",
        help="LLM provider name (default: google)",
    )
    parser.add_argument(
        "--model", default="gemini-2.5-flash",
        help="Model name (default: gemini-2.5-flash)",
    )
    parser.add_argument(
        "--case", default=None,
        help="Run only a specific test case by ID",
    )
    parser.add_argument(
        '--diff_level', choices=['easy', 'medium', 'hard', 'very_hard', 'super_hard', 'hyper_hard'],
        default=None, help='Difference level (default: all levels)'
    )
    parser.add_argument(
        "--language", default=None,
        help="Filter test cases by language (e.g., python, typescript)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List available test cases and exit",
    )
    args = parser.parse_args()

    # Load all test cases
    all_cases = load_all_test_cases()
    if not all_cases:
        print(f"No test cases found in {DATA_DIR}")
        sys.exit(1)

    # Filter cases
    cases = all_cases
    if args.case:
        cases = [c for c in cases if c.id == args.case]
        if not cases:
            print(f"Test case '{args.case}' not found. Use --list to see available cases.")
            sys.exit(1)
    if args.language:
        cases = [c for c in cases if c.language == args.language.lower()]
        if not cases:
            print(f"No test cases found for language '{args.language}'.")
            sys.exit(1)
    if args.diff_level:
        cases = [c for c in cases if c.difficulty == args.diff_level]
        if not cases:
            print(f"No test cases found for difficulty '{args.diff_level}'.")
            sys.exit(1)

    # --list mode
    if args.list:
        print(f"\nAvailable test cases ({len(cases)}):\n")
        print(f"  {'ID':<40}  {'Lang':<12}  {'Diff':<10}  {'Files':>5}  {'Hunks':>5}  Name")
        print(f"  {'--':<40}  {'----':<12}  {'----':<10}  {'-----':>5}  {'-----':>5}  ----")
        for c in cases:
            print(f"  {c.id:<40}  {c.language:<12}  {c.difficulty:<10}  "
                  f"{c.num_files:>5}  {c.num_hunks:>5}  {c.name}")
        print()
        sys.exit(0)

    # Setup provider
    from hunknote.config import LLMProvider, load_config
    from hunknote.llm import get_provider

    load_config()

    try:
        provider_enum = LLMProvider(args.provider.lower())
    except ValueError:
        print(f"Unknown provider: {args.provider}")
        print(f"Valid providers: {[p.value for p in LLMProvider]}")
        sys.exit(1)

    provider = get_provider(provider=provider_enum, model=args.model)

    # Timestamp for this eval run
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    eval_dir = EVALS_DIR / timestamp

    # Print header
    print()
    print("=" * 72)
    print("  COMPOSE COHERENCE EVALUATION")
    print(f"  Provider: {args.provider} / {args.model}")
    print(f"  Cases:    {len(cases)}")
    print(f"  Eval dir: {eval_dir}")
    print("=" * 72)
    print()

    # Run tests
    results: list[TestResult] = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case.name}")
        print(f"  Language: {case.language} | Difficulty: {case.difficulty} | "
              f"Files: {case.num_files} | Hunks: {case.num_hunks}")
        print(f"  {case.description}")

        # Show relationships
        if case.file_relationships:
            print(f"  Relationships ({len(case.file_relationships)}):")
            for rel in case.file_relationships:
                if rel.kind == "direct":
                    print(f"    {rel.source} -> {rel.target}")
                else:
                    print(f"    {rel.source} -> {rel.target} (via {rel.via})")

        result = run_single_test(case, provider)
        results.append(result)

        # Print result
        if result.error:
            print(f"  Result: \u26a0\ufe0f  ERROR — {result.error}")
        elif result.passed:
            print(f"  Result: \u2705 PASSED ({result.num_commits_generated} commits, "
                  f"{result.latency_seconds}s, "
                  f"{result.input_tokens}+{result.output_tokens} tokens)")
        else:
            print(f"  Result: \u274c FAILED ({result.num_commits_generated} commits, "
                  f"{result.latency_seconds}s)")

        # Print coherence details
        if result.coherence_details:
            for line in result.coherence_details.split("\n"):
                print(f"  {line}")
        print()
        print("-" * 72)
        print()

    # Build and save summary
    summary = build_summary(results, args.provider, args.model, timestamp)
    save_results(eval_dir, results, summary)

    # Print summary
    print_summary(summary, results)

    print(f"\n  Detailed results saved to: {eval_dir}\n")

    # Exit with non-zero if any test failed
    sys.exit(0 if summary.failed == 0 else 1)


if __name__ == "__main__":
    main()

