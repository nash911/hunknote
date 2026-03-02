"""Tests for the Compose Agent orchestrator."""

import pytest

from hunknote.compose.models import (
    CommitGroup,
    ComposePlan,
    FileDiff,
    HunkRef,
    HunkSymbols,
    PlannedCommit,
)
from hunknote.compose.agent import (
    ComposeAgentResult,
    run_compose_agent,
    _merge_to_max_commits,
)


def _make_hunk(hunk_id: str, file_path: str, added: list[str] | None = None) -> HunkRef:
    lines = [f"+{line}" for line in (added or ["line"])]
    return HunkRef(
        id=hunk_id, file_path=file_path,
        header="@@ -1,5 +1,5 @@",
        old_start=1, old_len=5, new_start=1, new_len=5,
        lines=lines,
    )


def _make_file_diff(file_path: str, hunks: list[HunkRef], is_new_file: bool = False) -> FileDiff:
    return FileDiff(
        file_path=file_path, diff_header_lines=[], hunks=hunks,
        is_new_file=is_new_file,
    )


# ============================================================
# Agent Orchestrator Tests
# ============================================================

class TestRunComposeAgent:
    """Tests for the run_compose_agent orchestrator."""

    def test_small_diff_skips_agent(self):
        """Below threshold → used_agent=False, empty plan."""
        hunks = {f"H{i}": _make_hunk(f"H{i}", f"f{i}.py") for i in range(1, 4)}
        file_diffs = [_make_file_diff(f"f{i}.py", [hunks[f"H{i}"]]) for i in range(1, 4)]

        result = run_compose_agent(
            file_diffs=file_diffs,
            inventory=hunks,
            style="default",
            max_commits=6,
        )
        assert not result.used_agent
        assert len(result.plan.commits) == 0

    def test_force_agent_mode(self):
        """force_agent=True activates agent even for small diffs."""
        hunks = {
            "H1": _make_hunk("H1", "a.py", added=["def func_a():", "    pass"]),
            "H2": _make_hunk("H2", "b.py", added=["def func_b():", "    pass"]),
        }
        file_diffs = [
            _make_file_diff("a.py", [hunks["H1"]]),
            _make_file_diff("b.py", [hunks["H2"]]),
        ]

        result = run_compose_agent(
            file_diffs=file_diffs,
            inventory=hunks,
            style="default",
            max_commits=6,
            force_agent=True,
        )
        assert result.used_agent
        assert len(result.groups) >= 1
        assert len(result.symbol_analyses) == 2

    def test_agent_extracts_symbols(self):
        """Agent should extract symbols from all hunks."""
        hunks = {
            "H1": _make_hunk("H1", "utils.py", added=["def rate_limit(key):", "    pass"]),
            "H2": _make_hunk("H2", "api.py", added=["result = rate_limit(k)"]),
        }
        file_diffs = [
            _make_file_diff("utils.py", [hunks["H1"]]),
            _make_file_diff("api.py", [hunks["H2"]]),
        ]

        result = run_compose_agent(
            file_diffs=file_diffs,
            inventory=hunks,
            style="default",
            max_commits=6,
            force_agent=True,
        )
        assert "H1" in result.symbol_analyses
        assert "H2" in result.symbol_analyses
        assert "rate_limit" in result.symbol_analyses["H1"].defines

    def test_agent_builds_graph(self):
        """Agent should build hunk dependency graph."""
        hunks = {
            "H1": _make_hunk("H1", "utils.py", added=["def rate_limit(key):", "    pass"]),
            "H2": _make_hunk("H2", "api.py", added=["result = rate_limit(k)"]),
        }
        file_diffs = [
            _make_file_diff("utils.py", [hunks["H1"]]),
            _make_file_diff("api.py", [hunks["H2"]]),
        ]

        result = run_compose_agent(
            file_diffs=file_diffs,
            inventory=hunks,
            style="default",
            max_commits=6,
            force_agent=True,
        )
        # H2 should depend on H1 (rate_limit)
        assert "H2" in result.graph
        assert "H1" in result.graph["H2"]

    def test_agent_groups_dependent_hunks(self):
        """Dependent hunks should be in the same group."""
        hunks = {
            "H1": _make_hunk("H1", "utils.py", added=["def rate_limit(key):", "    pass"]),
            "H2": _make_hunk("H2", "api.py", added=["result = rate_limit(k)"]),
            "H3": _make_hunk("H3", "other.py", added=["def unrelated():", "    pass"]),
        }
        file_diffs = [
            _make_file_diff("utils.py", [hunks["H1"]]),
            _make_file_diff("api.py", [hunks["H2"]]),
            _make_file_diff("other.py", [hunks["H3"]]),
        ]

        result = run_compose_agent(
            file_diffs=file_diffs,
            inventory=hunks,
            style="default",
            max_commits=6,
            force_agent=True,
        )
        assert result.used_agent
        # H1 and H2 should be in the same group, H3 separate
        assert len(result.groups) == 2

    def test_agent_creates_placeholder_plan_without_provider(self):
        """Without an LLM provider, agent creates placeholder messages."""
        hunks = {
            "H1": _make_hunk("H1", "a.py", added=["def func_a():", "    pass"]),
        }
        file_diffs = [_make_file_diff("a.py", [hunks["H1"]])]

        result = run_compose_agent(
            file_diffs=file_diffs,
            inventory=hunks,
            style="default",
            max_commits=6,
            force_agent=True,
            provider=None,
        )
        assert result.used_agent
        assert len(result.plan.commits) >= 1
        assert result.plan.commits[0].hunks == ["H1"]

    def test_agent_validates_checkpoints(self):
        """Agent should validate plan checkpoints."""
        hunks = {
            "H1": _make_hunk("H1", "a.py", added=["def func_a():", "    pass"]),
            "H2": _make_hunk("H2", "b.py", added=["x = func_a()"]),
        }
        file_diffs = [
            _make_file_diff("a.py", [hunks["H1"]]),
            _make_file_diff("b.py", [hunks["H2"]]),
        ]

        result = run_compose_agent(
            file_diffs=file_diffs,
            inventory=hunks,
            style="default",
            max_commits=6,
            force_agent=True,
        )
        assert len(result.checkpoint_results) >= 1


