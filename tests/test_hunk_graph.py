"""Tests for the hunk dependency graph."""

import pytest

from hunknote.compose.models import HunkSymbols, Rename
from hunknote.compose.graph import (
    _extract_symbol_from_import,
    build_hunk_dependency_graph,
    compute_connected_components,
    detect_renames,
    find_related_hunks,
    topological_sort_groups,
    build_inter_group_edges,
)


# ============================================================
# Import Path Normalisation Tests
# ============================================================

class TestExtractSymbolFromImport:
    """Tests for the multi-language import path normaliser."""

    def test_python_dotted_path(self):
        assert _extract_symbol_from_import("core.utils.rate_limit") == "rate_limit"

    def test_js_relative_path(self):
        assert _extract_symbol_from_import("./helpers") == "helpers"

    def test_go_package_path(self):
        assert _extract_symbol_from_import("pkg/auth") == "auth"

    def test_rust_crate_path(self):
        assert _extract_symbol_from_import("crate::auth::service") == "service"

    def test_java_package_path(self):
        assert _extract_symbol_from_import("com.example.UserService") == "UserService"

    def test_c_header_path(self):
        assert _extract_symbol_from_import("auth/service.h") == "service"

    def test_single_name(self):
        assert _extract_symbol_from_import("os") == "os"

    def test_ts_with_extension(self):
        assert _extract_symbol_from_import("./utils.ts") == "utils"


# ============================================================
# Rename Detection Tests
# ============================================================

class TestDetectRenames:
    """Tests for rename detection across hunks."""

    def test_simple_rename(self):
        analyses = {
            "H1": HunkSymbols(
                file_path="utils.py", language="python",
                defines={"new_function"}, removes={"old_function"},
            ),
        }
        renames = detect_renames(analyses)
        assert len(renames) == 1
        assert renames[0].old_name == "old_function"
        assert renames[0].new_name == "new_function"

    def test_no_rename_different_case(self):
        analyses = {
            "H1": HunkSymbols(
                file_path="utils.py", language="python",
                defines={"NewClass"}, removes={"old_function"},
            ),
        }
        renames = detect_renames(analyses)
        assert len(renames) == 0

    def test_no_rename_very_different_names(self):
        analyses = {
            "H1": HunkSymbols(
                file_path="utils.py", language="python",
                defines={"xyz"}, removes={"abcdefgh"},
            ),
        }
        renames = detect_renames(analyses)
        assert len(renames) == 0

    def test_rename_shared_suffix(self):
        analyses = {
            "H1": HunkSymbols(
                file_path="utils.py", language="python",
                defines={"new_handler"}, removes={"old_handler"},
            ),
        }
        renames = detect_renames(analyses)
        assert len(renames) == 1


# ============================================================
# Graph Construction Tests
# ============================================================

class TestBuildHunkDependencyGraph:
    """Tests for building the hunk-level dependency graph."""

    def test_simple_dependency(self):
        """H2 references a symbol defined by H1."""
        analyses = {
            "H1": HunkSymbols(
                file_path="utils.py", language="python",
                defines={"rate_limit"},
            ),
            "H2": HunkSymbols(
                file_path="api.py", language="python",
                references={"rate_limit"},
            ),
        }
        graph = build_hunk_dependency_graph(analyses)
        assert "H2" in graph
        assert "H1" in graph["H2"]

    def test_independent_hunks(self):
        """No shared symbols → no edges."""
        analyses = {
            "H1": HunkSymbols(
                file_path="utils.py", language="python",
                defines={"rate_limit"},
            ),
            "H2": HunkSymbols(
                file_path="api.py", language="python",
                defines={"sanitize_input"},
            ),
        }
        graph = build_hunk_dependency_graph(analyses)
        assert len(graph) == 0

    def test_import_dependency(self):
        """H2 imports a module whose final symbol matches H1's definition."""
        analyses = {
            "H1": HunkSymbols(
                file_path="core/utils.py", language="python",
                defines={"rate_limit"},
            ),
            "H2": HunkSymbols(
                file_path="api/routes.py", language="python",
                imports_added={"core.utils.rate_limit"},
            ),
        }
        graph = build_hunk_dependency_graph(analyses)
        assert "H2" in graph
        assert "H1" in graph["H2"]

    def test_two_independent_chains(self):
        """Two independent feature chains: H1→H3, H2→H4."""
        analyses = {
            "H1": HunkSymbols(
                file_path="utils.py", language="python",
                defines={"rate_limit"},
            ),
            "H2": HunkSymbols(
                file_path="utils.py", language="python",
                defines={"sanitize_input"},
            ),
            "H3": HunkSymbols(
                file_path="api.py", language="python",
                references={"rate_limit"},
            ),
            "H4": HunkSymbols(
                file_path="api.py", language="python",
                references={"sanitize_input"},
            ),
        }
        graph = build_hunk_dependency_graph(analyses)
        assert graph.get("H3") == {"H1"}
        assert graph.get("H4") == {"H2"}
        # H1 and H2 are independent — no edge between them
        assert "H1" not in graph
        assert "H2" not in graph

    def test_rename_chain(self):
        """H1 renames old→new, H2 removes import of old → linked."""
        analyses = {
            "H1": HunkSymbols(
                file_path="utils.py", language="python",
                defines={"new_func"}, removes={"old_func"},
            ),
            "H2": HunkSymbols(
                file_path="api.py", language="python",
                imports_removed={"utils.old_func"},
                imports_added={"utils.new_func"},
            ),
        }
        renames = detect_renames(analyses)
        graph = build_hunk_dependency_graph(analyses, renames)
        # H2 should depend on H1 (rename chain)
        assert "H2" in graph
        assert "H1" in graph["H2"]

    def test_self_reference_excluded(self):
        """A hunk should not depend on itself."""
        analyses = {
            "H1": HunkSymbols(
                file_path="utils.py", language="python",
                defines={"my_func"}, references={"my_func"},
            ),
        }
        graph = build_hunk_dependency_graph(analyses)
        assert "H1" not in graph


