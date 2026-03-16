"""Tests for Compose Agent phase modules (summarize, cluster, order, messages)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from hunknote.compose.agent.models import (
    CommitGroup,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
    FrozenBaseline,
    FrozenCommit,
    HunkSummary,
)
from hunknote.compose.agent.phases.cluster import (
    _build_cluster_prompt,
    _build_commit_groups,
    _parse_clustering_response,
    run_phase3_cluster,
)
from hunknote.compose.agent.phases.messages import (
    _fallback_commit,
    _parse_message_response,
    run_phase6_messages,
)
from hunknote.compose.agent.phases.order import (
    _build_group_dag,
    run_phase4_order,
)
from hunknote.compose.agent.phases.summarize import (
    _fallback_summaries,
    _parse_summaries,
    run_phase1_summarize,
)
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.models import FileDiff, HunkRef
from hunknote.llm.base import RawLLMResult


# ── Phase 1: Summarize ──


class TestParseSummaries:
    """Tests for Phase 1 summary response parsing."""

    @pytest.fixture
    def batch_and_inventory(self):
        from hunknote.compose.agent.batching import Batch
        h1 = HunkRef(id="H1_abc123", file_path="foo.py", header="@@",
                      old_start=1, old_len=1, new_start=1, new_len=1, lines=["+x"])
        fd = FileDiff(file_path="foo.py", diff_header_lines=["diff"], hunks=[h1])
        batch = Batch(batch_id=1, file_path="foo.py",
                      hunk_ids=["H1_abc123"], file_paths=["foo.py"],
                      estimated_tokens=500)
        return batch, {"H1_abc123": h1}, {"foo.py": fd}

    def test_valid_json_array(self, batch_and_inventory):
        batch, inv, fd_map = batch_and_inventory
        response = json.dumps([{
            "hunk_id": "H1_abc123",
            "intent": "Add function",
            "category": "feature",
            "symbols_modified": ["hello"],
            "symbols_referenced": [],
        }])
        result = _parse_summaries(response, batch, inv, fd_map)
        assert result is not None
        assert "H1_abc123" in result
        assert result["H1_abc123"].intent == "Add function"

    def test_json_with_markdown_fences(self, batch_and_inventory):
        batch, inv, fd_map = batch_and_inventory
        response = '```json\n[{"hunk_id": "H1_abc123", "intent": "X", "category": "chore"}]\n```'
        result = _parse_summaries(response, batch, inv, fd_map)
        assert result is not None

    def test_invalid_json_returns_none(self, batch_and_inventory):
        batch, inv, fd_map = batch_and_inventory
        result = _parse_summaries("not json at all", batch, inv, fd_map)
        assert result is None

    def test_unknown_hunk_id_skipped(self, batch_and_inventory):
        batch, inv, fd_map = batch_and_inventory
        response = json.dumps([{"hunk_id": "H99_fake", "intent": "X", "category": "chore"}])
        result = _parse_summaries(response, batch, inv, fd_map)
        assert result is None  # No valid summaries


class TestFallbackSummaries:
    """Tests for fallback summaries when LLM fails."""

    def test_creates_summaries_for_all_hunks(self):
        from hunknote.compose.agent.batching import Batch
        h1 = HunkRef(id="H1_a", file_path="foo.py", header="@@",
                      old_start=1, old_len=1, new_start=1, new_len=1, lines=["+x"])
        fd = FileDiff(file_path="foo.py", diff_header_lines=["diff"], hunks=[h1])
        batch = Batch(batch_id=1, file_path="foo.py",
                      hunk_ids=["H1_a"], file_paths=["foo.py"],
                      estimated_tokens=500)
        result = _fallback_summaries(batch, {"H1_a": h1}, {"foo.py": fd})
        assert "H1_a" in result
        assert result["H1_a"].intent == "(summarization failed)"


class TestRunPhase1Summarize:
    """Tests for the full Phase 1 entry point."""

    def test_produces_summaries_for_all_hunks(self):
        """Phase 1 returns a summary for every hunk in the inventory."""
        h1 = HunkRef(id="H1_abc123", file_path="foo.py", header="@@",
                      old_start=1, old_len=3, new_start=1, new_len=5,
                      lines=["+def hello():", "+    pass"])
        fd = FileDiff(file_path="foo.py", diff_header_lines=["diff"], hunks=[h1])
        inv = {"H1_abc123": h1}

        def mock_llm(sys, user):
            return RawLLMResult(
                raw_response=json.dumps([{
                    "hunk_id": "H1_abc123", "intent": "Add hello",
                    "category": "feature",
                }]),
                model="test", input_tokens=10, output_tokens=5,
            )

        trace = AgentTrace()
        summaries = run_phase1_summarize(inv, [fd], Path("."), mock_llm, trace)
        assert "H1_abc123" in summaries
        assert summaries["H1_abc123"].intent == "Add hello"

    def test_fallback_on_llm_failure(self):
        """Produces fallback summaries when LLM raises."""
        h1 = HunkRef(id="H1_a", file_path="foo.py", header="@@",
                      old_start=1, old_len=1, new_start=1, new_len=1, lines=["+x"])
        fd = FileDiff(file_path="foo.py", diff_header_lines=["diff"], hunks=[h1])

        def failing_llm(sys, user):
            raise RuntimeError("API down")

        trace = AgentTrace()
        summaries = run_phase1_summarize({"H1_a": h1}, [fd], Path("."), failing_llm, trace)
        assert "H1_a" in summaries
        assert "failed" in summaries["H1_a"].intent.lower()


# ── Phase 3: Cluster ──


class TestParseClusteringResponse:
    """Tests for Phase 3 response parsing."""

    def test_valid_json(self):
        response = json.dumps({"groups": [
            {"id": "_G1", "hunks": ["H1_a"], "theme": "t", "category": "feat"},
        ]})
        result = _parse_clustering_response(response)
        assert result is not None
        assert len(result) == 1

    def test_json_with_fences(self):
        response = '```json\n{"groups": [{"id": "_G1", "hunks": ["H1_a"]}]}\n```'
        result = _parse_clustering_response(response)
        assert result is not None

    def test_invalid_json(self):
        assert _parse_clustering_response("not json") is None

    def test_missing_groups_key(self):
        assert _parse_clustering_response('{"data": []}') is None


class TestBuildCommitGroups:
    """Tests for converting parsed dicts to CommitGroup objects."""

    def test_basic_conversion(self):
        data = [
            {"id": "_G1", "hunks": ["H1_a", "H2_b"], "theme": "Feature", "category": "feat"},
            {"id": "_G2", "hunks": ["H3_c"], "theme": "Fix", "category": "fix"},
        ]
        groups = _build_commit_groups(data)
        assert len(groups) == 2
        assert groups[0].group_id == "_G1"
        assert groups[0].hunk_ids == ["H1_a", "H2_b"]
        assert groups[1].category == "fix"

    def test_missing_fields_use_defaults(self):
        data = [{"hunks": ["H1_a"]}]
        groups = _build_commit_groups(data)
        assert groups[0].group_id == "_G1"
        assert groups[0].theme == ""
        assert groups[0].category == "chore"


class TestRunPhase3Cluster:
    """Tests for the Phase 3 entry point."""

    def test_successful_clustering(self, summaries, trace):
        """Produces valid commit groups from LLM response."""
        graph = DependencyGraph()

        def mock_llm(sys, user):
            return RawLLMResult(
                raw_response=json.dumps({"groups": [
                    {"id": "_G1", "hunks": ["H1_abc123", "H4_jkl012"], "theme": "Feature+tests", "category": "feature"},
                    {"id": "_G2", "hunks": ["H2_def456"], "theme": "Goodbye", "category": "feature"},
                    {"id": "_G3", "hunks": ["H3_789ghi"], "theme": "Integration", "category": "feature"},
                    {"id": "_G4", "hunks": ["H5_mno345"], "theme": "New module", "category": "feature"},
                ]}),
                model="test", input_tokens=100, output_tokens=50,
            )

        groups = run_phase3_cluster(
            summaries, graph,
            list(summaries.keys()), FrozenBaseline(), 6,
            mock_llm, trace,
        )
        assert len(groups) == 4
        # All hunks assigned
        all_hids = set()
        for g in groups:
            all_hids.update(g.hunk_ids)
        assert all_hids == set(summaries.keys())

    def test_fallback_to_single_group(self, summaries, trace):
        """Falls back to single group after max attempts."""
        graph = DependencyGraph()

        def bad_llm(sys, user):
            return RawLLMResult(
                raw_response="not valid json at all",
                model="test", input_tokens=10, output_tokens=5,
            )

        groups = run_phase3_cluster(
            summaries, graph,
            list(summaries.keys()), FrozenBaseline(), 6,
            bad_llm, trace, max_attempts=2,
        )
        assert len(groups) == 1
        assert set(groups[0].hunk_ids) == set(summaries.keys())

    def test_gate_correction_reprompt(self, summaries, trace):
        """Gate failure triggers reprompt with correction."""
        graph = DependencyGraph()
        call_count = [0]

        def mock_llm(sys, user):
            call_count[0] += 1
            if call_count[0] == 1:
                # First attempt: missing H5_mno345
                return RawLLMResult(
                    raw_response=json.dumps({"groups": [
                        {"id": "_G1", "hunks": ["H1_abc123", "H2_def456", "H3_789ghi", "H4_jkl012"]},
                    ]}),
                    model="test", input_tokens=100, output_tokens=50,
                )
            # Second attempt: all hunks assigned
            return RawLLMResult(
                raw_response=json.dumps({"groups": [
                    {"id": "_G1", "hunks": list(summaries.keys())},
                ]}),
                model="test", input_tokens=100, output_tokens=50,
            )

        groups = run_phase3_cluster(
            summaries, graph,
            list(summaries.keys()), FrozenBaseline(), 6,
            mock_llm, trace,
        )
        assert call_count[0] == 2
        assert len(groups) >= 1


# ── Phase 4: Order ──


class TestBuildGroupDag:
    """Tests for group-level DAG construction."""

    def test_directional_edge_creates_group_dependency(self):
        """Directional hunk edge creates group-level dependency."""
        groups = [
            CommitGroup("_G1", ["H1_a"], "Feature", "feat"),
            CommitGroup("_G2", ["H2_b"], "Fix", "fix"),
        ]
        graph = DependencyGraph()
        graph.add_edge(DependencyEdge("H2_b", "H1_a", EdgeType.DIRECTIONAL, "imports"))

        dag = _build_group_dag(groups, graph)
        # _G2 depends on _G1 (H2_b→H1_a means G2 depends on G1)
        assert "_G1" in dag["_G2"]

    def test_bidirectional_edge_ignored(self):
        """Bidirectional edges don't create group ordering dependencies."""
        groups = [
            CommitGroup("_G1", ["H1_a"], "A", "feat"),
            CommitGroup("_G2", ["H2_b"], "B", "feat"),
        ]
        graph = DependencyGraph()
        graph.add_edge(DependencyEdge("H1_a", "H2_b", EdgeType.BIDIRECTIONAL, "test"))

        dag = _build_group_dag(groups, graph)
        assert dag["_G1"] == set()
        assert dag["_G2"] == set()

    def test_intra_group_edge_ignored(self):
        """Edge within the same group doesn't create self-dependency."""
        groups = [
            CommitGroup("_G1", ["H1_a", "H2_b"], "A", "feat"),
        ]
        graph = DependencyGraph()
        graph.add_edge(DependencyEdge("H1_a", "H2_b", EdgeType.DIRECTIONAL, "internal"))

        dag = _build_group_dag(groups, graph)
        assert dag["_G1"] == set()


