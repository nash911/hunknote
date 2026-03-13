"""Tests for reporting and regression tracking."""

import json

import pytest

from eval.models import (
    DifficultyTier,
    EvalCaseResult,
    EvalRunResult,
    Language,
    MechanicalResult,
    SemanticScores,
)
from eval.reporting import (
    compare_runs,
    generate_report,
    load_result,
    save_result,
)


class TestGenerateReport:
    def test_generates_markdown(self, sample_eval_run_result):
        report = generate_report(sample_eval_run_result)
        assert "# Eval Report:" in report
        assert "Summary" in report
        assert "Case Details" in report
        assert sample_eval_run_result.run_id in report

    def test_includes_case_ids(self, sample_eval_run_result):
        report = generate_report(sample_eval_run_result)
        for case in sample_eval_run_result.cases:
            assert case.case_id in report

    def test_failures_section(self):
        result = EvalRunResult(
            run_id="test",
            timestamp="now",
            agent_config={},
            suite="test",
            cases=[EvalCaseResult(case_id="broken", error="boom")],
        )
        report = generate_report(result)
        assert "Failures" in report
        assert "broken" in report
        assert "boom" in report


class TestSaveAndLoadResult:
    def test_roundtrip(self, temp_dir, sample_eval_run_result):
        path = save_result(sample_eval_run_result, temp_dir)
        assert path.exists()

        loaded = load_result(path)
        assert loaded.run_id == sample_eval_run_result.run_id
        assert loaded.timestamp == sample_eval_run_result.timestamp
        assert loaded.suite == sample_eval_run_result.suite
        assert len(loaded.cases) == len(sample_eval_run_result.cases)

    def test_preserves_case_data(self, temp_dir, sample_eval_run_result):
        path = save_result(sample_eval_run_result, temp_dir)
        loaded = load_result(path)

        orig = sample_eval_run_result.cases[0]
        loaded_case = loaded.cases[0]

        assert loaded_case.case_id == orig.case_id
        assert loaded_case.tier == orig.tier
        assert loaded_case.language == orig.language
        assert loaded_case.overall_score == orig.overall_score
        assert loaded_case.mechanical.full_sequence_valid == orig.mechanical.full_sequence_valid
        assert loaded_case.semantic.reference_similarity == orig.semantic.reference_similarity

    def test_preserves_per_commit(self, temp_dir, sample_eval_run_result):
        path = save_result(sample_eval_run_result, temp_dir)
        loaded = load_result(path)

        orig_commits = sample_eval_run_result.cases[0].mechanical.per_commit
        loaded_commits = loaded.cases[0].mechanical.per_commit

        assert len(loaded_commits) == len(orig_commits)
        assert loaded_commits[0].commit_id == orig_commits[0].commit_id
        assert loaded_commits[0].patch_applies == orig_commits[0].patch_applies


class TestCompareRuns:
    def _make_result(self, case_id, score, valid=True, error=None):
        return EvalCaseResult(
            case_id=case_id,
            tier=DifficultyTier.TIER2,
            language=Language.PYTHON,
            mechanical=MechanicalResult(
                full_sequence_valid=valid,
                build_pass_rate=1.0 if valid else 0.0,
                patch_apply_rate=1.0,
                import_integrity_rate=1.0,
            ),
            semantic=SemanticScores(
                reference_similarity=score,
                granularity=score,
                dependency_recall=score,
            ),
            overall_score=score,
            error=error,
        )

    def _make_run(self, run_id, cases):
        return EvalRunResult(
            run_id=run_id,
            timestamp="now",
            agent_config={},
            suite="test",
            cases=cases,
        )

    def test_no_regressions(self):
        baseline = self._make_run("b", [self._make_result("c1", 0.8)])
        current = self._make_run("c", [self._make_result("c1", 0.9)])
        comparison = compare_runs(current, baseline)
        assert len(comparison["new_failures"]) == 0
        assert len(comparison["score_regressions"]) == 0
        assert len(comparison["score_improvements"]) == 1

    def test_detects_new_failure(self):
        baseline = self._make_run("b", [self._make_result("c1", 0.8, valid=True)])
        current = self._make_run("c", [self._make_result("c1", 0.3, valid=False)])
        comparison = compare_runs(current, baseline)
        assert "c1" in comparison["new_failures"]

    def test_detects_new_pass(self):
        baseline = self._make_run("b", [self._make_result("c1", 0.3, valid=False)])
        current = self._make_run("c", [self._make_result("c1", 0.8, valid=True)])
        comparison = compare_runs(current, baseline)
        assert "c1" in comparison["new_passes"]

    def test_detects_score_regression(self):
        baseline = self._make_run("b", [self._make_result("c1", 0.9)])
        current = self._make_run("c", [self._make_result("c1", 0.7)])
        comparison = compare_runs(current, baseline, regression_threshold=0.05)
        assert len(comparison["score_regressions"]) == 1

    def test_only_in_baseline(self):
        baseline = self._make_run("b", [
            self._make_result("c1", 0.8),
            self._make_result("c2", 0.7),
        ])
        current = self._make_run("c", [self._make_result("c1", 0.8)])
        comparison = compare_runs(current, baseline)
        assert "c2" in comparison["only_in_baseline"]

    def test_only_in_current(self):
        baseline = self._make_run("b", [self._make_result("c1", 0.8)])
        current = self._make_run("c", [
            self._make_result("c1", 0.8),
            self._make_result("c2", 0.9),
        ])
        comparison = compare_runs(current, baseline)
        assert "c2" in comparison["only_in_current"]
