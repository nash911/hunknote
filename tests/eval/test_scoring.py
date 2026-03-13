"""Tests for semantic quality scoring."""

import math

import pytest

from eval.models import (
    KnownDependency,
    MechanicalResult,
    SemanticScores,
)
from eval.scoring import (
    compute_dependency_recall,
    compute_granularity_score,
    compute_overall_score,
    compute_reference_similarity,
)


class TestComputeReferenceSimilarity:
    def test_perfect_match(self):
        agent = {"H1": "C1", "H2": "C1", "H3": "C2"}
        ref = {"H1": "R1", "H2": "R1", "H3": "R2"}
        score = compute_reference_similarity(agent, ref)
        assert score == 1.0

    def test_completely_different(self):
        agent = {"H1": "C1", "H2": "C2", "H3": "C3"}
        ref = {"H1": "R1", "H2": "R1", "H3": "R1"}
        score = compute_reference_similarity(agent, ref)
        assert score == 0.0  # Clamped from negative

    def test_partial_match(self):
        agent = {"H1": "C1", "H2": "C1", "H3": "C2", "H4": "C2"}
        ref = {"H1": "R1", "H2": "R1", "H3": "R1", "H4": "R2"}
        score = compute_reference_similarity(agent, ref)
        assert 0.0 <= score <= 1.0

    def test_no_common_ids(self):
        agent = {"H1": "C1"}
        ref = {"H2": "R1"}
        score = compute_reference_similarity(agent, ref)
        assert score == 0.0

    def test_single_common_id(self):
        agent = {"H1": "C1"}
        ref = {"H1": "R1"}
        score = compute_reference_similarity(agent, ref)
        assert score == 0.0  # Need at least 2 items


class TestComputeGranularityScore:
    def test_exact_match(self):
        score = compute_granularity_score(3, 3)
        assert score == 1.0

    def test_off_by_one(self):
        score = compute_granularity_score(4, 3)
        expected = math.exp(-0.5)
        assert abs(score - expected) < 1e-6

    def test_off_by_two(self):
        score = compute_granularity_score(5, 3)
        expected = math.exp(-1.0)
        assert abs(score - expected) < 1e-6

    def test_zero_reference(self):
        assert compute_granularity_score(0, 0) == 1.0
        assert compute_granularity_score(1, 0) == 0.0

    def test_symmetric(self):
        assert compute_granularity_score(2, 4) == compute_granularity_score(4, 2)


class TestComputeDependencyRecall:
    def test_all_satisfied(self):
        agent = {"H1": "C1", "H5": "C1", "H3": "C2"}
        deps = [
            KnownDependency(
                description="test",
                hunks_must_cocommit=["H1", "H5"],
                reason="related",
            )
        ]
        assert compute_dependency_recall(agent, deps) == 1.0

    def test_none_satisfied(self):
        agent = {"H1": "C1", "H5": "C2"}
        deps = [
            KnownDependency(
                description="test",
                hunks_must_cocommit=["H1", "H5"],
                reason="related",
            )
        ]
        assert compute_dependency_recall(agent, deps) == 0.0

    def test_partial_satisfaction(self):
        agent = {"H1": "C1", "H2": "C1", "H3": "C2", "H4": "C3"}
        deps = [
            KnownDependency(
                description="d1",
                hunks_must_cocommit=["H1", "H2"],
                reason="r1",
            ),
            KnownDependency(
                description="d2",
                hunks_must_cocommit=["H3", "H4"],
                reason="r2",
            ),
        ]
        assert compute_dependency_recall(agent, deps) == 0.5

    def test_no_constraints(self):
        assert compute_dependency_recall({}, []) == 1.0

    def test_missing_hunk_id(self):
        agent = {"H1": "C1"}
        deps = [
            KnownDependency(
                description="test",
                hunks_must_cocommit=["H1", "H99"],
                reason="missing hunk",
            )
        ]
        assert compute_dependency_recall(agent, deps) == 0.0

    def test_empty_constraint(self):
        agent = {"H1": "C1"}
        deps = [
            KnownDependency(
                description="empty",
                hunks_must_cocommit=[],
                reason="empty",
            )
        ]
        assert compute_dependency_recall(agent, deps) == 1.0


class TestComputeOverallScore:
    def test_perfect_scores(self):
        mechanical = MechanicalResult(
            full_sequence_valid=True,
            build_pass_rate=1.0,
            patch_apply_rate=1.0,
            import_integrity_rate=1.0,
        )
        semantic = SemanticScores(
            reference_similarity=1.0,
            granularity=1.0,
            dependency_recall=1.0,
        )
        score = compute_overall_score(mechanical, semantic)
        assert abs(score - 1.0) < 1e-6

    def test_zero_scores(self):
        mechanical = MechanicalResult(
            full_sequence_valid=False,
            build_pass_rate=0.0,
            patch_apply_rate=0.0,
            import_integrity_rate=0.0,
        )
        semantic = SemanticScores(
            reference_similarity=0.0,
            granularity=0.0,
            dependency_recall=0.0,
        )
        score = compute_overall_score(mechanical, semantic)
        assert score == 0.0

    def test_with_judge_scores(self):
        mechanical = MechanicalResult(
            full_sequence_valid=True,
            build_pass_rate=1.0,
            patch_apply_rate=1.0,
            import_integrity_rate=1.0,
        )
        semantic = SemanticScores(
            reference_similarity=0.8,
            granularity=0.9,
            dependency_recall=1.0,
            cohesion=0.7,
            separation=0.8,
            ordering=0.9,
        )
        score = compute_overall_score(mechanical, semantic)
        assert 0.0 < score < 1.0

    def test_mechanical_failure_uses_build_pass_rate(self):
        mechanical = MechanicalResult(
            full_sequence_valid=False,
            build_pass_rate=0.5,
            patch_apply_rate=0.5,
            import_integrity_rate=0.5,
        )
        semantic = SemanticScores(
            reference_similarity=1.0,
            granularity=1.0,
            dependency_recall=1.0,
        )
        score = compute_overall_score(mechanical, semantic)
        # 0.6 * 0.5 + 0.4 * 1.0 = 0.3 + 0.4 = 0.7
        assert abs(score - 0.7) < 1e-6