class TestRunPhase4Order:
    """Tests for the Phase 4 ordering entry point."""

    def test_single_group(self, trace):
        """Single group gets renamed to C1."""
        groups = [CommitGroup("_G1", ["H1_a"], "Only one", "feat")]
        ordered = run_phase4_order(
            groups, DependencyGraph(), FrozenBaseline(),
            lambda s, u: None, trace,
        )
        assert len(ordered) == 1
        assert ordered[0].group_id == "C1"

    def test_topological_order_respected(self, trace):
        """Dependencies determine commit order."""
        groups = [
            CommitGroup("_G1", ["H1_a"], "Depends on G2", "feat"),
            CommitGroup("_G2", ["H2_b"], "Base", "refactor"),
        ]
        graph = DependencyGraph()
        # H1_a depends on H2_b → _G1 depends on _G2
        graph.add_edge(DependencyEdge("H1_a", "H2_b", EdgeType.DIRECTIONAL, "dep"))

        def mock_llm(sys, user):
            return RawLLMResult(
                raw_response='["_G2", "_G1"]',
                model="test", input_tokens=10, output_tokens=5,
            )

        ordered = run_phase4_order(groups, graph, FrozenBaseline(), mock_llm, trace)
        # _G2 should come first (no deps), then _G1
        assert ordered[0].hunk_ids == ["H2_b"]  # Was _G2
        assert ordered[1].hunk_ids == ["H1_a"]  # Was _G1
        assert ordered[0].group_id == "C1"
        assert ordered[1].group_id == "C2"

    def test_ids_renamed_to_c_prefix(self, trace):
        """All groups get C{n} IDs after ordering."""
        groups = [
            CommitGroup("_G1", ["H1_a"], "A", "feat"),
            CommitGroup("_G2", ["H2_b"], "B", "feat"),
            CommitGroup("_G3", ["H3_c"], "C", "feat"),
        ]

        def mock_llm(sys, user):
            return RawLLMResult(
                raw_response='["_G1", "_G2", "_G3"]',
                model="test", input_tokens=10, output_tokens=5,
            )

        ordered = run_phase4_order(
            groups, DependencyGraph(), FrozenBaseline(), mock_llm, trace,
        )
        ids = [g.group_id for g in ordered]
        assert ids == ["C1", "C2", "C3"]


