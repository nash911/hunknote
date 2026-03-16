"""Tests for hunknote.compose.agent.gates — Output validation gates."""

import pytest

from hunknote.compose.agent.gates import (
    GateViolation,
    build_correction_prompt,
    validate_clustering_output,
    validate_dependency_output,
    validate_remediation_output,
)


# ── validate_clustering_output ──


class TestValidateClusteringOutput:
    """Tests for Phase 3 clustering gate validation."""

    @pytest.fixture
    def mutable(self):
        return {"H1_abc123", "H2_def456", "H3_789ghi"}

    @pytest.fixture
    def frozen(self):
        return {"H10_frozen"}

    def test_valid_clustering(self, mutable, frozen):
        """All hunks assigned to valid groups passes validation."""
        groups = [
            {"id": "_G1", "hunks": ["H1_abc123", "H2_def456"]},
            {"id": "_G2", "hunks": ["H3_789ghi"]},
        ]
        valid, violations = validate_clustering_output(groups, mutable, frozen, 6)
        assert valid is True
        assert violations == []

    def test_empty_group(self, mutable, frozen):
        """Empty group triggers violation."""
        groups = [
            {"id": "_G1", "hunks": ["H1_abc123", "H2_def456", "H3_789ghi"]},
            {"id": "_G2", "hunks": []},
        ]
        valid, violations = validate_clustering_output(groups, mutable, frozen, 6)
        assert valid is False
        assert any(v.violation_type == "empty_group" for v in violations)

    def test_frozen_hunk_referenced(self, mutable, frozen):
        """Referencing a frozen hunk triggers violation."""
        groups = [
            {"id": "_G1", "hunks": ["H1_abc123", "H10_frozen"]},
            {"id": "_G2", "hunks": ["H2_def456", "H3_789ghi"]},
        ]
        valid, violations = validate_clustering_output(groups, mutable, frozen, 6)
        assert valid is False
        assert any(v.violation_type == "frozen_hunk_referenced" for v in violations)

    def test_nonexistent_hunk(self, mutable, frozen):
        """Referencing a nonexistent hunk triggers violation."""
        groups = [
            {"id": "_G1", "hunks": ["H1_abc123", "H99_fake"]},
            {"id": "_G2", "hunks": ["H2_def456", "H3_789ghi"]},
        ]
        valid, violations = validate_clustering_output(groups, mutable, frozen, 6)
        assert valid is False
        assert any(v.violation_type == "nonexistent_hunk" for v in violations)

    def test_duplicate_assignment(self, mutable, frozen):
        """Assigning a hunk to multiple groups triggers violation."""
        groups = [
            {"id": "_G1", "hunks": ["H1_abc123", "H2_def456"]},
            {"id": "_G2", "hunks": ["H2_def456", "H3_789ghi"]},
        ]
        valid, violations = validate_clustering_output(groups, mutable, frozen, 6)
        assert valid is False
        assert any(v.violation_type == "duplicate_assignment" for v in violations)

    def test_unassigned_mutable_hunk(self, mutable, frozen):
        """Leaving a mutable hunk unassigned triggers violation."""
        groups = [
            {"id": "_G1", "hunks": ["H1_abc123"]},
        ]
        valid, violations = validate_clustering_output(groups, mutable, frozen, 6)
        assert valid is False
        unassigned = [v for v in violations if v.violation_type == "mutable_hunk_unassigned"]
        assert len(unassigned) == 2  # H2 and H3 missing

    def test_too_many_groups(self, mutable, frozen):
        """Exceeding max commit count triggers violation."""
        groups = [
            {"id": f"_G{i}", "hunks": [hid]}
            for i, hid in enumerate(mutable, 1)
        ]
        valid, violations = validate_clustering_output(groups, mutable, frozen, 2)
        assert valid is False
        assert any(v.violation_type == "too_many_groups" for v in violations)

    def test_single_group_all_hunks(self, mutable, frozen):
        """Single group with all mutable hunks is valid."""
        groups = [{"id": "_G1", "hunks": list(mutable)}]
        valid, violations = validate_clustering_output(groups, mutable, frozen, 6)
        assert valid is True


# ── validate_dependency_output ──