# ============================================================
# Connected Components Tests
# ============================================================

class TestComputeConnectedComponents:
    """Tests for computing connected components."""

    def test_all_independent(self):
        graph: dict[str, set[str]] = {}
        all_ids = {"H1", "H2", "H3"}
        components = compute_connected_components(graph, all_ids)
        assert len(components) == 3

    def test_single_component(self):
        graph = {"H2": {"H1"}, "H3": {"H2"}}
        all_ids = {"H1", "H2", "H3"}
        components = compute_connected_components(graph, all_ids)
        assert len(components) == 1
        assert components[0] == {"H1", "H2", "H3"}

    def test_two_components(self):
        graph = {"H2": {"H1"}, "H4": {"H3"}}
        all_ids = {"H1", "H2", "H3", "H4"}
        components = compute_connected_components(graph, all_ids)
        assert len(components) == 2

    def test_isolated_hunk(self):
        graph = {"H2": {"H1"}}
        all_ids = {"H1", "H2", "H3"}
        components = compute_connected_components(graph, all_ids)
        assert len(components) == 2
        # H3 should be its own component
        sizes = sorted(len(c) for c in components)
        assert sizes == [1, 2]


# ============================================================
# Transitive Closure Tests
# ============================================================

class TestFindRelatedHunks:
    """Tests for find_related_hunks (BFS transitive closure)."""

    def test_direct_dependency(self):
        graph = {"H2": {"H1"}}
        related = find_related_hunks("H1", graph)
        assert related == {"H1", "H2"}

    def test_transitive_chain(self):
        graph = {"H2": {"H1"}, "H3": {"H2"}}
        related = find_related_hunks("H1", graph)
        assert related == {"H1", "H2", "H3"}

    def test_isolated_hunk(self):
        graph = {"H2": {"H1"}}
        related = find_related_hunks("H3", graph)
        assert related == {"H3"}

    def test_bidirectional(self):
        graph = {"H2": {"H1"}, "H1": {"H3"}}
        related = find_related_hunks("H2", graph)
        assert related == {"H1", "H2", "H3"}


# ============================================================
# Topological Sort Tests
# ============================================================

class TestTopologicalSortGroups:
    """Tests for topological sorting of commit groups."""

    def test_no_dependencies(self):
        groups = [{"H1"}, {"H2"}, {"H3"}]
        graph: dict[str, set[str]] = {}
        sorted_groups = topological_sort_groups(groups, graph)
        assert len(sorted_groups) == 3

    def test_linear_dependency(self):
        groups = [{"H1"}, {"H2"}, {"H3"}]
        graph = {"H3": {"H2"}, "H2": {"H1"}}
        sorted_groups = topological_sort_groups(groups, graph)
        # H1 should come before H2, H2 before H3
        assert sorted_groups[0] == {"H1"}
        assert sorted_groups[-1] == {"H3"}

    def test_single_group(self):
        groups = [{"H1", "H2"}]
        graph = {"H2": {"H1"}}
        sorted_groups = topological_sort_groups(groups, graph)
        assert len(sorted_groups) == 1

    def test_empty(self):
        result = topological_sort_groups([], {})
        assert result == []


# ============================================================
# Inter-Group Edge Tests
# ============================================================

class TestBuildInterGroupEdges:
    """Tests for building edges between commit groups."""

    def test_no_cross_group_edges(self):
        groups = [{"H1", "H2"}, {"H3", "H4"}]
        graph = {"H2": {"H1"}, "H4": {"H3"}}
        edges = build_inter_group_edges(groups, graph)
        assert len(edges) == 0

    def test_cross_group_edge(self):
        groups = [{"H1"}, {"H2"}]
        graph = {"H2": {"H1"}}
        edges = build_inter_group_edges(groups, graph)
        # Group 1 (H2) depends on Group 0 (H1)
        assert 1 in edges
        assert 0 in edges[1]

