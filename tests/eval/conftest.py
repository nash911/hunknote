"""Shared fixtures for eval module tests."""

import json
import tempfile
from pathlib import Path

import pytest

from eval.models import (
    BuildSystemConfig,
    CommitValidation,
    DifficultyTier,
    EvalCaseResult,
    EvalRunResult,
    KnownDependency,
    Language,
    MechanicalResult,
    ReferenceCommit,
    SemanticScores,
    TestCase,
    TestCaseStats,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_build_system():
    """Sample Python build system config."""
    return BuildSystemConfig(
        type="python",
        install_commands=["pip install -e ."],
        check_command="python -m py_compile {file}",
        import_check=True,
        test_command="python -m pytest tests/ -x",
        test_enabled=False,
    )


@pytest.fixture
def sample_stats():
    """Sample test case stats."""
    return TestCaseStats(
        total_hunks=10,
        total_files=3,
        reference_commit_count=3,
        lines_added=50,
        lines_removed=20,
    )


@pytest.fixture
def sample_known_dep():
    """Sample known dependency constraint."""
    return KnownDependency(
        description="Function rename + test update",
        hunks_must_cocommit=["H1_abc", "H5_def"],
        reason="Test references renamed function",
    )


@pytest.fixture
def sample_reference_commits():
    """Sample reference commits."""
    return [
        ReferenceCommit(
            index=0,
            message="Refactor models",
            files=["src/models.py"],
            hunk_ids=["H1_abc", "H2_bcd"],
        ),
        ReferenceCommit(
            index=1,
            message="Update tests",
            files=["tests/test_models.py"],
            hunk_ids=["H3_cde", "H4_def"],
        ),
        ReferenceCommit(
            index=2,
            message="Fix imports",
            files=["src/utils.py", "tests/test_utils.py"],
            hunk_ids=["H5_efg", "H6_fgh"],
        ),
    ]


@pytest.fixture
def sample_test_case(sample_build_system, sample_stats, sample_known_dep, sample_reference_commits):
    """Sample test case."""
    return TestCase(
        id="python_test_tier2_sample",
        language=Language.PYTHON,
        tier=DifficultyTier.TIER2,
        description="Sample test case for unit tests",
        source_repo="https://github.com/example/repo",
        source_commits=["abc123", "def456", "ghi789"],
        stats=sample_stats,
        build_system=sample_build_system,
        known_dependencies=[sample_known_dep],
        reference_commits=sample_reference_commits,
        tags=["test", "sample"],
    )


@pytest.fixture
def sample_case_dir(temp_dir, sample_test_case):
    """Create a sample test case directory with case.json."""
    case_dir = temp_dir / sample_test_case.language.value / sample_test_case.id
    case_dir.mkdir(parents=True)

    case_json = {
        "id": sample_test_case.id,
        "language": sample_test_case.language.value,
        "tier": sample_test_case.tier.value,
        "description": sample_test_case.description,
        "source_repo": sample_test_case.source_repo,
        "source_commits": sample_test_case.source_commits,
        "stats": {
            "total_hunks": sample_test_case.stats.total_hunks,
            "total_files": sample_test_case.stats.total_files,
            "reference_commit_count": sample_test_case.stats.reference_commit_count,
            "lines_added": sample_test_case.stats.lines_added,
            "lines_removed": sample_test_case.stats.lines_removed,
        },
        "build_system": {
            "type": sample_test_case.build_system.type,
            "install_commands": sample_test_case.build_system.install_commands,
            "check_command": sample_test_case.build_system.check_command,
            "import_check": sample_test_case.build_system.import_check,
            "test_command": sample_test_case.build_system.test_command,
            "test_enabled": sample_test_case.build_system.test_enabled,
        },
        "known_dependencies": [
            {
                "description": kd.description,
                "hunks_must_cocommit": kd.hunks_must_cocommit,
                "reason": kd.reason,
            }
            for kd in sample_test_case.known_dependencies
        ],
        "reference_commits": [
            {
                "index": rc.index,
                "message": rc.message,
                "files": rc.files,
                "hunk_ids": rc.hunk_ids,
            }
            for rc in sample_test_case.reference_commits
        ],
        "tags": sample_test_case.tags,
    }

    with open(case_dir / "case.json", "w") as f:
        json.dump(case_json, f, indent=2)

    return temp_dir  # Return the base dir (cases root)


@pytest.fixture
def sample_mechanical_result():
    """Sample passing mechanical result."""
    return MechanicalResult(
        full_sequence_valid=True,
        build_pass_rate=1.0,
        patch_apply_rate=1.0,
        import_integrity_rate=1.0,
        per_commit=[
            CommitValidation(
                commit_index=0,
                commit_id="C1",
                patch_applies=True,
                syntax_valid=True,
                compile_passes=True,
                import_resolves=True,
            ),
            CommitValidation(
                commit_index=1,
                commit_id="C2",
                patch_applies=True,
                syntax_valid=True,
                compile_passes=True,
                import_resolves=True,
            ),
        ],
    )


@pytest.fixture
def sample_semantic_scores():
    """Sample semantic scores."""
    return SemanticScores(
        reference_similarity=0.85,
        granularity=0.9,
        dependency_recall=1.0,
    )


@pytest.fixture
def sample_eval_case_result(sample_mechanical_result, sample_semantic_scores):
    """Sample eval case result."""
    return EvalCaseResult(
        case_id="python_test_tier2_sample",
        tier=DifficultyTier.TIER2,
        language=Language.PYTHON,
        mechanical=sample_mechanical_result,
        semantic=sample_semantic_scores,
        overall_score=0.85,
        agent_commit_count=3,
        reference_commit_count=3,
        total_llm_calls=2,
        total_tokens=5000,
        duration_s=12.5,
    )


@pytest.fixture
def sample_eval_run_result(sample_eval_case_result):
    """Sample eval run result."""
    return EvalRunResult(
        run_id="eval_2025-03-10_14-30-00",
        timestamp="2025-03-10_14-30-00",
        agent_config={"provider": "google", "model": "gemini-2.0-flash"},
        suite="standard",
        cases=[sample_eval_case_result],
    )