# ── Phase 6: Messages ──


class TestParseMessageResponse:
    """Tests for Phase 6 message response parsing."""

    def test_valid_response(self):
        response = json.dumps({
            "type": "feat", "scope": "auth",
            "title": "Add login endpoint", "bullets": ["Add POST /login"],
        })
        group = CommitGroup("C1", ["H1_a"], "Login", "feature")
        commit = _parse_message_response(response, group)
        assert commit is not None
        assert commit.type == "feat"
        assert commit.scope == "auth"
        assert commit.id == "C1"

    def test_invalid_response_returns_none(self):
        group = CommitGroup("C1", ["H1_a"], "X", "feat")
        assert _parse_message_response("not json", group) is None

    def test_fenced_json(self):
        response = '```json\n{"type": "fix", "title": "Fix bug", "bullets": []}\n```'
        group = CommitGroup("C1", ["H1_a"], "X", "fix")
        commit = _parse_message_response(response, group)
        assert commit is not None
        assert commit.type == "fix"


class TestFallbackCommit:
    """Tests for fallback commit generation."""

    def test_uses_group_info(self):
        group = CommitGroup("C1", ["H1_a", "H2_b"], "Add feature", "feat")
        commit = _fallback_commit(group)
        assert commit.id == "C1"
        assert commit.title == "Add feature"
        assert commit.hunks == ["H1_a", "H2_b"]


