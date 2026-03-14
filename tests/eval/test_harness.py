"""Tests for eval.harness — helper/utility functions."""

import pytest

from eval.harness import _error_result
from eval.models import (
    BuildSystemConfig,
    DifficultyTier,
    EvalCaseResult,
    Language,
    TestCase,
    TestCaseStats,
)


@pytest.fixture
def test_case():
    """A minimal TestCase for testing harness helpers."""
    return TestCase(
        id="python_test_tier1_sample",
        language=Language.PYTHON,
        tier=DifficultyTier.TIER1,
        description="Sample test",
        source_repo="https://github.com/test/repo",
        source_commits=["abc123"],
        stats=TestCaseStats(
            total_hunks=3, total_files=2,
            reference_commit_count=1,
            lines_added=10, lines_removed=5,
        ),
        build_system=BuildSystemConfig(
            type="python",
            install_commands=["pip install -e ."],
            check_command="python -m py_compile {file}",
        ),
    )


class TestErrorResult:
    def test_returns_eval_case_result(self, test_case):
        result = _error_result(test_case, "something broke")
        assert isinstance(result, EvalCaseResult)

    def test_sets_case_id(self, test_case):
        result = _error_result(test_case, "error")
        assert result.case_id == test_case.id

    def test_sets_tier(self, test_case):
        result = _error_result(test_case, "error")
        assert result.tier == test_case.tier

    def test_sets_language(self, test_case):
        result = _error_result(test_case, "error")
        assert result.language == test_case.language

    def test_sets_error_message(self, test_case):
        result = _error_result(test_case, "Dependency installation failed")
        assert result.error == "Dependency installation failed"

    def test_overall_score_is_zero(self, test_case):
        result = _error_result(test_case, "error")
        assert result.overall_score == 0.0

    def test_mechanical_is_default(self, test_case):
        result = _error_result(test_case, "error")
        assert result.mechanical is not None
        assert result.mechanical.full_sequence_valid is False

    def test_different_tiers(self):
        for tier in DifficultyTier:
            tc = TestCase(
                id=f"test_tier{tier.value}",
                language=Language.PYTHON,
                tier=tier,
                description="Test",
                source_repo="https://github.com/test/repo",
                source_commits=["abc123"],
                stats=TestCaseStats(
                    total_hunks=3, total_files=2,
                    reference_commit_count=1,
                    lines_added=10, lines_removed=5,
                ),
                build_system=BuildSystemConfig(
                    type="python",
                    install_commands=["pip install -e ."],
                    check_command="python -m py_compile {file}",
                ),
            )
            result = _error_result(tc, "error")
            assert result.tier == tier

