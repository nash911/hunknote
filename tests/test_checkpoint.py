"""Tests for the checkpoint validator."""

import pytest

from hunknote.compose.models import (
    CheckpointResult,
    ComposePlan,
    HunkSymbols,
    PlannedCommit,
    Violation,
)
from hunknote.compose.checkpoint import (
    validate_commit_checkpoint,
    validate_plan_checkpoints,
)


# ============================================================
# validate_commit_checkpoint Tests
# ============================================================

class TestValidateCommitCheckpoint:
    """Tests for validating individual commit checkpoints."""

    def test_valid_checkpoint_independent_hunks(self):
        """Independent hunks can be in any commit."""
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"func_a"}),
            "H2": HunkSymbols(file_path="b.py", language="python", defines={"func_b"}),
        }
        result = validate_commit_checkpoint(
            committed_hunks={"H1"},
            remaining_hunks={"H2"},
            graph={},
            symbol_analyses=analyses,
        )
        assert result.valid

    def test_valid_checkpoint_dependency_committed(self):
        """H2 depends on H1, both committed → valid."""
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"func_a"}),
            "H2": HunkSymbols(file_path="b.py", language="python", references={"func_a"}),
        }
        result = validate_commit_checkpoint(
            committed_hunks={"H1", "H2"},
            remaining_hunks=set(),
            graph={"H2": {"H1"}},
            symbol_analyses=analyses,
        )
        assert result.valid

    def test_invalid_forward_dependency(self):
        """H1 references func_b defined by H2, but H2 is NOT committed."""
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", references={"func_b"}),
            "H2": HunkSymbols(file_path="b.py", language="python", defines={"func_b"}),
        }
        result = validate_commit_checkpoint(
            committed_hunks={"H1"},
            remaining_hunks={"H2"},
            graph={"H1": {"H2"}},
            symbol_analyses=analyses,
        )
        assert not result.valid
        assert len(result.violations) >= 1
        assert any("func_b" in v.issue for v in result.violations)

    def test_invalid_removed_symbol_still_referenced(self):
        """H1 removes func_old, but H2 (uncommitted) still references it."""
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", removes={"func_old"}),
            "H2": HunkSymbols(file_path="b.py", language="python", references={"func_old"}),
        }
        result = validate_commit_checkpoint(
            committed_hunks={"H1"},
            remaining_hunks={"H2"},
            graph={},
            symbol_analyses=analyses,
        )
        assert not result.valid
        assert any("func_old" in v.issue for v in result.violations)

    def test_invalid_rename_without_consumer_update(self):
        """H1 renames old_func → new_func, but H2 (consumer update) is not committed."""
        analyses = {
            "H1": HunkSymbols(
                file_path="a.py", language="python",
                defines={"new_func"}, removes={"old_func"},
            ),
            "H2": HunkSymbols(
                file_path="b.py", language="python",
                imports_removed={"a.old_func"},
                imports_added={"a.new_func"},
            ),
        }
        result = validate_commit_checkpoint(
            committed_hunks={"H1"},
            remaining_hunks={"H2"},
            graph={},
            symbol_analyses=analyses,
        )
        assert not result.valid
        assert any("old_func" in v.issue for v in result.violations)

    def test_valid_rename_with_consumer_update(self):
        """H1 renames, H2 updates consumer — both committed together."""
        analyses = {
            "H1": HunkSymbols(
                file_path="a.py", language="python",
                defines={"new_func"}, removes={"old_func"},
            ),
            "H2": HunkSymbols(
                file_path="b.py", language="python",
                imports_removed={"a.old_func"},
                imports_added={"a.new_func"},
            ),
        }
        result = validate_commit_checkpoint(
            committed_hunks={"H1", "H2"},
            remaining_hunks=set(),
            graph={},
            symbol_analyses=analyses,
        )
        assert result.valid

    def test_empty_commit(self):
        """Empty commit is always valid."""
        result = validate_commit_checkpoint(
            committed_hunks=set(),
            remaining_hunks={"H1"},
            graph={},
            symbol_analyses={"H1": HunkSymbols(file_path="a.py", language="python")},
        )
        assert result.valid

    def test_all_committed(self):
        """All hunks committed, nothing remaining — valid."""
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"func_a"}),
            "H2": HunkSymbols(file_path="b.py", language="python", references={"func_a"}),
        }
        result = validate_commit_checkpoint(
            committed_hunks={"H1", "H2"},
            remaining_hunks=set(),
            graph={"H2": {"H1"}},
            symbol_analyses=analyses,
        )
        assert result.valid