class TestRunPhase6Messages:
    """Tests for the Phase 6 entry point."""

    def test_produces_planned_commits(self, summaries, trace):
        ordered = [
            CommitGroup("C1", ["H1_abc123", "H2_def456"], "Feature", "feature"),
            CommitGroup("C2", ["H3_789ghi"], "Integration", "feature"),
        ]
        inv = {hid: HunkRef(id=hid, file_path="f.py", header="@@",
                             old_start=1, old_len=1, new_start=1, new_len=1,
                             lines=["+x"]) for hid in ["H1_abc123", "H2_def456", "H3_789ghi"]}

        def mock_llm(sys, user):
            return RawLLMResult(
                raw_response=json.dumps({
                    "type": "feat", "title": "Test commit",
                    "bullets": ["change 1"],
                }),
                model="test", input_tokens=50, output_tokens=30,
            )

        commits = run_phase6_messages(
            ordered, inv, summaries, None, None, mock_llm, trace,
        )
        assert len(commits) == 2
        assert commits[0].id == "C1"
        assert commits[1].id == "C2"

    def test_fallback_on_llm_failure(self, summaries, trace):
        """Produces fallback commits when LLM raises."""
        ordered = [CommitGroup("C1", ["H1_abc123"], "X", "feat")]
        inv = {"H1_abc123": HunkRef(id="H1_abc123", file_path="f.py", header="@@",
                                     old_start=1, old_len=1, new_start=1, new_len=1, lines=["+x"])}

        def failing_llm(sys, user):
            raise RuntimeError("API down")

        commits = run_phase6_messages(
            ordered, inv, summaries, None, None, failing_llm, trace,
        )
        assert len(commits) == 1
        assert commits[0].id == "C1"


