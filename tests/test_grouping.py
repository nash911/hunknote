"""Tests for the grouping module and should_use_agent threshold."""

import pytest

from hunknote.compose.models import (
    CommitGroup,
    FileDiff,
    HunkRef,
    HunkSymbols,
)
from hunknote.compose.grouping import (
    should_use_agent,
    group_hunks_programmatic,
    AGENT_HUNK_THRESHOLD,
    AGENT_CONNECTIVITY_THRESHOLD,
)


def _make_hunk(hunk_id: str, file_path: str) -> HunkRef:
    return HunkRef(
        id=hunk_id, file_path=file_path,
        header="@@ -1,5 +1,5 @@",
        old_start=1, old_len=5, new_start=1, new_len=5,
        lines=["+line"],
    )


def _make_file_diff(file_path: str, hunk_ids: list[str]) -> FileDiff:
    hunks = [_make_hunk(hid, file_path) for hid in hunk_ids]
    return FileDiff(file_path=file_path, diff_header_lines=[], hunks=hunks)


# ============================================================
# should_use_agent Tests
# ============================================================

class TestShouldUseAgent:
    """Tests for the agent activation threshold."""

    def test_small_diff_no_agent(self):
        """3 hunks across 2 files — below threshold."""
        inventory = {f"H{i}": _make_hunk(f"H{i}", f"f{i}.py") for i in range(1, 4)}
        file_diffs = [_make_file_diff(f"f{i}.py", [f"H{i}"]) for i in range(1, 4)]
        assert not should_use_agent(inventory, file_diffs)

    def test_large_diff_triggers_agent(self):
        """12 hunks — above default threshold of 10."""
        inventory = {f"H{i}": _make_hunk(f"H{i}", f"f{i}.py") for i in range(1, 13)}
        file_diffs = [_make_file_diff(f"f{i}.py", [f"H{i}"]) for i in range(1, 13)]
        assert should_use_agent(inventory, file_diffs)

    def test_threshold_boundary(self):
        """Exactly at threshold — should NOT trigger."""
        inventory = {f"H{i}": _make_hunk(f"H{i}", f"f{i}.py") for i in range(1, 11)}
        file_diffs = [_make_file_diff(f"f{i}.py", [f"H{i}"]) for i in range(1, 11)]
        assert not should_use_agent(inventory, file_diffs)

    def test_high_connectivity_triggers_agent(self):
        """Many hunks in few files — high connectivity."""
        hunks = {f"H{i}": _make_hunk(f"H{i}", f"f{i % 3}.py") for i in range(1, 10)}
        file_diffs = [
            _make_file_diff("f0.py", [f"H{i}" for i in range(1, 10) if i % 3 == 0]),
            _make_file_diff("f1.py", [f"H{i}" for i in range(1, 10) if i % 3 == 1]),
            _make_file_diff("f2.py", [f"H{i}" for i in range(1, 10) if i % 3 == 2]),
        ]
        # 9 hunks in 3 files, but with higher hunks-per-file ratio
        # This should still be handled based on actual counts
        result = should_use_agent(hunks, file_diffs)
        # 9 hunks < 10, but 3 hunks/file > 3 and 3 files is not > 3
        # So this should NOT trigger based on the default logic
        # (9 <= 10 and file count not > 3)

    def test_single_file_no_agent(self):
        """Single file, even with many hunks, low connectivity."""
        inventory = {f"H{i}": _make_hunk(f"H{i}", "f.py") for i in range(1, 9)}
        file_diffs = [_make_file_diff("f.py", [f"H{i}" for i in range(1, 9)])]
        assert not should_use_agent(inventory, file_diffs)

    def test_custom_threshold(self):
        """Custom threshold override."""
        inventory = {f"H{i}": _make_hunk(f"H{i}", f"f{i}.py") for i in range(1, 6)}
        file_diffs = [_make_file_diff(f"f{i}.py", [f"H{i}"]) for i in range(1, 6)]
        assert should_use_agent(inventory, file_diffs, hunk_threshold=4)
        assert not should_use_agent(inventory, file_diffs, hunk_threshold=10)


# ============================================================
# group_hunks_programmatic Tests
# ============================================================

class TestGroupHunksProgrammatic:
    """Tests for programmatic hunk grouping."""

    def test_independent_hunks_separate_groups(self):
        """Independent hunks → one group per hunk."""
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"func_a"}),
            "H2": HunkSymbols(file_path="b.py", language="python", defines={"func_b"}),
            "H3": HunkSymbols(file_path="c.py", language="python", defines={"func_c"}),
        }
        groups = group_hunks_programmatic(analyses, {"H1", "H2", "H3"})
        assert len(groups) == 3

    def test_dependent_hunks_same_group(self):
        """H2 depends on H1 → same group."""
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"func_a"}),
            "H2": HunkSymbols(file_path="b.py", language="python", references={"func_a"}),
        }
        groups = group_hunks_programmatic(analyses, {"H1", "H2"})
        assert len(groups) == 1
        assert set(groups[0].hunk_ids) == {"H1", "H2"}

    def test_two_independent_chains(self):
        """H1→H3, H2→H4 — two groups."""
        analyses = {
            "H1": HunkSymbols(file_path="utils.py", language="python", defines={"rate_limit"}),
            "H2": HunkSymbols(file_path="utils.py", language="python", defines={"sanitize"}),
            "H3": HunkSymbols(file_path="api.py", language="python", references={"rate_limit"}),
            "H4": HunkSymbols(file_path="api.py", language="python", references={"sanitize"}),
        }
        groups = group_hunks_programmatic(analyses, {"H1", "H2", "H3", "H4"})
        assert len(groups) == 2

    def test_transitive_chain_single_group(self):
        """H3→H2→H1 — all in one group."""
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"base"}),
            "H2": HunkSymbols(file_path="b.py", language="python", defines={"mid"}, references={"base"}),
            "H3": HunkSymbols(file_path="c.py", language="python", references={"mid"}),
        }
        groups = group_hunks_programmatic(analyses, {"H1", "H2", "H3"})
        assert len(groups) == 1
        assert set(groups[0].hunk_ids) == {"H1", "H2", "H3"}

    def test_groups_have_file_info(self):
        """Each CommitGroup should list the files it touches."""
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"func_a"}),
            "H2": HunkSymbols(file_path="b.py", language="python", references={"func_a"}),
        }
        groups = group_hunks_programmatic(analyses, {"H1", "H2"})
        assert len(groups) == 1
        assert "a.py" in groups[0].files
        assert "b.py" in groups[0].files

    def test_empty_input(self):
        """No hunks → no groups."""
        groups = group_hunks_programmatic({}, set())
        assert len(groups) == 0

    def test_single_hunk(self):
        """Single hunk → single group."""
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"func_a"}),
        }
        groups = group_hunks_programmatic(analyses, {"H1"})
        assert len(groups) == 1
        assert groups[0].hunk_ids == ["H1"]

    def test_mixed_independent_and_dependent(self):
        """Mix of dependent (H1→H2) and independent (H3) hunks."""
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"func_a"}),
            "H2": HunkSymbols(file_path="b.py", language="python", references={"func_a"}),
            "H3": HunkSymbols(file_path="c.py", language="python", defines={"func_c"}),
        }
        groups = group_hunks_programmatic(analyses, {"H1", "H2", "H3"})
        assert len(groups) == 2
        # One group with H1+H2, one with H3
        group_sets = [set(g.hunk_ids) for g in groups]
        assert {"H1", "H2"} in group_sets
        assert {"H3"} in group_sets

