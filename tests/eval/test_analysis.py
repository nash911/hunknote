"""Tests for eval.analysis — report generation and run_analysis."""

import json
from pathlib import Path

import pytest

from eval.analysis import (
    generate_analysis_report,
    generate_terminal_report,
    generate_web_report,
    run_analysis,
)
from eval.models import (
    CommitValidation,
    DifficultyTier,
    EvalCaseResult,
    EvalRunResult,
    Language,
    MechanicalResult,
    SemanticScores,
)
from eval.reporting import save_result


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def passing_case():
    """A fully passing eval case."""
    return EvalCaseResult(
        case_id="python_test_tier1_passing",
        tier=DifficultyTier.TIER1,
        language=Language.PYTHON,
        mechanical=MechanicalResult(
            full_sequence_valid=True,
            build_pass_rate=1.0,
            patch_apply_rate=1.0,
            import_integrity_rate=1.0,
            test_pass_rate=1.0,
            final_state_matches=True,
            per_commit=[
                CommitValidation(
                    commit_index=0, commit_id="C1",
                    patch_applies=True, syntax_valid=True,
                    compile_passes=True, import_resolves=True,
                    tests_pass=True,
                ),
                CommitValidation(
                    commit_index=1, commit_id="C2",
                    patch_applies=True, syntax_valid=True,
                    compile_passes=True, import_resolves=True,
                    tests_pass=True,
                ),
            ],
        ),
        semantic=SemanticScores(
            reference_similarity=0.5,
            granularity=0.8,
            dependency_recall=1.0,
        ),
        overall_score=0.85,
        agent_commit_count=2,
        reference_commit_count=1,
        total_llm_calls=1,
        total_tokens=3000,
        duration_s=45.0,
    )


@pytest.fixture
def failing_case():
    """An eval case with mechanical failures."""
    return EvalCaseResult(
        case_id="python_test_tier2_failing",
        tier=DifficultyTier.TIER2,
        language=Language.PYTHON,
        mechanical=MechanicalResult(
            full_sequence_valid=False,
            build_pass_rate=1.0,
            patch_apply_rate=1.0,
            import_integrity_rate=0.5,
            test_pass_rate=0.5,
            final_state_matches=True,
            per_commit=[
                CommitValidation(
                    commit_index=0, commit_id="C1",
                    patch_applies=True, syntax_valid=True,
                    compile_passes=True, import_resolves=False,
                    tests_pass=None,
                    errors=["Import failed for module_x: NameError"],
                ),
                CommitValidation(
                    commit_index=1, commit_id="C2",
                    patch_applies=True, syntax_valid=True,
                    compile_passes=True, import_resolves=True,
                    tests_pass=False,
                    errors=["Tests failed:\n=== FAILURES ===\n___ test_foo ___\nAssertionError"],
                ),
                CommitValidation(
                    commit_index=2, commit_id="C3",
                    patch_applies=True, syntax_valid=True,
                    compile_passes=True, import_resolves=True,
                    tests_pass=True,
                ),
            ],
        ),
        semantic=SemanticScores(
            reference_similarity=0.0,
            granularity=0.36,
            dependency_recall=1.0,
        ),
        overall_score=0.72,
        agent_commit_count=3,
        reference_commit_count=1,
        total_llm_calls=1,
        total_tokens=5000,
        duration_s=90.0,
    )


@pytest.fixture
def error_case():
    """An eval case that errored out."""
    return EvalCaseResult(
        case_id="python_test_tier3_error",
        tier=DifficultyTier.TIER3,
        language=Language.PYTHON,
        error="Dependency installation failed",
    )


@pytest.fixture
def multi_case_result(passing_case, failing_case, error_case):
    """A run result with multiple cases across tiers."""
    return EvalRunResult(
        run_id="eval_2026-03-14_test",
        timestamp="2026-03-14_12-00-00",
        agent_config={
            "provider": "google",
            "model": "gemini-2.5-flash",
            "use_agent": False,
        },
        suite="test",
        cases=[passing_case, failing_case, error_case],
    )


@pytest.fixture
def single_pass_result(passing_case):
    """A run result with a single passing case."""
    return EvalRunResult(
        run_id="eval_single",
        timestamp="2026-03-14_12-00-00",
        agent_config={"provider": "openai", "model": "gpt-4o"},
        suite="smoke",
        cases=[passing_case],
    )


# ── Markdown report ────────────────────────────────────────────────────────


class TestGenerateAnalysisReport:
    def test_returns_string(self, multi_case_result):
        report = generate_analysis_report(multi_case_result)
        assert isinstance(report, str)

    def test_contains_run_id(self, multi_case_result):
        report = generate_analysis_report(multi_case_result)
        assert multi_case_result.run_id in report

    def test_contains_aggregate_summary(self, multi_case_result):
        report = generate_analysis_report(multi_case_result)
        assert "Aggregate Summary" in report

    def test_contains_per_tier_breakdown(self, multi_case_result):
        report = generate_analysis_report(multi_case_result)
        assert "Per-Tier Breakdown" in report
        assert "Tier 1" in report
        assert "Tier 2" in report

    def test_contains_per_case_details(self, multi_case_result):
        report = generate_analysis_report(multi_case_result)
        for case in multi_case_result.cases:
            assert case.case_id in report

    def test_contains_failure_analysis(self, multi_case_result):
        report = generate_analysis_report(multi_case_result)
        assert "Failure Analysis" in report

    def test_shows_agent_mode(self, multi_case_result):
        report = generate_analysis_report(multi_case_result)
        assert "Single-shot" in report

    def test_shows_per_commit_breakdown(self, multi_case_result):
        report = generate_analysis_report(multi_case_result)
        assert "Per-Commit Breakdown" in report
        assert "C1" in report

    def test_single_passing_case(self, single_pass_result):
        report = generate_analysis_report(single_pass_result)
        assert "✅" in report
        assert "python_test_tier1_passing" in report