# ── Phase 5a: Validation helpers ──


from hunknote.compose.agent.phases.validate import (
    _check_import_deps,
    _check_internal_module_missing,
    _file_path_to_module,
)
from hunknote.compose.agent.models import ValidationLayer


class TestFilePathToModule:
    """Tests for _file_path_to_module conversion."""

    def test_regular_module(self):
        assert _file_path_to_module("hunknote/cli/compose.py") == "hunknote.cli.compose"

    def test_init_file(self):
        assert _file_path_to_module("hunknote/compose/__init__.py") == "hunknote.compose"

    def test_test_file_not_skipped(self):
        """Test files should NOT be skipped — they need import validation."""
        result = _file_path_to_module("tests/compose/agent/test_models.py")
        assert result == "tests.compose.agent.test_models"

    def test_test_init_not_skipped(self):
        result = _file_path_to_module("tests/compose/__init__.py")
        assert result == "tests.compose"

    def test_setup_skipped(self):
        assert _file_path_to_module("setup.py") is None

    def test_non_python_skipped(self):
        assert _file_path_to_module("README.md") is None


class TestCheckInternalModuleMissing:
    """Tests for _check_internal_module_missing."""

    def test_external_module_not_flagged(self, tmp_path):
        """Modules whose top-level package doesn't exist are external."""
        assert _check_internal_module_missing(tmp_path, "requests.models") is False

    def test_internal_module_exists_as_file(self, tmp_path):
        (tmp_path / "hunknote" / "compose").mkdir(parents=True)
        (tmp_path / "hunknote" / "compose" / "models.py").write_text("")
        assert _check_internal_module_missing(tmp_path, "hunknote.compose.models") is False

    def test_internal_module_exists_as_package(self, tmp_path):
        (tmp_path / "hunknote" / "compose" / "agent").mkdir(parents=True)
        (tmp_path / "hunknote" / "compose" / "agent" / "__init__.py").write_text("")
        assert _check_internal_module_missing(tmp_path, "hunknote.compose.agent") is False

    def test_internal_module_missing(self, tmp_path):
        """Module whose top-level package exists but target file doesn't."""
        (tmp_path / "hunknote").mkdir()
        (tmp_path / "hunknote" / "__init__.py").write_text("")
        assert _check_internal_module_missing(
            tmp_path, "hunknote.compose.agent.models",
        ) is True

    def test_single_part_module_file(self, tmp_path):
        (tmp_path / "setup.py").write_text("")
        assert _check_internal_module_missing(tmp_path, "setup") is False

    def test_single_part_module_dir(self, tmp_path):
        (tmp_path / "hunknote").mkdir()
        (tmp_path / "hunknote" / "__init__.py").write_text("")
        assert _check_internal_module_missing(tmp_path, "hunknote") is False


