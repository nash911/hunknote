"""Data models for the Compose Agent evaluation framework."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class DifficultyTier(Enum):
    """Difficulty tier based on hunk and file count."""

    TIER1 = 1  # 2-5 hunks, 1-2 files
    TIER2 = 2  # 5-15 hunks, 2-5 files
    TIER3 = 3  # 15-40 hunks, 5-15 files
    TIER4 = 4  # 40-100 hunks, 10-25 files
    TIER5 = 5  # 100+ hunks, 25+ files


class Language(Enum):
    """Supported programming languages for evaluation."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    GO = "go"
    RUST = "rust"
    JAVA = "java"
    CPP = "cpp"
    RUBY = "ruby"


# ── Test case definition ──


@dataclass
class BuildSystemConfig:
    """How to build and validate the target project."""

    type: str  # "python", "typescript", etc.
    install_commands: list[str]  # Commands to install deps in target venv
    check_command: str  # e.g. "python -m py_compile {file}"
    import_check: bool = True
    import_command: str = 'python -c "import {module}"'
    test_command: Optional[str] = None
    test_enabled: bool = False
    python_version_min: Optional[str] = None


@dataclass
class KnownDependency:
    """A known co-commit constraint in the test case."""

    description: str
    hunks_must_cocommit: list[str]  # Hunk IDs that must be in the same commit
    reason: str


@dataclass
class ReferenceCommit:
    """A single commit in the reference decomposition."""

    index: int
    message: str
    files: list[str]
    hunk_ids: list[str]


@dataclass
class TestCaseStats:
    """Statistics about a test case's diff."""

    total_hunks: int
    total_files: int
    reference_commit_count: int
    lines_added: int
    lines_removed: int


@dataclass
class TestCase:
    """A complete eval test case."""

    id: str  # e.g. "python_httpx_tier3_url_model"
    language: Language
    tier: DifficultyTier
    description: str
    source_repo: str  # GitHub URL
    source_commits: list[str]  # Original commit SHAs
    stats: TestCaseStats
    build_system: BuildSystemConfig
    known_dependencies: list[KnownDependency] = field(default_factory=list)
    reference_commits: list[ReferenceCommit] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @property
    def case_dir(self) -> Path:
        """Path to this test case's directory."""
        return (
            Path(__file__).parent
            / "test_cases"
            / "cases"
            / self.language.value
            / self.id
        )


# ── Eval results ──


@dataclass
class CommitValidation:
    """Validation result for a single commit in the agent's plan."""

    commit_index: int
    commit_id: str  # "C1", "C2", etc.
    patch_applies: bool
    syntax_valid: bool
    compile_passes: bool
    import_resolves: bool
    tests_pass: Optional[bool] = None
    errors: list[str] = field(default_factory=list)


@dataclass
class MechanicalResult:
    """Mechanical validation results for the full commit sequence."""

    full_sequence_valid: bool
    build_pass_rate: float
    patch_apply_rate: float
    import_integrity_rate: float
    test_pass_rate: Optional[float] = None
    final_state_matches: Optional[bool] = None  # Does worktree match expected after-state?
    final_state_diff: Optional[str] = None  # git diff summary if mismatch
    per_commit: list[CommitValidation] = field(default_factory=list)
    first_failure_index: Optional[int] = None


@dataclass
class SemanticScores:
    """Semantic quality scores for the agent's output."""

    reference_similarity: float  # ARI score (0-1)
    granularity: float  # Commit count deviation penalty (0-1)
    dependency_recall: float  # Fraction of known deps satisfied (0-1)
    cohesion: Optional[float] = None  # LLM-judge (0-1)
    separation: Optional[float] = None  # LLM-judge (0-1)
    ordering: Optional[float] = None  # LLM-judge (0-1)


@dataclass
class EvalCaseResult:
    """Complete eval result for one test case."""

    case_id: str
    tier: DifficultyTier = DifficultyTier.TIER1
    language: Language = Language.PYTHON
    mechanical: MechanicalResult = field(
        default_factory=lambda: MechanicalResult(
            full_sequence_valid=False,
            build_pass_rate=0.0,
            patch_apply_rate=0.0,
            import_integrity_rate=0.0,
        )
    )
    semantic: SemanticScores = field(
        default_factory=lambda: SemanticScores(
            reference_similarity=0.0,
            granularity=0.0,
            dependency_recall=0.0,
        )
    )
    overall_score: float = 0.0
    agent_commit_count: int = 0
    reference_commit_count: int = 0
    agent_trace_path: Optional[str] = None
    total_llm_calls: int = 0
    total_tokens: int = 0
    duration_s: float = 0.0
    error: Optional[str] = None


@dataclass
class EvalRunResult:
    """Complete eval result for one run of the suite."""

    run_id: str  # e.g. "eval_2025-03-10_14-30-00"
    timestamp: str
    agent_config: dict  # provider, model, max_retries, etc.
    suite: str  # "smoke", "standard", "full"
    cases: list[EvalCaseResult] = field(default_factory=list)

    def get_summary(self) -> dict:
        """Get aggregate summary statistics."""
        if not self.cases:
            return {"total": 0, "passed": 0, "failed": 0, "avg_score": 0.0}

        valid_cases = [c for c in self.cases if c.error is None]
        failed_cases = [c for c in self.cases if c.error is not None]
        scores = [c.overall_score for c in valid_cases]

        return {
            "total": len(self.cases),
            "passed": len(valid_cases),
            "failed": len(failed_cases),
            "avg_score": sum(scores) / len(scores) if scores else 0.0,
            "min_score": min(scores) if scores else 0.0,
            "max_score": max(scores) if scores else 0.0,
            "mechanical_pass_rate": (
                sum(1 for c in valid_cases if c.mechanical.full_sequence_valid)
                / len(valid_cases)
                if valid_cases
                else 0.0
            ),
        }

    def get_by_tier(self) -> dict[DifficultyTier, list[EvalCaseResult]]:
        """Group results by difficulty tier."""
        result: dict[DifficultyTier, list[EvalCaseResult]] = {}
        for case in self.cases:
            result.setdefault(case.tier, []).append(case)
        return result

    def get_by_language(self) -> dict[Language, list[EvalCaseResult]]:
        """Group results by language."""
        result: dict[Language, list[EvalCaseResult]] = {}
        for case in self.cases:
            result.setdefault(case.language, []).append(case)
        return result

    def get_failures(self) -> list[EvalCaseResult]:
        """Get cases that failed (error or mechanical failure)."""
        return [
            c
            for c in self.cases
            if c.error is not None or not c.mechanical.full_sequence_valid
        ]
