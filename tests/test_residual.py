"""Tests for hunknote.compose.residual — residual commit builder.

Tests cover:
- collect_residual_files: identifying uncovered binary/empty/mode-change files
- build_residual_commit: generating the housekeeping commit
- append_residual_to_plan: in-place plan modification
- execute_residual_commit: staging residual files via git add
"""

import subprocess
from dataclasses import field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hunknote.compose.models import ComposePlan, FileDiff, HunkRef, PlannedCommit
from hunknote.compose.residual import (
    append_residual_to_plan,
    build_residual_commit,
    collect_residual_files,
)


# ── Fixtures ──


def _make_hunk(hunk_id: str, file_path: str) -> HunkRef:
    """Create a minimal HunkRef."""
    return HunkRef(
        id=hunk_id,
        file_path=file_path,
        header="@@ -1,3 +1,4 @@",
        old_start=1,
        old_len=3,
        new_start=1,
        new_len=4,
        lines=["@@ -1,3 +1,4 @@", " line1", "+added", " line3"],
    )


def _make_file_diff(
    file_path: str,
    hunks: list[HunkRef] | None = None,
    is_binary: bool = False,
    is_new_file: bool = False,
    is_deleted_file: bool = False,
    is_renamed: bool = False,
    old_path: str | None = None,
) -> FileDiff:
    """Create a minimal FileDiff."""
    return FileDiff(
        file_path=file_path,
        diff_header_lines=[f"diff --git a/{file_path} b/{file_path}"],
        hunks=hunks or [],
        is_binary=is_binary,
        is_new_file=is_new_file,
        is_deleted_file=is_deleted_file,
        is_renamed=is_renamed,
        old_path=old_path,
    )


def _make_plan(commits: list[PlannedCommit]) -> ComposePlan:
    """Create a minimal ComposePlan."""
    return ComposePlan(version="1", warnings=[], commits=commits)


# ── collect_residual_files ──