class TestCheckImportDeps:
    """Tests for the AST-based import dependency analysis."""

    @pytest.fixture
    def trace(self):
        return AgentTrace()

    def test_detects_missing_lazy_import(self, tmp_path, trace):
        """Catches a from...import inside a function body."""
        # Set up worktree with top-level package but missing submodule
        (tmp_path / "hunknote").mkdir()
        (tmp_path / "hunknote" / "__init__.py").write_text("")
        cli_file = tmp_path / "hunknote" / "cli.py"
        cli_file.write_text(
            "def run():\n"
            "    from hunknote.agent.orchestrator import Agent\n"
            "    return Agent()\n"
        )
        group = CommitGroup("C1", ["H1"], "cli", "feat")
        result = _check_import_deps(
            tmp_path, ["hunknote/cli.py"], 0, group, trace,
        )
        assert result is not None
        assert result.layer == ValidationLayer.IMPORT_DEPS
        assert "hunknote.agent.orchestrator" in result.error_output

    def test_passes_when_module_exists(self, tmp_path, trace):
        """No failure when imported module actually exists."""
        (tmp_path / "hunknote" / "compose" / "agent").mkdir(parents=True)
        (tmp_path / "hunknote" / "__init__.py").write_text("")
        (tmp_path / "hunknote" / "compose" / "__init__.py").write_text("")
        (tmp_path / "hunknote" / "compose" / "agent" / "__init__.py").write_text("")
        (tmp_path / "hunknote" / "compose" / "agent" / "models.py").write_text("")
        cli_file = tmp_path / "hunknote" / "cli.py"
        cli_file.write_text(
            "from hunknote.compose.agent.models import HunkSummary\n"
        )
        group = CommitGroup("C1", ["H1"], "cli", "feat")
        result = _check_import_deps(
            tmp_path, ["hunknote/cli.py"], 0, group, trace,
        )
        assert result is None

    def test_ignores_external_modules(self, tmp_path, trace):
        """External imports (stdlib, third-party) are not flagged."""
        (tmp_path / "hunknote").mkdir()
        (tmp_path / "hunknote" / "__init__.py").write_text("")
        cli_file = tmp_path / "hunknote" / "cli.py"
        cli_file.write_text(
            "import os\n"
            "import json\n"
            "from pathlib import Path\n"
            "import requests\n"
        )
        group = CommitGroup("C1", ["H1"], "cli", "feat")
        result = _check_import_deps(
            tmp_path, ["hunknote/cli.py"], 0, group, trace,
        )
        assert result is None

    def test_detects_missing_import_statement(self, tmp_path, trace):
        """Catches 'import X.Y.Z' style (not just 'from X import Y')."""
        (tmp_path / "hunknote").mkdir()
        (tmp_path / "hunknote" / "__init__.py").write_text("")
        cli_file = tmp_path / "hunknote" / "cli.py"
        cli_file.write_text("import hunknote.compose.agent.react\n")
        group = CommitGroup("C1", ["H1"], "cli", "feat")
        result = _check_import_deps(
            tmp_path, ["hunknote/cli.py"], 0, group, trace,
        )
        assert result is not None
        assert "hunknote.compose.agent.react" in result.error_output

    def test_skips_nonexistent_file(self, tmp_path, trace):
        """Files that don't exist in the worktree are skipped gracefully."""
        group = CommitGroup("C1", ["H1"], "cli", "feat")
        result = _check_import_deps(
            tmp_path, ["missing/file.py"], 0, group, trace,
        )
        assert result is None

    def test_catches_test_file_importing_missing_module(self, tmp_path, trace):
        """Test files importing from not-yet-added feature modules are caught."""
        (tmp_path / "hunknote").mkdir()
        (tmp_path / "hunknote" / "__init__.py").write_text("")
        (tmp_path / "tests" / "agent").mkdir(parents=True)
        (tmp_path / "tests" / "__init__.py").write_text("")
        (tmp_path / "tests" / "agent" / "__init__.py").write_text("")
        test_file = tmp_path / "tests" / "agent" / "test_models.py"
        test_file.write_text(
            "from hunknote.compose.agent.models import HunkSummary\n"
            "\n"
            "def test_hunk():\n"
            "    pass\n"
        )
        group = CommitGroup("C2", ["H10"], "tests", "test")
        result = _check_import_deps(
            tmp_path, ["tests/agent/test_models.py"], 0, group, trace,
        )
        assert result is not None
        assert result.layer == ValidationLayer.IMPORT_DEPS
        assert "hunknote.compose.agent.models" in result.error_output