class TestValidateDependencyOutput:
    """Tests for Phase 2 dependency gate validation."""

    @pytest.fixture
    def inventory_ids(self):
        return {"H1_abc123", "H2_def456", "H3_789ghi"}

    def test_valid_edges(self, inventory_ids):
        """Valid edges pass validation."""
        edges = [
            {"from": "H1_abc123", "to": "H2_def456", "type": "directional"},
            {"from": "H2_def456", "to": "H3_789ghi", "type": "bidirectional"},
        ]
        valid, violations = validate_dependency_output(edges, inventory_ids)
        assert valid is True

    def test_nonexistent_from(self, inventory_ids):
        """Nonexistent 'from' hunk triggers violation."""
        edges = [{"from": "H99_fake", "to": "H1_abc123", "type": "directional"}]
        valid, violations = validate_dependency_output(edges, inventory_ids)
        assert valid is False
        assert any(v.violation_type == "nonexistent_hunk_in_edge" for v in violations)

    def test_nonexistent_to(self, inventory_ids):
        """Nonexistent 'to' hunk triggers violation."""
        edges = [{"from": "H1_abc123", "to": "H99_fake", "type": "directional"}]
        valid, violations = validate_dependency_output(edges, inventory_ids)
        assert valid is False

    def test_self_dependency(self, inventory_ids):
        """Self-referential edge triggers violation."""
        edges = [{"from": "H1_abc123", "to": "H1_abc123", "type": "directional"}]
        valid, violations = validate_dependency_output(edges, inventory_ids)
        assert valid is False
        assert any(v.violation_type == "self_dependency" for v in violations)

    def test_invalid_edge_type(self, inventory_ids):
        """Invalid edge type triggers violation."""
        edges = [{"from": "H1_abc123", "to": "H2_def456", "type": "unknown"}]
        valid, violations = validate_dependency_output(edges, inventory_ids)
        assert valid is False
        assert any(v.violation_type == "invalid_edge_type" for v in violations)

    def test_empty_edges(self, inventory_ids):
        """Empty edge list is valid."""
        valid, violations = validate_dependency_output([], inventory_ids)
        assert valid is True


# ── validate_remediation_output ──


class TestValidateRemediationOutput:
    """Tests for Phase 5b remediation gate validation."""

    @pytest.fixture
    def ids(self):
        return {
            "mutable": {"H1_abc123", "H2_def456"},
            "frozen": {"H10_frozen"},
            "inventory": {"H1_abc123", "H2_def456", "H10_frozen"},
        }

    def test_valid_recluster(self, ids):
        """Valid recluster remediation passes."""
        rem = {
            "action": "recluster",
            "modifications": {
                "merge_hunks_into_same_commit": [["H1_abc123", "H2_def456"]],
            },
        }
        valid, violations = validate_remediation_output(
            rem, ids["mutable"], ids["frozen"], ids["inventory"])
        assert valid is True

    def test_frozen_hunk_in_non_unlock(self, ids):
        """Frozen hunk in recluster triggers violation."""
        rem = {
            "action": "recluster",
            "modifications": {
                "merge_hunks_into_same_commit": [["H1_abc123", "H10_frozen"]],
            },
        }
        valid, violations = validate_remediation_output(
            rem, ids["mutable"], ids["frozen"], ids["inventory"])
        assert valid is False
        assert any(v.violation_type == "frozen_hunk_in_remediation" for v in violations)

    def test_frozen_hunk_allowed_in_unlock(self, ids):
        """Frozen hunk is allowed in unlock_and_recluster."""
        rem = {
            "action": "unlock_and_recluster",
            "modifications": {
                "merge_hunks_into_same_commit": [["H1_abc123", "H10_frozen"]],
            },
        }
        valid, violations = validate_remediation_output(
            rem, ids["mutable"], ids["frozen"], ids["inventory"])
        assert valid is True

    def test_nonexistent_hunk_in_edge(self, ids):
        """Nonexistent hunk in dependency edge triggers violation."""
        rem = {
            "action": "recluster",
            "modifications": {
                "add_dependency_edges": [
                    {"from": "H1_abc123", "to": "H99_fake"},
                ],
            },
        }
        valid, violations = validate_remediation_output(
            rem, ids["mutable"], ids["frozen"], ids["inventory"])
        assert valid is False

    def test_self_dependency_in_edge(self, ids):
        """Self-referential edge in remediation triggers violation."""
        rem = {
            "action": "recluster",
            "modifications": {
                "add_dependency_edges": [
                    {"from": "H1_abc123", "to": "H1_abc123"},
                ],
            },
        }
        valid, violations = validate_remediation_output(
            rem, ids["mutable"], ids["frozen"], ids["inventory"])
        assert valid is False


# ── build_correction_prompt ──


class TestBuildCorrectionPrompt:
    """Tests for correction prompt generation."""

    def test_includes_violations(self):
        """Correction prompt lists all violations."""
        violations = [
            GateViolation("frozen_hunk_referenced", "H10_f", "Hunk H10_f is frozen"),
            GateViolation("mutable_hunk_unassigned", "H3_c", "H3_c unassigned"),
        ]
        prompt = build_correction_prompt(violations, {"H1_a", "H2_b", "H3_c"})
        assert "VIOLATION 1" in prompt
        assert "VIOLATION 2" in prompt
        assert "frozen_hunk_referenced" in prompt
        assert "VALID HUNK IDs" in prompt

    def test_includes_sorted_hunk_ids(self):
        """Valid hunk IDs are sorted by numeric prefix."""
        violations = [GateViolation("test", "", "detail")]
        prompt = build_correction_prompt(
            violations, {"H3_c", "H1_a", "H2_b"})
        # H1 should come before H2 before H3
        idx1 = prompt.index("H1_a")
        idx2 = prompt.index("H2_b")
        idx3 = prompt.index("H3_c")
        assert idx1 < idx2 < idx3
