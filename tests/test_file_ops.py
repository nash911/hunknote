"""Tests for file-operations (rename/deletion) support in the compose pipeline.

Tests cover:
- build_file_ops_inventory: creating synthetic HunkRef entries
- is_file_op_id: identifying synthetic IDs
- format_inventory_for_llm: including [FILE OPERATIONS] section
- build_commit_patch: emitting rename/deletion headers in patches
- End-to-end: git apply --cached with rename patches
"""

import subprocess
from pathlib import Path

import pytest

from hunknote.compose.inventory import (
    RENAME_PREFIX,
    DELETE_PREFIX,
    build_file_ops_inventory,
    build_hunk_inventory,
    format_inventory_for_llm,
    is_file_op_id,
)
from hunknote.compose.models import ComposePlan, FileDiff, HunkRef, PlannedCommit
from hunknote.compose.patch import build_commit_patch
from hunknote.compose.validation import validate_plan


# ── Fixtures ──


def _hunk(hunk_id: str, file_path: str) -> HunkRef:
    return HunkRef(
        id=hunk_id, file_path=file_path,
        header="@@ -1,3 +1,4 @@",
        old_start=1, old_len=3, new_start=1, new_len=4,
        lines=["@@ -1,3 +1,4 @@", " line1", "+added", " line3"],
    )


def _file_diff(
    file_path: str, hunks=None, is_binary=False, is_new_file=False,
    is_deleted_file=False, is_renamed=False, old_path=None,
) -> FileDiff:
    header = [f"diff --git a/{old_path or file_path} b/{file_path}"]
    if is_renamed and old_path:
        header += [
            "similarity index 100%",
            f"rename from {old_path}",
            f"rename to {file_path}",
        ]
    if is_deleted_file:
        header += ["deleted file mode 100644"]
    return FileDiff(
        file_path=file_path,
        diff_header_lines=header,
        hunks=hunks or [],
        is_binary=is_binary, is_new_file=is_new_file,
        is_deleted_file=is_deleted_file, is_renamed=is_renamed,
        old_path=old_path,
    )


# ── build_file_ops_inventory ──