# ── Terminal report ─────────────────────────────────────────────────────────


class TestGenerateTerminalReport:
    def test_returns_string(self, multi_case_result):
        report = generate_terminal_report(multi_case_result)
        assert isinstance(report, str)

    def test_contains_header(self, multi_case_result):
        report = generate_terminal_report(multi_case_result)
        assert "Evaluation Analysis Report" in report

    def test_contains_run_id(self, multi_case_result):
        report = generate_terminal_report(multi_case_result)
        assert multi_case_result.run_id in report

    def test_contains_summary_box(self, multi_case_result):
        report = generate_terminal_report(multi_case_result)
        assert "Summary" in report
        assert "Cases" in report
        assert "Avg Score" in report

    def test_contains_per_tier_section(self, multi_case_result):
        report = generate_terminal_report(multi_case_result)
        assert "Per-Tier Breakdown" in report

    def test_contains_per_case_section(self, multi_case_result):
        report = generate_terminal_report(multi_case_result)
        assert "Per-Case Results" in report

    def test_contains_legend(self, multi_case_result):
        report = generate_terminal_report(multi_case_result)
        assert "Legend" in report
        assert "all pass" in report
        assert "tests fail" in report
        assert "build/import fail" in report

    def test_contains_commit_dots(self, multi_case_result):
        report = generate_terminal_report(multi_case_result)
        assert "●" in report

    def test_contains_failure_digest(self, multi_case_result):
        report = generate_terminal_report(multi_case_result)
        assert "Failure Digest" in report

    def test_all_pass_shows_no_failure_digest(self, single_pass_result):
        report = generate_terminal_report(single_pass_result)
        assert "All cases passed" in report

    def test_contains_ansi_codes(self, multi_case_result):
        report = generate_terminal_report(multi_case_result)
        assert "\033[" in report  # ANSI escape


# ── Web report ──────────────────────────────────────────────────────────────


class TestGenerateWebReport:
    def test_returns_string(self, multi_case_result):
        report = generate_web_report(multi_case_result)
        assert isinstance(report, str)

    def test_is_valid_html(self, multi_case_result):
        report = generate_web_report(multi_case_result)
        assert report.strip().startswith("<!DOCTYPE html>") or report.strip().startswith("<html")
        assert "</html>" in report

    def test_contains_data_json(self, multi_case_result):
        report = generate_web_report(multi_case_result)
        assert "const DATA" in report

    def test_contains_case_ids(self, multi_case_result):
        report = generate_web_report(multi_case_result)
        for case in multi_case_result.cases:
            assert case.case_id in report

    def test_contains_run_id(self, multi_case_result):
        report = generate_web_report(multi_case_result)
        assert multi_case_result.run_id in report

    def test_single_passing_case(self, single_pass_result):
        report = generate_web_report(single_pass_result)
        assert "</html>" in report
        assert "python_test_tier1_passing" in report


# ── run_analysis ────────────────────────────────────────────────────────────


class TestRunAnalysis:
    def test_creates_markdown_report(self, tmp_path, multi_case_result):
        result_path = save_result(multi_case_result, tmp_path)
        md_path, terminal_report = run_analysis(result_path)
        assert md_path.exists()
        assert md_path.name == "eval_analysis.md"

    def test_returns_terminal_report(self, tmp_path, multi_case_result):
        result_path = save_result(multi_case_result, tmp_path)
        _, terminal_report = run_analysis(result_path)
        assert isinstance(terminal_report, str)
        assert "Evaluation Analysis Report" in terminal_report

    def test_web_flag_creates_html(self, tmp_path, multi_case_result):
        result_path = save_result(multi_case_result, tmp_path)
        md_path, _ = run_analysis(result_path, web=True)
        html_path = md_path.parent / "eval_dashboard.html"
        assert html_path.exists()

    def test_no_web_flag_no_html(self, tmp_path, multi_case_result):
        result_path = save_result(multi_case_result, tmp_path)
        md_path, _ = run_analysis(result_path, web=False)
        html_path = md_path.parent / "eval_dashboard.html"
        assert not html_path.exists()

    def test_custom_output_dir(self, tmp_path, multi_case_result):
        result_path = save_result(multi_case_result, tmp_path)
        out_dir = tmp_path / "custom_output"
        md_path, _ = run_analysis(result_path, output_dir=out_dir)
        assert md_path.parent == out_dir
        assert md_path.exists()

    def test_markdown_content_matches_generate(self, tmp_path, multi_case_result):
        result_path = save_result(multi_case_result, tmp_path)
        md_path, _ = run_analysis(result_path)
        content = md_path.read_text()
        assert multi_case_result.run_id in content