# ============================================================
# Merge to Max Commits Tests
# ============================================================

class TestMergeToMaxCommits:
    """Tests for _merge_to_max_commits."""

    def test_no_merge_needed(self):
        groups = [
            CommitGroup(hunk_ids=["H1"], files=["a.py"]),
            CommitGroup(hunk_ids=["H2"], files=["b.py"]),
        ]
        result = _merge_to_max_commits(groups, max_commits=3)
        assert len(result) == 2

    def test_merge_to_one(self):
        groups = [
            CommitGroup(hunk_ids=["H1"], files=["a.py"]),
            CommitGroup(hunk_ids=["H2"], files=["b.py"]),
            CommitGroup(hunk_ids=["H3"], files=["c.py"]),
        ]
        result = _merge_to_max_commits(groups, max_commits=1)
        assert len(result) == 1
        assert len(result[0].hunk_ids) == 3

    def test_merge_smallest_first(self):
        groups = [
            CommitGroup(hunk_ids=["H1", "H2", "H3"], files=["a.py"]),
            CommitGroup(hunk_ids=["H4"], files=["b.py"]),
            CommitGroup(hunk_ids=["H5"], files=["c.py"]),
        ]
        result = _merge_to_max_commits(groups, max_commits=2)
        assert len(result) == 2
        # The two smallest (H4 and H5) should be merged
        sizes = sorted(len(g.hunk_ids) for g in result)
        assert sizes == [2, 3]

    def test_single_group_unchanged(self):
        groups = [CommitGroup(hunk_ids=["H1", "H2"], files=["a.py"])]
        result = _merge_to_max_commits(groups, max_commits=1)
        assert len(result) == 1


# ============================================================
# End-to-End Agent Tests (Multi-Feature Scenario)
# ============================================================

class TestAgentEndToEnd:
    """End-to-end tests simulating real multi-feature diffs."""

    def test_two_features_in_shared_file(self):
        """The classic granularity gap: two features touching a shared utility file.

        H1: Add rate_limit in utils.py (Feature X)
        H2: Add sanitize in utils.py (Feature Y)
        H3: Use rate_limit in api.py (Feature X)
        H4: Use sanitize in api.py (Feature Y)

        File-level analysis would merge all 4 into one commit.
        Agent should produce 2 groups: {H1,H3} and {H2,H4}.
        """
        hunks = {
            "H1": _make_hunk("H1", "utils.py", added=["def rate_limit(key):", "    pass"]),
            "H2": _make_hunk("H2", "utils.py", added=["def sanitize(input):", "    pass"]),
            "H3": _make_hunk("H3", "api.py", added=["x = rate_limit(k)"]),
            "H4": _make_hunk("H4", "api.py", added=["y = sanitize(data)"]),
        }
        file_diffs = [
            _make_file_diff("utils.py", [hunks["H1"], hunks["H2"]]),
            _make_file_diff("api.py", [hunks["H3"], hunks["H4"]]),
        ]

        result = run_compose_agent(
            file_diffs=file_diffs,
            inventory=hunks,
            style="default",
            max_commits=6,
            force_agent=True,
        )
        assert result.used_agent
        assert len(result.groups) == 2

        group_sets = [set(g.hunk_ids) for g in result.groups]
        assert {"H1", "H3"} in group_sets
        assert {"H2", "H4"} in group_sets

    def test_rename_across_files(self):
        """A rename in one file requires consumer updates in another.

        H1: Rename old_func → new_func in utils.py
        H2: Update import in api.py

        Both must be in the same group.
        """
        hunks = {
            "H1": _make_hunk("H1", "utils.py", added=[
                "def new_func():", "    pass",
            ]),
            "H2": _make_hunk("H2", "api.py", added=[
                "from utils import new_func",
            ]),
        }
        # Simulate removal in H1
        hunks["H1"].lines = [
            "-def old_func():", "-    pass",
            "+def new_func():", "+    pass",
        ]
        # Simulate import update in H2
        hunks["H2"].lines = [
            "-from utils import old_func",
            "+from utils import new_func",
        ]

        file_diffs = [
            _make_file_diff("utils.py", [hunks["H1"]]),
            _make_file_diff("api.py", [hunks["H2"]]),
        ]

        result = run_compose_agent(
            file_diffs=file_diffs,
            inventory=hunks,
            style="default",
            max_commits=6,
            force_agent=True,
        )
        assert result.used_agent
        # Both should be in same group due to rename dependency
        assert len(result.groups) == 1
        assert set(result.groups[0].hunk_ids) == {"H1", "H2"}

    def test_max_commits_respected(self):
        """Agent should merge groups to respect max_commits."""
        hunks = {
            f"H{i}": _make_hunk(f"H{i}", f"f{i}.py", added=[f"def func_{i}():", "    pass"])
            for i in range(1, 8)
        }
        file_diffs = [
            _make_file_diff(f"f{i}.py", [hunks[f"H{i}"]]) for i in range(1, 8)
        ]

        result = run_compose_agent(
            file_diffs=file_diffs,
            inventory=hunks,
            style="default",
            max_commits=3,
            force_agent=True,
        )
        assert result.used_agent
        assert len(result.groups) <= 3