class TestCollectResidualFiles:
    """Tests for collect_residual_files."""

    def test_no_residual_when_all_hunks_covered(self):
        """All files have hunks assigned — no residuals."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        h2 = _make_hunk("H2_def", "src/utils.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("src/utils.py", hunks=[h2]),
        ]
        inventory = {"H1_abc": h1, "H2_def": h2}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc", "H2_def"]),
        ])

        result = collect_residual_files(file_diffs, plan, inventory)
        assert result == []

    def test_binary_file_is_residual(self):
        """Binary files (no hunks) are always residual."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("image.png", is_binary=True),
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        result = collect_residual_files(file_diffs, plan, inventory)
        assert len(result) == 1
        assert result[0].file_path == "image.png"

    def test_empty_new_file_is_residual(self):
        """Empty new files (e.g., __init__.py) are residual."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("src/pkg/__init__.py", is_new_file=True),
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        result = collect_residual_files(file_diffs, plan, inventory)
        assert len(result) == 1
        assert result[0].file_path == "src/pkg/__init__.py"

    def test_mode_change_file_is_residual(self):
        """Files with only mode changes (no hunks) are residual."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("scripts/run.sh"),  # mode change only — no hunks
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        result = collect_residual_files(file_diffs, plan, inventory)
        assert len(result) == 1
        assert result[0].file_path == "scripts/run.sh"

    def test_multiple_residual_types(self):
        """Mix of binary, empty, and mode-change residuals."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("image.png", is_binary=True),
            _make_file_diff("src/pkg/__init__.py", is_new_file=True),
            _make_file_diff("poetry.lock", is_binary=True),
            _make_file_diff("scripts/run.sh"),  # mode change
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        result = collect_residual_files(file_diffs, plan, inventory)
        assert len(result) == 4
        paths = {fd.file_path for fd in result}
        assert paths == {"image.png", "src/pkg/__init__.py", "poetry.lock", "scripts/run.sh"}

    def test_no_residual_when_no_file_diffs(self):
        """Edge case: empty file_diffs list."""
        plan = _make_plan([])
        result = collect_residual_files([], plan, {})
        assert result == []

    def test_deleted_file_no_hunks_is_residual(self):
        """Deleted files with no hunks are residual."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("old_config.py", is_deleted_file=True),
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="cleanup", hunks=["H1_abc"]),
        ])

        result = collect_residual_files(file_diffs, plan, inventory)
        assert len(result) == 1
        assert result[0].file_path == "old_config.py"
        assert result[0].is_deleted_file

    def test_renamed_file_no_hunks_is_residual(self):
        """Renamed files with no content changes are residual."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff(
                "src/new_name.py",
                is_renamed=True,
                old_path="src/old_name.py",
            ),
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="rename", hunks=["H1_abc"]),
        ])

        result = collect_residual_files(file_diffs, plan, inventory)
        assert len(result) == 1
        assert result[0].file_path == "src/new_name.py"
        assert result[0].is_renamed
        assert result[0].old_path == "src/old_name.py"


# ── build_residual_commit ──


class TestBuildResidualCommit:
    """Tests for build_residual_commit."""

    def test_returns_none_when_no_residuals(self):
        """No residual files → returns None."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [_make_file_diff("src/main.py", hunks=[h1])]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        result = build_residual_commit(file_diffs, plan, inventory)
        assert result is None

    def test_creates_commit_for_binary_files(self):
        """Creates a chore commit for binary residuals."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("image.png", is_binary=True),
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        commit = build_residual_commit(file_diffs, plan, inventory)
        assert commit is not None
        assert commit.id == "C2"
        assert commit.type == "chore"
        assert commit.hunks == []
        assert "binary" in commit.title.lower()

    def test_commit_id_follows_last_commit(self):
        """Residual commit ID = C{N+1} where N = existing commits."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        h2 = _make_hunk("H2_def", "src/utils.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("src/utils.py", hunks=[h2]),
            _make_file_diff("data.bin", is_binary=True),
        ]
        inventory = {"H1_abc": h1, "H2_def": h2}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
            PlannedCommit(id="C2", title="refactor", hunks=["H2_def"]),
            PlannedCommit(id="C3", title="test", hunks=[]),
        ])

        commit = build_residual_commit(file_diffs, plan, inventory)
        assert commit is not None
        assert commit.id == "C4"

    def test_bullets_describe_binary_files(self):
        """Commit bullets list binary file names."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("icon.png", is_binary=True),
            _make_file_diff("poetry.lock", is_binary=True),
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        commit = build_residual_commit(file_diffs, plan, inventory)
        assert commit is not None
        bullets_text = " ".join(commit.bullets)
        assert "icon.png" in bullets_text
        assert "poetry.lock" in bullets_text

    def test_bullets_describe_empty_files(self):
        """Commit bullets list empty new files."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("src/pkg/__init__.py", is_new_file=True),
            _make_file_diff("src/pkg/.gitkeep", is_new_file=True),
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        commit = build_residual_commit(file_diffs, plan, inventory)
        assert commit is not None
        bullets_text = " ".join(commit.bullets)
        assert "__init__.py" in bullets_text

    def test_title_truncated_to_72_char_header(self):
        """Title is truncated so type: title ≤ 72 chars."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        # Create many residual files to produce a long title
        residuals = [
            _make_file_diff(f"file_{i}.bin", is_binary=True)
            for i in range(20)
        ]
        file_diffs = [_make_file_diff("src/main.py", hunks=[h1])] + residuals
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        commit = build_residual_commit(file_diffs, plan, inventory)
        assert commit is not None
        # "chore: " = 7 chars → title ≤ 65
        assert len(commit.title) <= 65

    def test_mixed_residual_types_title(self):
        """Title mentions all residual types present."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("image.png", is_binary=True),
            _make_file_diff("src/pkg/__init__.py", is_new_file=True),
            _make_file_diff("old.txt", is_deleted_file=True),
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        commit = build_residual_commit(file_diffs, plan, inventory)
        assert commit is not None
        title_lower = commit.title.lower()
        assert "binary" in title_lower
        assert "empty" in title_lower
        assert "delet" in title_lower


# ── append_residual_to_plan ──


