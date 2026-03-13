"""Deterministic semantic quality metrics.

Computed without LLM calls. Measures how well the agent's grouping
matches the reference decomposition.
"""

import logging
from typing import Optional

from hunknote.compose.models import ComposePlan, HunkRef
from eval.config import CORRECTNESS_WEIGHT, QUALITY_WEIGHT
from eval.models import (
    KnownDependency,
    MechanicalResult,
    SemanticScores,
    TestCase,
)

logger = logging.getLogger(__name__)


def compute_reference_similarity(
    agent_assignment: dict[str, str],
    reference_assignment: dict[str, str],
) -> float:
    """Adjusted Rand Index between agent and reference groupings.

    The ARI measures agreement between two clustering assignments,
    adjusted for chance. Returns a value in [-1, 1] where 1 is perfect
    agreement, 0 is random, and negative values indicate worse than random.
    We clamp to [0, 1] for scoring.

    Args:
        agent_assignment: hunk_id -> commit_id from agent's plan.
        reference_assignment: hunk_id -> commit_id from reference.

    Returns:
        ARI score clamped to [0, 1].
    """
    # Find common hunk IDs
    common_ids = sorted(set(agent_assignment.keys()) & set(reference_assignment.keys()))
    if len(common_ids) < 2:
        return 0.0

    agent_labels = [agent_assignment[hid] for hid in common_ids]
    ref_labels = [reference_assignment[hid] for hid in common_ids]

    try:
        from sklearn.metrics import adjusted_rand_score

        score = adjusted_rand_score(ref_labels, agent_labels)
        return max(0.0, score)  # Clamp negative to 0
    except ImportError:
        logger.warning(
            "scikit-learn not installed; reference_similarity will be 0.0. "
            "Install with: pip install scikit-learn"
        )
        return 0.0


def compute_granularity_score(agent_count: int, reference_count: int) -> float:
    """Penalize deviation from reference commit count.

    Uses an exponential decay penalty based on the absolute difference
    between agent and reference commit counts.

    Args:
        agent_count: Number of commits in agent's plan.
        reference_count: Number of commits in reference.

    Returns:
        Score in [0, 1] where 1 means exact match.
    """
    if reference_count == 0:
        return 0.0 if agent_count > 0 else 1.0

    diff = abs(agent_count - reference_count)
    # Exponential decay: score = exp(-0.5 * diff)
    import math

    return math.exp(-0.5 * diff)


def compute_dependency_recall(
    agent_assignment: dict[str, str],
    known_deps: list[KnownDependency],
) -> float:
    """Fraction of known co-commit constraints satisfied.

    A constraint is satisfied if all hunks in hunks_must_cocommit
    are assigned to the same commit.

    Args:
        agent_assignment: hunk_id -> commit_id from agent's plan.
        known_deps: List of known dependency constraints.

    Returns:
        Fraction in [0, 1]. Returns 1.0 if there are no constraints.
    """
    if not known_deps:
        return 1.0

    satisfied = 0
    total = len(known_deps)

    for dep in known_deps:
        hunk_ids = dep.hunks_must_cocommit
        if not hunk_ids:
            satisfied += 1
            continue

        # Get the commit IDs for these hunks
        commit_ids = set()
        all_found = True
        for hid in hunk_ids:
            if hid in agent_assignment:
                commit_ids.add(agent_assignment[hid])
            else:
                all_found = False
                break

        # All hunks must be in the same commit
        if all_found and len(commit_ids) == 1:
            satisfied += 1

    return satisfied / total


def _build_assignment_from_plan(plan: ComposePlan) -> dict[str, str]:
    """Build a hunk_id -> commit_id mapping from a ComposePlan."""
    assignment: dict[str, str] = {}
    for commit in plan.commits:
        for hunk_id in commit.hunks:
            assignment[hunk_id] = commit.id
    return assignment


def _build_reference_assignment(test_case: TestCase) -> dict[str, str]:
    """Build a hunk_id -> commit_id mapping from reference commits."""
    assignment: dict[str, str] = {}
    for ref_commit in test_case.reference_commits:
        commit_id = f"R{ref_commit.index}"
        for hunk_id in ref_commit.hunk_ids:
            assignment[hunk_id] = commit_id
    return assignment


def compute_semantic_scores(
    agent_plan: ComposePlan,
    test_case: TestCase,
    inventory: dict[str, HunkRef],
) -> SemanticScores:
    """Compute all deterministic semantic scores.

    Args:
        agent_plan: The agent's ComposePlan.
        test_case: The test case with reference decomposition.
        inventory: Hunk ID -> HunkRef mapping.

    Returns:
        SemanticScores with reference_similarity, granularity, dependency_recall.
    """
    agent_assignment = _build_assignment_from_plan(agent_plan)
    reference_assignment = _build_reference_assignment(test_case)

    ref_similarity = compute_reference_similarity(agent_assignment, reference_assignment)
    granularity = compute_granularity_score(
        len(agent_plan.commits), test_case.stats.reference_commit_count
    )
    dep_recall = compute_dependency_recall(
        agent_assignment, test_case.known_dependencies
    )

    return SemanticScores(
        reference_similarity=ref_similarity,
        granularity=granularity,
        dependency_recall=dep_recall,
    )


def compute_overall_score(
    mechanical: MechanicalResult,
    semantic: SemanticScores,
) -> float:
    """Weighted combination: 60% correctness + 40% quality.

    Args:
        mechanical: Mechanical validation results.
        semantic: Semantic quality scores.

    Returns:
        Overall score in [0, 1].
    """
    correctness = 1.0 if mechanical.full_sequence_valid else mechanical.build_pass_rate

    quality_components: list[tuple[float, float]] = [
        (0.25, semantic.reference_similarity),
        (0.20, semantic.dependency_recall),
        (0.20, semantic.granularity),
    ]

    # Add LLM-judge scores if available
    if semantic.cohesion is not None:
        quality_components.append((0.15, semantic.cohesion))
    if semantic.separation is not None:
        quality_components.append((0.10, semantic.separation))
    if semantic.ordering is not None:
        quality_components.append((0.10, semantic.ordering))

    # Normalize weights
    total_weight = sum(w for w, _ in quality_components)
    quality = (
        sum(w * s for w, s in quality_components) / total_weight
        if total_weight > 0
        else 0.0
    )

    return CORRECTNESS_WEIGHT * correctness + QUALITY_WEIGHT * quality