class TestBuildFileOpsInventory:
    """Tests for build_file_ops_inventory."""

    def test_pure_rename_gets_synthetic_entry(self):
        """A rename with no hunks produces a R_* entry."""
        diffs = [_file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py")]
        ops = build_file_ops_inventory(diffs)

        assert len(ops) == 1
        hid = list(ops.keys())[0]
        assert hid.startswith(RENAME_PREFIX)
        assert ops[hid].file_path == "src/helpers.py"
        assert "rename" in ops[hid].header.lower()

    def test_rename_with_hunks_is_ignored(self):
        """A rename that also has content hunks is NOT a file-op."""
        h = _hunk("H1_abc", "src/helpers.py")
        diffs = [_file_diff("src/helpers.py", hunks=[h], is_renamed=True, old_path="src/utils.py")]
        ops = build_file_ops_inventory(diffs)
        assert len(ops) == 0

    def test_hunkless_deletion_gets_synthetic_entry(self):
        """A deletion of an empty file gets a D_* entry."""
        diffs = [_file_diff("src/__init__.py", is_deleted_file=True)]
        ops = build_file_ops_inventory(diffs)

        assert len(ops) == 1
        hid = list(ops.keys())[0]
        assert hid.startswith(DELETE_PREFIX)
        assert ops[hid].file_path == "src/__init__.py"

    def test_deletion_with_hunks_is_ignored(self):
        """A deletion that has content-removal hunks is NOT a file-op."""
        h = _hunk("H1_abc", "src/old.py")
        diffs = [_file_diff("src/old.py", hunks=[h], is_deleted_file=True)]
        ops = build_file_ops_inventory(diffs)
        assert len(ops) == 0

    def test_binary_file_is_ignored(self):
        """Binary files are not file-ops (they go to residual)."""
        diffs = [_file_diff("image.png", is_binary=True)]
        ops = build_file_ops_inventory(diffs)
        assert len(ops) == 0

    def test_new_empty_file_is_ignored(self):
        """New empty files are not file-ops (they go to residual)."""
        diffs = [_file_diff("src/__init__.py", is_new_file=True)]
        ops = build_file_ops_inventory(diffs)
        assert len(ops) == 0

    def test_regular_file_is_ignored(self):
        """A regular file with hunks produces no file-ops."""
        h = _hunk("H1_abc", "src/main.py")
        diffs = [_file_diff("src/main.py", hunks=[h])]
        ops = build_file_ops_inventory(diffs)
        assert len(ops) == 0

    def test_multiple_renames_and_deletes(self):
        """Multiple renames and deletions each get their own entry."""
        diffs = [
            _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py"),
            _file_diff("src/new_config.py", is_renamed=True, old_path="src/config.py"),
            _file_diff("src/old.py", is_deleted_file=True),
        ]
        ops = build_file_ops_inventory(diffs)
        assert len(ops) == 3

        renames = [k for k in ops if k.startswith(RENAME_PREFIX)]
        deletes = [k for k in ops if k.startswith(DELETE_PREFIX)]
        assert len(renames) == 2
        assert len(deletes) == 1

    def test_synthetic_lines_contain_diff_header(self):
        """The synthetic HunkRef stores the diff header lines."""
        diffs = [_file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py")]
        ops = build_file_ops_inventory(diffs)
        hid = list(ops.keys())[0]
        assert "rename from src/utils.py" in "\n".join(ops[hid].lines)
        assert "rename to src/helpers.py" in "\n".join(ops[hid].lines)


# ── is_file_op_id ──


class TestIsFileOpId:
    """Tests for is_file_op_id."""

    def test_rename_id(self):
        assert is_file_op_id("R_1_abc123") is True

    def test_delete_id(self):
        assert is_file_op_id("D_1_abc123") is True

    def test_regular_hunk_id(self):
        assert is_file_op_id("H1_abc123") is False

    def test_empty_string(self):
        assert is_file_op_id("") is False


# ── format_inventory_for_llm with file ops ──


class TestFormatInventoryWithFileOps:
    """Tests for format_inventory_for_llm including file operations."""

    def test_includes_file_operations_section(self):
        """FILE OPERATIONS section is present when renames exist."""
        h1 = _hunk("H1_abc", "src/main.py")
        diffs = [
            _file_diff("src/main.py", hunks=[h1]),
            _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py"),
        ]
        formatted = format_inventory_for_llm(diffs)

        assert "[FILE OPERATIONS]" in formatted
        assert "R_" in formatted
        assert "src/utils.py" in formatted
        assert "src/helpers.py" in formatted

    def test_no_file_operations_section_when_none(self):
        """No FILE OPERATIONS section when only regular hunks."""
        h1 = _hunk("H1_abc", "src/main.py")
        diffs = [_file_diff("src/main.py", hunks=[h1])]
        formatted = format_inventory_for_llm(diffs)
        assert "[FILE OPERATIONS]" not in formatted

    def test_pure_rename_not_in_hunk_inventory_section(self):
        """Pure renames should NOT appear in the [HUNK INVENTORY] section."""
        h1 = _hunk("H1_abc", "src/main.py")
        diffs = [
            _file_diff("src/main.py", hunks=[h1]),
            _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py"),
        ]
        formatted = format_inventory_for_llm(diffs)
        # The HUNK INVENTORY section should NOT list the renamed file
        hunk_section = formatted.split("[FILE OPERATIONS]")[0]
        assert "src/helpers.py" not in hunk_section

    def test_deletion_in_file_operations_section(self):
        """Hunkless deletions appear in FILE OPERATIONS section."""
        h1 = _hunk("H1_abc", "src/main.py")
        diffs = [
            _file_diff("src/main.py", hunks=[h1]),
            _file_diff("src/old.py", is_deleted_file=True),
        ]
        formatted = format_inventory_for_llm(diffs)
        assert "D_" in formatted
        assert "src/old.py" in formatted


# ── build_commit_patch with file ops ──


class TestBuildCommitPatchWithFileOps:
    """Tests for build_commit_patch including synthetic file-op entries."""

    def test_rename_only_commit(self):
        """A commit with only a R_* entry emits the diff header."""
        rename_diff = _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py")
        ops = build_file_ops_inventory([rename_diff])
        rename_id = list(ops.keys())[0]

        commit = PlannedCommit(id="C1", title="Rename utils", hunks=[rename_id])
        patch = build_commit_patch(commit, ops, [rename_diff])

        assert "rename from src/utils.py" in patch
        assert "rename to src/helpers.py" in patch

    def test_rename_plus_regular_hunk(self):
        """A commit with a rename and a regular hunk emits both."""
        rename_diff = _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py")
        h1 = _hunk("H1_abc", "src/main.py")
        main_diff = _file_diff("src/main.py", hunks=[h1])

        ops = build_file_ops_inventory([rename_diff])
        inventory = {"H1_abc": h1}
        inventory.update(ops)
        rename_id = list(ops.keys())[0]

        commit = PlannedCommit(
            id="C1", title="Rename and update imports",
            hunks=[rename_id, "H1_abc"],
        )
        patch = build_commit_patch(commit, inventory, [rename_diff, main_diff])

        assert "rename from src/utils.py" in patch
        assert "rename to src/helpers.py" in patch
        assert "@@ -1,3 +1,4 @@" in patch

    def test_file_ops_before_regular_hunks(self):
        """File-op headers come before regular hunk patches."""
        rename_diff = _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py")
        h1 = _hunk("H1_abc", "src/main.py")
        main_diff = _file_diff("src/main.py", hunks=[h1])

        ops = build_file_ops_inventory([rename_diff])
        inventory = {"H1_abc": h1}
        inventory.update(ops)
        rename_id = list(ops.keys())[0]

        commit = PlannedCommit(
            id="C1", title="Rename and update",
            hunks=[rename_id, "H1_abc"],
        )
        patch = build_commit_patch(commit, inventory, [rename_diff, main_diff])

        rename_pos = patch.index("rename from")
        hunk_pos = patch.index("@@ -1,3 +1,4 @@")
        assert rename_pos < hunk_pos, "Rename header should come before regular hunks"


# ── validate_plan with file ops ──


class TestValidatePlanWithFileOps:
    """Tests for plan validation accepting file-op IDs."""

    def test_file_op_ids_are_valid(self):
        """File-op IDs in inventory should not produce validation errors."""
        h1 = _hunk("H1_abc", "src/main.py")
        rename_diff = _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py")
        ops = build_file_ops_inventory([rename_diff])
        rename_id = list(ops.keys())[0]

        inventory = {"H1_abc": h1}
        inventory.update(ops)

        plan = ComposePlan(
            version="1", warnings=[],
            commits=[
                PlannedCommit(
                    id="C1", title="Rename and update",
                    hunks=[rename_id, "H1_abc"],
                ),
            ],
        )
        errors = validate_plan(plan, inventory, max_commits=5)
        assert errors == []

    def test_unassigned_file_op_produces_warning(self):
        """An unassigned file-op ID produces a warning (not error)."""
        h1 = _hunk("H1_abc", "src/main.py")
        rename_diff = _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py")
        ops = build_file_ops_inventory([rename_diff])

        inventory = {"H1_abc": h1}
        inventory.update(ops)

        plan = ComposePlan(
            version="1", warnings=[],
            commits=[
                PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
            ],
        )
        errors = validate_plan(plan, inventory, max_commits=5)
        # No errors — unassigned hunks are warnings, not errors
        assert errors == []
        # But there should be a warning about the unassigned file-op
        assert any("Unassigned" in w for w in plan.warnings)


# ── End-to-end: git apply --cached ──


class TestGitApplyWithRename:
    """End-to-end test that git apply --cached handles rename patches."""

    def test_rename_patch_applies_cleanly(self, tmp_path):
        """A patch with a rename header applies via git apply --cached."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)

        # Create initial file
        (repo / "src").mkdir()
        (repo / "src" / "utils.py").write_text("def helper():\n    return 42\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        # Build a rename-only patch
        rename_diff = _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py")
        ops = build_file_ops_inventory([rename_diff])
        rename_id = list(ops.keys())[0]

        commit = PlannedCommit(id="C1", title="Rename", hunks=[rename_id])
        patch = build_commit_patch(commit, ops, [rename_diff])

        # Apply it
        patch_file = repo / "test.patch"
        patch_file.write_text(patch)
        result = subprocess.run(
            ["git", "apply", "--cached", str(patch_file)],
            capture_output=True, text=True, cwd=repo,
        )
        assert result.returncode == 0, f"git apply failed: {result.stderr}"

        # Verify the rename is staged
        status = subprocess.run(
            ["git", "diff", "--cached", "--name-status"],
            capture_output=True, text=True, cwd=repo,
        )
        assert "src/helpers.py" in status.stdout

    def test_rename_plus_import_update_patch(self, tmp_path):
        """A patch with rename + import update applies correctly."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)

        (repo / "src").mkdir()
        (repo / "src" / "utils.py").write_text("def helper():\n    return 42\n")
        (repo / "src" / "main.py").write_text("from src.utils import helper\n\ndef run():\n    return helper()\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        # Build combined patch: rename + import update
        rename_diff = _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py")
        import_hunk = HunkRef(
            id="H1_abc", file_path="src/main.py",
            header="@@ -1,4 +1,4 @@",
            old_start=1, old_len=4, new_start=1, new_len=4,
            lines=[
                "@@ -1,4 +1,4 @@",
                "-from src.utils import helper",
                "+from src.helpers import helper",
                " ",
                " def run():",
                "     return helper()",
            ],
        )
        main_diff = FileDiff(
            file_path="src/main.py",
            diff_header_lines=[
                "diff --git a/src/main.py b/src/main.py",
                "index e9521c9..62da199 100644",
                "--- a/src/main.py",
                "+++ b/src/main.py",
            ],
            hunks=[import_hunk],
        )

        ops = build_file_ops_inventory([rename_diff])
        rename_id = list(ops.keys())[0]
        inventory = {"H1_abc": import_hunk}
        inventory.update(ops)

        commit = PlannedCommit(
            id="C1", title="Rename and update imports",
            hunks=[rename_id, "H1_abc"],
        )
        patch = build_commit_patch(commit, inventory, [rename_diff, main_diff])

        patch_file = repo / "test.patch"
        patch_file.write_text(patch)
        result = subprocess.run(
            ["git", "apply", "--cached", str(patch_file)],
            capture_output=True, text=True, cwd=repo,
        )
        assert result.returncode == 0, f"git apply failed: {result.stderr}"

        # Verify both changes are staged
        status = subprocess.run(
            ["git", "diff", "--cached", "--name-status"],
            capture_output=True, text=True, cwd=repo,
        )
        assert "src/helpers.py" in status.stdout
        assert "src/main.py" in status.stdout


# ── Phase 2 context includes file ops ──


class TestPhase2ContextIncludesFileOps:
    """Tests for Phase 2 initial context including file operations."""

    def test_initial_context_includes_rename_entries(self):
        """The Phase 2 initial context shows RENAME entries."""
        from hunknote.compose.agent.phases.dependency import _build_initial_context
        from hunknote.compose.agent.models import DependencyGraph, HunkSummary

        h1 = _hunk("H1_abc", "src/main.py")
        rename_diff = _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py")
        ops = build_file_ops_inventory([rename_diff])
        rename_id = list(ops.keys())[0]

        inventory = {"H1_abc": h1}
        inventory.update(ops)

        summaries = {
            "H1_abc": HunkSummary(
                hunk_id="H1_abc", file_path="src/main.py",
                intent="Update imports", category="refactor",
            ),
        }

        graph = DependencyGraph()
        context = _build_initial_context(inventory, summaries, graph)

        assert "FILE OPERATIONS" in context
        assert rename_id in context
        assert "RENAME" in context
        assert "src/utils.py" in context

    def test_initial_context_includes_delete_entries(self):
        """The Phase 2 initial context shows DELETE entries."""
        from hunknote.compose.agent.phases.dependency import _build_initial_context
        from hunknote.compose.agent.models import DependencyGraph, HunkSummary

        h1 = _hunk("H1_abc", "src/main.py")
        del_diff = _file_diff("src/old.py", is_deleted_file=True)
        ops = build_file_ops_inventory([del_diff])
        del_id = list(ops.keys())[0]

        inventory = {"H1_abc": h1}
        inventory.update(ops)

        summaries = {
            "H1_abc": HunkSummary(
                hunk_id="H1_abc", file_path="src/main.py",
                intent="Remove old import", category="chore",
            ),
        }

        graph = DependencyGraph()
        context = _build_initial_context(inventory, summaries, graph)

        assert "DELETE" in context
        assert del_id in context

    def test_no_file_ops_section_when_no_ops(self):
        """No FILE OPERATIONS section when there are no renames/deletions."""
        from hunknote.compose.agent.phases.dependency import _build_initial_context
        from hunknote.compose.agent.models import DependencyGraph, HunkSummary

        h1 = _hunk("H1_abc", "src/main.py")
        inventory = {"H1_abc": h1}
        summaries = {
            "H1_abc": HunkSummary(
                hunk_id="H1_abc", file_path="src/main.py",
                intent="Add feature", category="feat",
            ),
        }

        graph = DependencyGraph()
        context = _build_initial_context(inventory, summaries, graph)

        assert "FILE OPERATIONS" not in context


# ── list_file_operations tool ──


class TestListFileOperationsTool:
    """Tests for the list_file_operations ReAct agent tool."""

    def test_returns_rename_info(self):
        """Tool shows rename details."""
        from hunknote.compose.agent.tools import execute_tool

        rename_diff = _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py")
        ops = build_file_ops_inventory([rename_diff])
        rename_id = list(ops.keys())[0]
        inventory = dict(ops)

        result = execute_tool("list_file_operations", {}, Path("/tmp"), inventory)
        assert result.success
        assert rename_id in result.output
        assert "RENAME" in result.output
        assert "src/helpers.py" in result.output

    def test_returns_delete_info(self):
        """Tool shows deletion details."""
        from hunknote.compose.agent.tools import execute_tool

        del_diff = _file_diff("src/old.py", is_deleted_file=True)
        ops = build_file_ops_inventory([del_diff])
        del_id = list(ops.keys())[0]
        inventory = dict(ops)

        result = execute_tool("list_file_operations", {}, Path("/tmp"), inventory)
        assert result.success
        assert del_id in result.output
        assert "DELETE" in result.output

    def test_empty_when_no_file_ops(self):
        """Returns a descriptive message when no file-ops exist."""
        from hunknote.compose.agent.tools import execute_tool

        h1 = _hunk("H1_abc", "src/main.py")
        inventory = {"H1_abc": h1}

        result = execute_tool("list_file_operations", {}, Path("/tmp"), inventory)
        assert result.success
        assert "no file operations" in result.output.lower()


# ── list_hunks excludes file ops ──


class TestListHunksExcludesFileOps:
    """list_hunks should NOT show R_*/D_* entries."""

    def test_file_ops_excluded_from_list_hunks(self):
        from hunknote.compose.agent.tools import execute_tool

        h1 = _hunk("H1_abc", "src/main.py")
        rename_diff = _file_diff("src/helpers.py", is_renamed=True, old_path="src/utils.py")
        ops = build_file_ops_inventory([rename_diff])

        inventory = {"H1_abc": h1}
        inventory.update(ops)

        result = execute_tool("list_hunks", {}, Path("/tmp"), inventory)
        assert "H1_abc" in result.output
        assert "R_" not in result.output