# ============================================================
# validate_plan_checkpoints Tests
# ============================================================

class TestValidatePlanCheckpoints:
    """Tests for validating all checkpoints in a plan sequentially."""

    def test_valid_plan(self):
        """Two commits in correct order — both valid."""
        plan = ComposePlan(commits=[
            PlannedCommit(id="C1", title="Add func_a", hunks=["H1"]),
            PlannedCommit(id="C2", title="Use func_a", hunks=["H2"]),
        ])
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"func_a"}),
            "H2": HunkSymbols(file_path="b.py", language="python", references={"func_a"}),
        }
        results = validate_plan_checkpoints(
            plan=plan,
            graph={"H2": {"H1"}},
            symbol_analyses=analyses,
            all_hunk_ids={"H1", "H2"},
        )
        assert all(r.valid for _, r in results)

    def test_invalid_plan_wrong_order(self):
        """H2 references func_a defined by H1, but H2 is committed first."""
        plan = ComposePlan(commits=[
            PlannedCommit(id="C1", title="Use func_a", hunks=["H2"]),
            PlannedCommit(id="C2", title="Add func_a", hunks=["H1"]),
        ])
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"func_a"}),
            "H2": HunkSymbols(file_path="b.py", language="python", references={"func_a"}),
        }
        results = validate_plan_checkpoints(
            plan=plan,
            graph={"H2": {"H1"}},
            symbol_analyses=analyses,
            all_hunk_ids={"H1", "H2"},
        )
        # First checkpoint (C1 with H2) should be invalid
        assert not results[0][1].valid

    def test_plan_with_independent_commits(self):
        """Independent commits are always valid regardless of order."""
        plan = ComposePlan(commits=[
            PlannedCommit(id="C1", title="Feature A", hunks=["H1"]),
            PlannedCommit(id="C2", title="Feature B", hunks=["H2"]),
        ])
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"func_a"}),
            "H2": HunkSymbols(file_path="b.py", language="python", defines={"func_b"}),
        }
        results = validate_plan_checkpoints(
            plan=plan,
            graph={},
            symbol_analyses=analyses,
            all_hunk_ids={"H1", "H2"},
        )
        assert all(r.valid for _, r in results)

    def test_three_commit_chain(self):
        """H3→H2→H1: correct order C1(H1), C2(H2), C3(H3)."""
        plan = ComposePlan(commits=[
            PlannedCommit(id="C1", title="Add base", hunks=["H1"]),
            PlannedCommit(id="C2", title="Add middle", hunks=["H2"]),
            PlannedCommit(id="C3", title="Add top", hunks=["H3"]),
        ])
        analyses = {
            "H1": HunkSymbols(file_path="a.py", language="python", defines={"base_func"}),
            "H2": HunkSymbols(file_path="b.py", language="python", defines={"mid_func"}, references={"base_func"}),
            "H3": HunkSymbols(file_path="c.py", language="python", references={"mid_func"}),
        }
        results = validate_plan_checkpoints(
            plan=plan,
            graph={"H2": {"H1"}, "H3": {"H2"}},
            symbol_analyses=analyses,
            all_hunk_ids={"H1", "H2", "H3"},
        )
        assert all(r.valid for _, r in results)

