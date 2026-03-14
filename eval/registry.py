"""Test case discovery and loading from the file system."""

import fnmatch
import json
import logging
from pathlib import Path
from typing import Optional

from eval.config import EVAL_TEST_CASES_DIR, SUITES
from eval.models import (
    BuildSystemConfig,
    DifficultyTier,
    KnownDependency,
    Language,
    ReferenceCommit,
    TestCase,
    TestCaseStats,
)

logger = logging.getLogger(__name__)


def discover_cases(
    base_dir: Optional[Path] = None,
    language: Optional[Language] = None,
    tier: Optional[DifficultyTier] = None,
    tags: Optional[list[str]] = None,
) -> list[TestCase]:
    """Discover test cases matching the given filters.

    Scans {base_dir}/cases/{language}/ directories for case.json files.

    Args:
        base_dir: Root of test_cases/cases directory. Default: hunknote/eval/test_cases/cases/
        language: Filter by language (None = all).
        tier: Filter by tier (None = all).
        tags: Filter by tags (all specified tags must be present).

    Returns:
        List of TestCase objects sorted by (language, tier, id).
    """
    base = base_dir or EVAL_TEST_CASES_DIR
    cases: list[TestCase] = []

    if not base.exists():
        logger.warning("Test cases directory does not exist: %s", base)
        return cases

    # Scan language directories
    lang_dirs = [base / lang.value for lang in Language] if language is None else [base / language.value]

    for lang_dir in lang_dirs:
        if not lang_dir.is_dir():
            continue
        for case_dir in sorted(lang_dir.iterdir()):
            if not case_dir.is_dir():
                continue
            case_json = case_dir / "case.json"
            if not case_json.exists():
                continue
            try:
                case = load_case(case_dir)
            except Exception as e:
                logger.warning("Failed to load case from %s: %s", case_dir, e)
                continue

            # Apply filters
            if tier is not None and case.tier != tier:
                continue
            if tags is not None and not all(t in case.tags for t in tags):
                continue

            cases.append(case)

    cases.sort(key=lambda c: (c.language.value, c.tier.value, c.id))
    return cases


def load_case(case_dir: Path) -> TestCase:
    """Load a single test case from its directory.

    Args:
        case_dir: Path to the test case directory containing case.json.

    Returns:
        TestCase object.

    Raises:
        FileNotFoundError: If case.json does not exist.
        ValueError: If case.json is malformed.
    """
    case_json = case_dir / "case.json"
    if not case_json.exists():
        raise FileNotFoundError(f"No case.json found in {case_dir}")

    with open(case_json) as f:
        data = json.load(f)

    # Parse build system config
    bs_data = data["build_system"]
    build_system = BuildSystemConfig(
        type=bs_data["type"],
        install_commands=bs_data.get("install_commands", []),
        check_command=bs_data.get("check_command", "python -m py_compile {file}"),
        import_check=bs_data.get("import_check", True),
        import_command=bs_data.get("import_command", 'python -c "import {module}"'),
        test_command=bs_data.get("test_command"),
        test_enabled=bs_data.get("test_enabled", False),
        python_version_min=bs_data.get("python_version_min"),
    )

    # Parse stats
    stats_data = data["stats"]
    stats = TestCaseStats(
        total_hunks=stats_data["total_hunks"],
        total_files=stats_data["total_files"],
        reference_commit_count=stats_data["reference_commit_count"],
        lines_added=stats_data.get("lines_added", 0),
        lines_removed=stats_data.get("lines_removed", 0),
    )

    # Parse known dependencies
    known_deps = [
        KnownDependency(
            description=kd["description"],
            hunks_must_cocommit=kd["hunks_must_cocommit"],
            reason=kd["reason"],
        )
        for kd in data.get("known_dependencies", [])
    ]

    # Parse reference commits (from reference.json if it exists, or inline)
    reference_commits: list[ReferenceCommit] = []
    ref_json = case_dir / "reference.json"
    ref_data_list = data.get("reference_commits", [])

    if ref_json.exists() and not ref_data_list:
        with open(ref_json) as f:
            ref_data_list = json.load(f).get("commits", [])

    for rc in ref_data_list:
        reference_commits.append(
            ReferenceCommit(
                index=rc["index"],
                message=rc["message"],
                files=rc["files"],
                hunk_ids=rc["hunk_ids"],
            )
        )

    return TestCase(
        id=data["id"],
        language=Language(data["language"]),
        tier=DifficultyTier(data["tier"]),
        description=data.get("description", ""),
        source_repo=data.get("source_repo", ""),
        source_commits=data.get("source_commits", []),
        stats=stats,
        build_system=build_system,
        known_dependencies=known_deps,
        reference_commits=reference_commits,
        tags=data.get("tags", []),
    )


def filter_cases_by_suite(
    cases: list[TestCase], suite: str
) -> list[TestCase]:
    """Filter cases by suite definition (glob patterns on case IDs).

    Args:
        cases: All available test cases.
        suite: Suite name ("smoke", "standard", "full").

    Returns:
        Filtered list of test cases.
    """
    patterns = SUITES.get(suite, ["*"])

    if suite == "smoke":
        # For smoke suite, only include one case per language/tier to keep it small and fast
        seen = set()
        filtered = []
        for c in cases:
            key = (c.language, c.tier)
            if key not in seen and any(fnmatch.fnmatch(c.id, pat) for pat in patterns):
                filtered.append(c)
                seen.add(key)
        return filtered
    else:  # Standard and full suites
        # Include all cases matching the patterns
        filtered = []
        for c in cases:
            if any(fnmatch.fnmatch(c.id, pat) for pat in patterns):
                filtered.append(c)
        return filtered


def get_suites() -> dict[str, list[str]]:
    """Return predefined suite definitions.

    Returns:
        Dict mapping suite name to list of glob patterns.
    """
    return dict(SUITES)