class TestAppendResidualToPlan:
    """Tests for append_residual_to_plan."""

    def test_appends_commit_to_plan(self):
        """Plan gains one more commit."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("image.png", is_binary=True),
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        residual = append_residual_to_plan(plan, file_diffs, inventory)
        assert len(plan.commits) == 2
        assert plan.commits[-1].id == "C2"
        assert plan.commits[-1].type == "chore"
        assert len(residual) == 1
        assert residual[0].file_path == "image.png"

    def test_no_change_when_no_residuals(self):
        """Plan unchanged when all files are covered."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [_make_file_diff("src/main.py", hunks=[h1])]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        residual = append_residual_to_plan(plan, file_diffs, inventory)
        assert len(plan.commits) == 1  # unchanged
        assert residual == []

    def test_returns_residual_file_diffs(self):
        """Returns the list of residual FileDiff objects."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("image.png", is_binary=True),
            _make_file_diff("src/__init__.py", is_new_file=True),
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        residual = append_residual_to_plan(plan, file_diffs, inventory)
        assert len(residual) == 2
        paths = {fd.file_path for fd in residual}
        assert paths == {"image.png", "src/__init__.py"}

    def test_can_exceed_max_commits(self):
        """Residual commit can be max_commits + 1."""
        h1 = _make_hunk("H1_abc", "src/main.py")
        file_diffs = [
            _make_file_diff("src/main.py", hunks=[h1]),
            _make_file_diff("data.bin", is_binary=True),
        ]
        inventory = {"H1_abc": h1}
        plan = _make_plan([
            PlannedCommit(id="C1", title="feat", hunks=["H1_abc"]),
        ])

        residual = append_residual_to_plan(plan, file_diffs, inventory, max_commits=1)
        assert len(plan.commits) == 2  # max_commits=1 but residual exceeds
        assert plan.commits[-1].id == "C2"


# ── execute_residual_commit ──


class TestExecuteResidualCommit:
    """Tests for execute_residual_commit (mocked git operations)."""

    def test_stages_binary_files_via_git_add(self, tmp_path):
        """Verifies git add is called for binary files."""
        from hunknote.compose.executor import execute_residual_commit

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / ".tmp").mkdir()

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo_dir, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo_dir, capture_output=True,
        )
        # Create initial commit
        (repo_dir / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo_dir, capture_output=True,
        )

        # Create a binary file to stage
        (repo_dir / "data.bin").write_bytes(b"\x00\x01\x02\x03")

        commit = PlannedCommit(
            id="C2",
            type="chore",
            title="Include binary assets",
            hunks=[],
        )
        residual_files = [
            _make_file_diff("data.bin", is_binary=True),
        ]

        execute_residual_commit(
            repo_dir, commit, residual_files,
            "chore: Include binary assets", 12345,
        )

        # Verify commit was created
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=repo_dir, capture_output=True, text=True,
        )
        assert "Include binary assets" in result.stdout

    def test_handles_empty_new_files(self, tmp_path):
        """Empty __init__.py files are staged and committed."""
        from hunknote.compose.executor import execute_residual_commit

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / ".tmp").mkdir()

        subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo_dir, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo_dir, capture_output=True,
        )
        (repo_dir / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo_dir, capture_output=True,
        )

        # Create empty __init__.py
        pkg_dir = repo_dir / "src" / "pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        commit = PlannedCommit(
            id="C2",
            type="chore",
            title="Add empty package files",
            hunks=[],
        )
        residual_files = [
            _make_file_diff("src/pkg/__init__.py", is_new_file=True),
        ]

        execute_residual_commit(
            repo_dir, commit, residual_files,
            "chore: Add empty package files", 12345,
        )

        # Verify commit was created with the file
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=repo_dir, capture_output=True, text=True,
        )
        assert "Add empty package files" in result.stdout

        # Verify the file is tracked
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_dir, capture_output=True, text=True,
        )
        assert "src/pkg/__init__.py" in result.stdout

    def test_skips_when_nothing_to_stage(self, tmp_path):
        """No error when residual files don't produce any staged changes."""
        from hunknote.compose.executor import execute_residual_commit

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / ".tmp").mkdir()

        subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo_dir, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo_dir, capture_output=True,
        )
        (repo_dir / "README.md").write_text("# Test")
        subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo_dir, capture_output=True,
        )

        commit = PlannedCommit(
            id="C2", type="chore", title="Nothing here", hunks=[],
        )
        # Reference a file that doesn't exist
        residual_files = [
            _make_file_diff("nonexistent.bin", is_binary=True),
        ]

        # Should not raise — gracefully skips
        execute_residual_commit(
            repo_dir, commit, residual_files,
            "chore: Nothing here", 12345,
        )

        # Verify no new commit (still just the init commit)
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=repo_dir, capture_output=True, text=True,
        )
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 1  # Only init commit

    def test_empty_residual_files_list_is_noop(self):
        """Calling with empty list does nothing."""
        from hunknote.compose.executor import execute_residual_commit

        commit = PlannedCommit(
            id="C2", type="chore", title="Nothing", hunks=[],
        )
        # Should not raise
        execute_residual_commit(
            Path("/tmp/fake"), commit, [],
            "chore: Nothing", 12345,
        )

