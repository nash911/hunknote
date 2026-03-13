"""Tests for eval data models."""

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


class TestDifficultyTier:
    def test_tier_values(self):
        assert DifficultyTier.TIER1.value == 1
        assert DifficultyTier.TIER5.value == 5

    def test_tier_from_value(self):
        assert DifficultyTier(3) == DifficultyTier.TIER3


class TestLanguage:
    def test_language_values(self):
        assert Language.PYTHON.value == "python"
        assert Language.TYPESCRIPT.value == "typescript"

    def test_language_from_value(self):
        assert Language("go") == Language.GO


class TestBuildSystemConfig:
    def test_defaults(self):
        config = BuildSystemConfig(
            type="python",
            install_commands=["pip install -e ."],
            check_command="python -m py_compile {file}",
        )
        assert config.import_check is True
        assert config.test_enabled is False
        assert config.test_command is None
        assert config.python_version_min is None


class TestTestCase:
    def test_case_dir_property(self, sample_test_case):
        case_dir = sample_test_case.case_dir
        assert "eval" in str(case_dir)
        assert sample_test_case.language.value in str(case_dir)
        assert sample_test_case.id in str(case_dir)

    def test_default_lists(self):
        case = TestCase(
            id="test",
            language=Language.PYTHON,
            tier=DifficultyTier.TIER1,
            description="",
            source_repo="",
            source_commits=[],
            stats=TestCaseStats(0, 0, 0, 0, 0),
            build_system=BuildSystemConfig("python", [], ""),
        )
        assert case.known_dependencies == []
        assert case.reference_commits == []
        assert case.tags == []


class TestCommitValidation:
    def test_defaults(self):
        cv = CommitValidation(
            commit_index=0,
            commit_id="C1",
            patch_applies=True,
            syntax_valid=True,
            compile_passes=True,
            import_resolves=True,
        )
        assert cv.tests_pass is None
        assert cv.errors == []


class TestMechanicalResult:
    def test_default_fields(self):
        result = MechanicalResult(
            full_sequence_valid=False,
            build_pass_rate=0.5,
            patch_apply_rate=1.0,
            import_integrity_rate=0.8,
        )
        assert result.test_pass_rate is None
        assert result.per_commit == []
        assert result.first_failure_index is None


class TestSemanticScores:
    def test_default_judge_scores(self):
        scores = SemanticScores(
            reference_similarity=0.9,
            granularity=0.8,
            dependency_recall=1.0,
        )
        assert scores.cohesion is None
        assert scores.separation is None
        assert scores.ordering is None


class TestEvalCaseResult:
    def test_error_result(self):
        result = EvalCaseResult(case_id="test", error="something failed")
        assert result.error == "something failed"
        assert result.overall_score == 0.0

    def test_defaults(self):
        result = EvalCaseResult(case_id="test")
        assert result.mechanical.full_sequence_valid is False
        assert result.semantic.reference_similarity == 0.0


class TestEvalRunResult:
    def test_get_summary_empty(self):
        result = EvalRunResult(
            run_id="test",
            timestamp="now",
            agent_config={},
            suite="test",
        )
        summary = result.get_summary()
        assert summary["total"] == 0
        assert summary["avg_score"] == 0.0

    def test_get_summary(self, sample_eval_run_result):
        summary = sample_eval_run_result.get_summary()
        assert summary["total"] == 1
        assert summary["passed"] == 1
        assert summary["failed"] == 0
        assert summary["avg_score"] > 0

    def test_get_by_tier(self, sample_eval_run_result):
        by_tier = sample_eval_run_result.get_by_tier()
        assert DifficultyTier.TIER2 in by_tier
        assert len(by_tier[DifficultyTier.TIER2]) == 1

    def test_get_by_language(self, sample_eval_run_result):
        by_lang = sample_eval_run_result.get_by_language()
        assert Language.PYTHON in by_lang

    def test_get_failures_none(self, sample_eval_run_result):
        # The sample has full_sequence_valid=True, so no failures
        failures = sample_eval_run_result.get_failures()
        assert len(failures) == 0

    def test_get_failures_with_error(self):
        result = EvalRunResult(
            run_id="test",
            timestamp="now",
            agent_config={},
            suite="test",
            cases=[
                EvalCaseResult(case_id="ok", mechanical=MechanicalResult(
                    full_sequence_valid=True,
                    build_pass_rate=1.0,
                    patch_apply_rate=1.0,
                    import_integrity_rate=1.0,
                )),
                EvalCaseResult(case_id="fail", error="boom"),
            ],
        )
        failures = result.get_failures()
        assert len(failures) == 1
        assert failures[0].case_id == "fail"
