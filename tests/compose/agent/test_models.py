"""Tests for hunknote.compose.agent.models — Data models and DependencyGraph."""

import pytest

from hunknote.compose.agent.models import (
    CommitGroup,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
    FrozenBaseline,
    FrozenCommit,
    HunkSummary,
    MutableWorkingSet,
    Remediation,
    RemediationAction,
    ValidationFailure,
    ValidationLayer,
)


class TestHunkSummary:
    """Tests for HunkSummary dataclass."""

    def test_basic_creation(self):
        """Test basic HunkSummary creation with required fields."""
        s = HunkSummary(hunk_id="H1_abc123", file_path="foo.py",
                        intent="Add function", category="feature")
        assert s.hunk_id == "H1_abc123"
        assert s.file_path == "foo.py"
        assert s.symbols_modified == []
        assert s.symbols_referenced == []
        assert s.is_new_file is False

    def test_new_file_flag(self):
        """Test is_new_file flag."""
        s = HunkSummary(hunk_id="H1_a", file_path="new.py",
                        intent="New file", category="feature", is_new_file=True)
        assert s.is_new_file is True


class TestEdgeType:
    """Tests for EdgeType enum."""

    def test_values(self):
        assert EdgeType.DIRECTIONAL.value == "directional"
        assert EdgeType.BIDIRECTIONAL.value == "bidirectional"

    def test_from_string(self):
        assert EdgeType("directional") == EdgeType.DIRECTIONAL
        assert EdgeType("bidirectional") == EdgeType.BIDIRECTIONAL

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            EdgeType("unknown")


class TestDependencyGraph:
    """Tests for DependencyGraph operations."""

    def test_empty_graph(self):
        """Empty graph has no edges."""
        g = DependencyGraph()
        assert g.edges == []
        assert g.warnings == []

    def test_add_edge(self):
        """Test adding a single edge."""
        g = DependencyGraph()
        edge = DependencyEdge(
            from_hunk="H1_a", to_hunk="H2_b",
            edge_type=EdgeType.DIRECTIONAL, reason="test",
        )
        g.add_edge(edge)
        assert len(g.edges) == 1
        assert g.edges[0].from_hunk == "H1_a"

    def test_add_bidirectional_pair(self):
        """Test adding bidirectional edges between two hunks."""
        g = DependencyGraph()
        g.add_bidirectional(["H1_a", "H2_b"], reason="same feature")
        assert len(g.edges) == 1
        assert g.edges[0].edge_type == EdgeType.BIDIRECTIONAL

    def test_add_bidirectional_triple(self):
        """Three hunks produce 3 bidirectional edges (n choose 2)."""
        g = DependencyGraph()
        g.add_bidirectional(["H1_a", "H2_b", "H3_c"], reason="new file")
        assert len(g.edges) == 3
        all_bidir = all(e.edge_type == EdgeType.BIDIRECTIONAL for e in g.edges)
        assert all_bidir

    def test_add_bidirectional_single_hunk_no_edges(self):
        """Single hunk produces no edges."""
        g = DependencyGraph()
        g.add_bidirectional(["H1_a"], reason="single")
        assert len(g.edges) == 0

    def test_get_edges_for_hunk(self):
        """Test filtering edges by hunk ID."""
        g = DependencyGraph()
        g.add_edge(DependencyEdge("H1_a", "H2_b", EdgeType.DIRECTIONAL, "r1"))
        g.add_edge(DependencyEdge("H3_c", "H1_a", EdgeType.DIRECTIONAL, "r2"))
        g.add_edge(DependencyEdge("H4_d", "H5_e", EdgeType.DIRECTIONAL, "r3"))

        edges = g.get_edges_for_hunk("H1_a")
        assert len(edges) == 2

    def test_get_bidirectional_groups_single_pair(self):
        """Test connected component for one pair."""
        g = DependencyGraph()
        g.add_edge(DependencyEdge("H1_a", "H2_b", EdgeType.BIDIRECTIONAL, "r"))
        groups = g.get_bidirectional_groups()
        assert len(groups) == 1
        assert groups[0] == {"H1_a", "H2_b"}

    def test_get_bidirectional_groups_transitive(self):
        """Bidirectional edges form transitive groups via union-find."""
        g = DependencyGraph()
        g.add_edge(DependencyEdge("H1_a", "H2_b", EdgeType.BIDIRECTIONAL, "r1"))
        g.add_edge(DependencyEdge("H2_b", "H3_c", EdgeType.BIDIRECTIONAL, "r2"))
        groups = g.get_bidirectional_groups()
        assert len(groups) == 1
        assert groups[0] == {"H1_a", "H2_b", "H3_c"}

    def test_get_bidirectional_groups_ignores_directional(self):
        """Directional edges are not grouped."""
        g = DependencyGraph()
        g.add_edge(DependencyEdge("H1_a", "H2_b", EdgeType.DIRECTIONAL, "r"))
        groups = g.get_bidirectional_groups()
        assert len(groups) == 0

    def test_get_bidirectional_groups_two_disconnected(self):
        """Two separate groups stay separate."""
        g = DependencyGraph()
        g.add_edge(DependencyEdge("H1_a", "H2_b", EdgeType.BIDIRECTIONAL, "r1"))
        g.add_edge(DependencyEdge("H3_c", "H4_d", EdgeType.BIDIRECTIONAL, "r2"))
        groups = g.get_bidirectional_groups()
        assert len(groups) == 2

    def test_get_dependencies_of(self):
        """Test getting directional dependencies."""
        g = DependencyGraph()
        g.add_edge(DependencyEdge("H1_a", "H2_b", EdgeType.DIRECTIONAL, "r1"))
        g.add_edge(DependencyEdge("H1_a", "H3_c", EdgeType.DIRECTIONAL, "r2"))
        g.add_edge(DependencyEdge("H4_d", "H1_a", EdgeType.DIRECTIONAL, "r3"))
        deps = g.get_dependencies_of("H1_a")
        assert deps == {"H2_b", "H3_c"}

    def test_get_dependencies_of_none(self):
        """Hunk with no outgoing directional edges returns empty set."""
        g = DependencyGraph()
        g.add_edge(DependencyEdge("H2_b", "H1_a", EdgeType.DIRECTIONAL, "r"))
        assert g.get_dependencies_of("H1_a") == set()


