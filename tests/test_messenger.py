"""Tests for the Compose Agent messenger module."""

import pytest

from hunknote.compose.models import CommitGroup, FileDiff, HunkRef
from hunknote.compose.messenger import (
    build_message_prompt,
    create_plan_from_groups,
    _infer_commit_type,
    _infer_scope,
)


def _make_hunk(hunk_id: str, file_path: str, added: list[str] | None = None) -> HunkRef:
    lines = [f"+{line}" for line in (added or ["line"])]
    return HunkRef(
        id=hunk_id, file_path=file_path,
        header="@@ -1,5 +1,5 @@",
        old_start=1, old_len=5, new_start=1, new_len=5,
        lines=lines,
    )


# ============================================================
# build_message_prompt Tests
# ============================================================

class TestBuildMessagePrompt:
    """Tests for building message-only prompts."""

    def test_prompt_contains_commit_groups(self):
        groups = [
            CommitGroup(hunk_ids=["H1", "H2"], files=["utils.py", "api.py"]),
        ]
        inventory = {
            "H1": _make_hunk("H1", "utils.py", added=["def rate_limit():", "    pass"]),
            "H2": _make_hunk("H2", "api.py", added=["x = rate_limit()"]),
        }
        file_diffs = [
            FileDiff(file_path="utils.py", diff_header_lines=[], hunks=[inventory["H1"]]),
            FileDiff(file_path="api.py", diff_header_lines=[], hunks=[inventory["H2"]]),
        ]
        prompt = build_message_prompt(groups, inventory, file_diffs, "default")
        assert "Commit C1" in prompt
        assert "H1" in prompt
        assert "H2" in prompt
        assert "utils.py" in prompt

    def test_prompt_contains_context(self):
        groups = [CommitGroup(hunk_ids=["H1"], files=["a.py"])]
        inventory = {"H1": _make_hunk("H1", "a.py")}
        file_diffs = [FileDiff(file_path="a.py", diff_header_lines=[], hunks=[inventory["H1"]])]
        prompt = build_message_prompt(
            groups, inventory, file_diffs, "conventional",
            branch="main", recent_commits=["Fix bug", "Add feature"],
        )
        assert "main" in prompt
        assert "Fix bug" in prompt
        assert "conventional" in prompt

    def test_prompt_multiple_groups(self):
        groups = [
            CommitGroup(hunk_ids=["H1"], files=["a.py"]),
            CommitGroup(hunk_ids=["H2"], files=["b.py"]),
        ]
        inventory = {
            "H1": _make_hunk("H1", "a.py"),
            "H2": _make_hunk("H2", "b.py"),
        }
        file_diffs = [
            FileDiff(file_path="a.py", diff_header_lines=[], hunks=[inventory["H1"]]),
            FileDiff(file_path="b.py", diff_header_lines=[], hunks=[inventory["H2"]]),
        ]
        prompt = build_message_prompt(groups, inventory, file_diffs, "default")
        assert "C1" in prompt
        assert "C2" in prompt


# ============================================================
# create_plan_from_groups Tests
# ============================================================

class TestCreatePlanFromGroups:
    """Tests for creating a ComposePlan from groups."""

    def test_placeholder_plan(self):
        groups = [
            CommitGroup(hunk_ids=["H1", "H2"], files=["utils.py", "api.py"]),
            CommitGroup(hunk_ids=["H3"], files=["docs.md"]),
        ]
        plan = create_plan_from_groups(groups)
        assert len(plan.commits) == 2
        assert plan.commits[0].id == "C1"
        assert plan.commits[0].hunks == ["H1", "H2"]
        assert plan.commits[1].id == "C2"
        assert plan.commits[1].hunks == ["H3"]

    def test_plan_from_llm_data(self):
        groups = [CommitGroup(hunk_ids=["H1"], files=["a.py"])]
        plan_data = {
            "version": "1",
            "warnings": [],
            "commits": [{
                "id": "C1",
                "type": "feat",
                "scope": "api",
                "title": "Add rate limiting",
                "bullets": ["Add rate_limit function"],
                "hunks": ["H1"],
            }],
        }
        plan = create_plan_from_groups(groups, plan_data)
        assert len(plan.commits) == 1
        assert plan.commits[0].type == "feat"
        assert plan.commits[0].title == "Add rate limiting"


# ============================================================
# Infer Commit Type / Scope Tests
# ============================================================

class TestInferCommitType:
    """Tests for _infer_commit_type."""

    def test_test_files(self):
        group = CommitGroup(hunk_ids=["H1"], files=["tests/test_api.py"])
        assert _infer_commit_type(group) == "test"

    def test_doc_files(self):
        group = CommitGroup(hunk_ids=["H1"], files=["README.md"])
        assert _infer_commit_type(group) == "docs"

    def test_mixed_files(self):
        group = CommitGroup(hunk_ids=["H1", "H2"], files=["src/api.py", "src/utils.py"])
        assert _infer_commit_type(group) == "feat"

    def test_build_files(self):
        group = CommitGroup(hunk_ids=["H1"], files=["pyproject.toml"])
        assert _infer_commit_type(group) == "build"


class TestInferScope:
    """Tests for _infer_scope."""

    def test_single_file(self):
        group = CommitGroup(hunk_ids=["H1"], files=["src/api.py"])
        scope = _infer_scope(group)
        assert scope == "api"

    def test_common_directory(self):
        group = CommitGroup(hunk_ids=["H1", "H2"], files=["src/auth/login.py", "src/auth/logout.py"])
        scope = _infer_scope(group)
        assert scope == "auth"

    def test_empty_files(self):
        group = CommitGroup(hunk_ids=["H1"], files=[])
        assert _infer_scope(group) == ""