class TestCommitGroup:
    """Tests for CommitGroup dataclass."""

    def test_creation(self):
        g = CommitGroup(group_id="_G1", hunk_ids=["H1_a", "H2_b"],
                        theme="Add feature", category="feature")
        assert g.group_id == "_G1"
        assert len(g.hunk_ids) == 2


class TestFrozenBaseline:
    """Tests for FrozenBaseline and FrozenCommit."""

    def test_empty_baseline(self):
        fb = FrozenBaseline()
        assert fb.all_hunk_ids == set()

    def test_all_hunk_ids_aggregation(self):
        """All hunk IDs from all frozen commits are merged."""
        fb = FrozenBaseline(commits=[
            FrozenCommit(index=0, message="C1", hunk_ids=["H1_a", "H2_b"]),
            FrozenCommit(index=1, message="C2", hunk_ids=["H3_c"]),
        ])
        assert fb.all_hunk_ids == {"H1_a", "H2_b", "H3_c"}


class TestRemediationAction:
    """Tests for RemediationAction enum."""

    def test_all_values(self):
        assert RemediationAction.RECLUSTER.value == "recluster"
        assert RemediationAction.REORDER.value == "reorder"
        assert RemediationAction.SPLIT_COMMIT.value == "split_commit"
        assert RemediationAction.UNLOCK_AND_RECLUSTER.value == "unlock_and_recluster"
        assert RemediationAction.FAIL.value == "fail"


class TestValidationLayer:
    """Tests for ValidationLayer enum."""

    def test_all_layers(self):
        assert ValidationLayer.PATCH_APPLY.value == "patch_apply"
        assert ValidationLayer.SYNTAX.value == "syntax"
        assert ValidationLayer.COMPILE.value == "compile"
        assert ValidationLayer.IMPORT.value == "import"
        assert ValidationLayer.TEST.value == "test"
