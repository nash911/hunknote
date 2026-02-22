"""Tests for hunknote.git_ctx module."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hunknote.git_ctx import (
    DEFAULT_DIFF_EXCLUDE_PATTERNS,
    GitError,
    NoStagedChangesError,
    _run_git_command,
    _should_exclude_file,
    build_context_bundle,
    get_branch,
    get_last_commits,
    get_repo_root,
    get_staged_diff,
    get_staged_status,
    get_status,
    is_merge_in_progress,
    get_merge_head,
    has_unresolved_conflicts,
    get_conflicted_files,
    get_merge_state,
    get_merge_source_branch,
)


class TestRunGitCommand:
    """Tests for _run_git_command function."""

    def test_successful_command(self, mocker):
        """Test successful git command execution."""
        mock_result = MagicMock()
        mock_result.stdout = "output\n"
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        result = _run_git_command(["status"])
        assert result == "output"

    def test_failed_command_raises_error(self, mocker):
        """Test that failed command raises GitError."""
        mocker.patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "git", stderr="error")
        )

        with pytest.raises(GitError) as exc_info:
            _run_git_command(["invalid"])

        assert "Git command failed" in str(exc_info.value)

    def test_git_not_found_raises_error(self, mocker):
        """Test that missing git raises GitError."""
        mocker.patch("subprocess.run", side_effect=FileNotFoundError())

        with pytest.raises(GitError) as exc_info:
            _run_git_command(["status"])

        assert "not installed" in str(exc_info.value)


class TestGetRepoRoot:
    """Tests for get_repo_root function."""

    def test_returns_path(self, mocker):
        """Test that repo root path is returned."""
        mock_result = MagicMock()
        mock_result.stdout = "/path/to/repo\n"
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        result = get_repo_root()
        assert result == Path("/path/to/repo")

    def test_raises_error_if_not_repo(self, mocker):
        """Test error if not in a git repository."""
        mocker.patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(128, "git", stderr="not a git repo")
        )

        with pytest.raises(GitError) as exc_info:
            get_repo_root()

        assert "Not in a git repository" in str(exc_info.value)


class TestGetBranch:
    """Tests for get_branch function."""

    def test_returns_branch_name(self, mocker):
        """Test that branch name is returned."""
        mock_result = MagicMock()
        mock_result.stdout = "main\n"
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        result = get_branch()
        assert result == "main"

    def test_detached_head(self, mocker):
        """Test detached HEAD state."""
        mock_result = MagicMock()
        mock_result.stdout = "\n"
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        result = get_branch()
        assert "detached" in result.lower()


class TestGetStatus:
    """Tests for get_status function."""

    def test_returns_status(self, mocker):
        """Test that status output is returned."""
        mock_result = MagicMock()
        mock_result.stdout = "## main\nA  file.py\n"
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        result = get_status()
        assert "## main" in result
        assert "A  file.py" in result


class TestGetStagedStatus:
    """Tests for get_staged_status function."""

    def test_filters_unstaged_files(self, mocker):
        """Test that unstaged files are filtered out."""
        mock_result = MagicMock()
        mock_result.stdout = "## main\nA  staged.py\n M unstaged.py\n?? untracked.py\n"
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        result = get_staged_status()
        assert "staged.py" in result
        assert "unstaged.py" not in result
        assert "untracked.py" not in result

    def test_keeps_branch_line(self, mocker):
        """Test that branch line is kept."""
        mock_result = MagicMock()
        mock_result.stdout = "## main...origin/main\nA  file.py\n"
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        result = get_staged_status()
        assert "## main" in result

    def test_keeps_staged_modifications(self, mocker):
        """Test that staged modifications are kept."""
        mock_result = MagicMock()
        mock_result.stdout = "## main\nM  modified.py\nD  deleted.py\nA  added.py\n"
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        result = get_staged_status()
        assert "M  modified.py" in result
        assert "D  deleted.py" in result
        assert "A  added.py" in result


class TestGetLastCommits:
    """Tests for get_last_commits function."""

    def test_returns_commit_list(self, mocker):
        """Test that commit list is returned."""
        mock_result = MagicMock()
        mock_result.stdout = "Commit 1\nCommit 2\nCommit 3\n"
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        result = get_last_commits(n=3)
        assert len(result) == 3
        assert result[0] == "Commit 1"

    def test_empty_repo_returns_empty(self, mocker):
        """Test that empty repo returns empty list."""
        mocker.patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(128, "git", stderr="no commits")
        )

        result = get_last_commits()
        assert result == []

    def test_respects_n_parameter(self, mocker):
        """Test that n parameter is passed to git."""
        mock_result = MagicMock()
        mock_result.stdout = "Commit 1\n"
        mock_result.returncode = 0

        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        get_last_commits(n=10)

        # Check that -n10 was in the command
        call_args = mock_run.call_args[0][0]
        assert "-n10" in call_args


class TestShouldExcludeFile:
    """Tests for _should_exclude_file function."""

    def test_exact_match(self):
        """Test exact filename match."""
        assert _should_exclude_file("poetry.lock", ["poetry.lock"]) is True

    def test_glob_pattern(self):
        """Test glob pattern matching."""
        assert _should_exclude_file("file.min.js", ["*.min.js"]) is True
        assert _should_exclude_file("file.js", ["*.min.js"]) is False

    def test_directory_pattern(self):
        """Test directory glob pattern."""
        assert _should_exclude_file(".idea/settings.xml", [".idea/*"]) is True

    def test_basename_match(self):
        """Test matching against basename."""
        assert _should_exclude_file("path/to/poetry.lock", ["poetry.lock"]) is True

    def test_no_match(self):
        """Test no match returns False."""
        assert _should_exclude_file("regular.py", ["*.lock"]) is False

    def test_multiple_patterns(self):
        """Test multiple patterns."""
        patterns = ["*.lock", "*.log", "*.tmp"]
        assert _should_exclude_file("file.lock", patterns) is True
        assert _should_exclude_file("file.log", patterns) is True
        assert _should_exclude_file("file.py", patterns) is False


class TestDefaultDiffExcludePatterns:
    """Tests for DEFAULT_DIFF_EXCLUDE_PATTERNS constant."""

    def test_contains_common_lock_files(self):
        """Test that common lock files are in defaults."""
        assert "poetry.lock" in DEFAULT_DIFF_EXCLUDE_PATTERNS
        assert "package-lock.json" in DEFAULT_DIFF_EXCLUDE_PATTERNS
        assert "yarn.lock" in DEFAULT_DIFF_EXCLUDE_PATTERNS


class TestGetStagedDiff:
    """Tests for get_staged_diff function."""

    def test_raises_if_no_staged_changes(self, mocker, temp_dir):
        """Test error when no staged changes."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)
        mocker.patch("hunknote.git_ctx.get_repo_root", return_value=temp_dir)

        with pytest.raises(NoStagedChangesError):
            get_staged_diff()

    def test_truncates_long_diff(self, mocker, temp_dir):
        """Test that long diff is truncated."""
        long_diff = "a" * 100000

        # Mock _get_staged_files_list
        mocker.patch(
            "hunknote.git.diff._get_staged_files_list",
            return_value=["file.py"]
        )
        mocker.patch("hunknote.git.diff.get_repo_root", return_value=temp_dir)
        mocker.patch(
            "hunknote.git.diff.get_ignore_patterns",
            return_value=[]
        )

        mock_result = MagicMock()
        mock_result.stdout = long_diff
        mock_result.returncode = 0
        mocker.patch("subprocess.run", return_value=mock_result)

        result = get_staged_diff(max_chars=1000)
        assert len(result) <= 1020  # 1000 + truncation message
        assert result.endswith("...[truncated]\n")

    def test_returns_message_if_only_ignored_files(self, mocker, temp_dir):
        """Test message when only ignored files are staged."""
        mocker.patch(
            "hunknote.git.diff._get_staged_files_list",
            return_value=["poetry.lock"]
        )
        mocker.patch("hunknote.git.diff.get_repo_root", return_value=temp_dir)
        mocker.patch(
            "hunknote.git.diff.get_ignore_patterns",
            return_value=["poetry.lock"]
        )

        result = get_staged_diff()
        assert "ignored files" in result.lower()


class TestBuildContextBundle:
    """Tests for build_context_bundle function."""

    def test_contains_all_sections(self, mocker, temp_dir):
        """Test that bundle contains all required sections."""
        mocker.patch("hunknote.git.context.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.git.context.get_branch", return_value="main")
        mocker.patch("hunknote.git.context.get_staged_status", return_value="## main\nA  file.py")
        mocker.patch("hunknote.git.context.get_last_commits", return_value=["Commit 1", "Commit 2"])
        mocker.patch("hunknote.git.context.get_staged_diff", return_value="diff content")
        mocker.patch("hunknote.git.context.get_merge_state", return_value={
            "is_merge": False, "merge_head": None, "source_branch": None,
            "has_conflicts": False, "conflicted_files": [], "state": "normal",
        })

        bundle = build_context_bundle()

        assert "[BRANCH]" in bundle
        assert "[FILE_CHANGES]" in bundle
        assert "[LAST_5_COMMITS]" in bundle
        assert "[STAGED_DIFF]" in bundle

    def test_includes_branch(self, mocker, temp_dir):
        """Test that branch is included."""
        mocker.patch("hunknote.git.context.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.git.context.get_branch", return_value="feature/test")
        mocker.patch("hunknote.git.context.get_staged_status", return_value="## feature/test\nA  file.py")
        mocker.patch("hunknote.git.context.get_last_commits", return_value=[])
        mocker.patch("hunknote.git.context.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.git.context.get_merge_state", return_value={
            "is_merge": False, "merge_head": None, "source_branch": None,
            "has_conflicts": False, "conflicted_files": [], "state": "normal",
        })

        bundle = build_context_bundle()

        assert "feature/test" in bundle

    def test_includes_commits(self, mocker, temp_dir):
        """Test that commits are included."""
        mocker.patch("hunknote.git.context.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.git.context.get_branch", return_value="main")
        mocker.patch("hunknote.git.context.get_staged_status", return_value="## main\nM  file.py")
        mocker.patch("hunknote.git.context.get_last_commits", return_value=["Fix bug", "Add feature"])
        mocker.patch("hunknote.git.context.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.git.context.get_merge_state", return_value={
            "is_merge": False, "merge_head": None, "source_branch": None,
            "has_conflicts": False, "conflicted_files": [], "state": "normal",
        })

        bundle = build_context_bundle()

        assert "- Fix bug" in bundle
        assert "- Add feature" in bundle

    def test_no_commits_message(self, mocker, temp_dir):
        """Test message when no commits exist."""
        mocker.patch("hunknote.git.context.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.git.context.get_branch", return_value="main")
        mocker.patch("hunknote.git.context.get_staged_status", return_value="## main\nA  file.py")
        mocker.patch("hunknote.git.context.get_last_commits", return_value=[])
        mocker.patch("hunknote.git.context.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.git.context.get_merge_state", return_value={
            "is_merge": False, "merge_head": None, "source_branch": None,
            "has_conflicts": False, "conflicted_files": [], "state": "normal",
        })

        bundle = build_context_bundle()

        assert "no commits yet" in bundle

    def test_passes_max_chars(self, mocker, temp_dir):
        """Test that max_chars is passed to get_staged_diff."""
        mocker.patch("hunknote.git.context.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.git.context.get_branch", return_value="main")
        mocker.patch("hunknote.git.context.get_staged_status", return_value="## main\nA  file.py")
        mocker.patch("hunknote.git.context.get_last_commits", return_value=[])
        mock_diff = mocker.patch("hunknote.git.context.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.git.context.get_merge_state", return_value={
            "is_merge": False, "merge_head": None, "source_branch": None,
            "has_conflicts": False, "conflicted_files": [], "state": "normal",
        })

        build_context_bundle(max_chars=10000)

        mock_diff.assert_called_once_with(max_chars=10000)

    def test_file_changes_shows_new_files(self, mocker, temp_dir):
        """Test that new files are labeled correctly in FILE_CHANGES."""
        mocker.patch("hunknote.git.context.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.git.context.get_branch", return_value="main")
        mocker.patch("hunknote.git.context.get_staged_status", return_value="## main\nA  new_file.py")
        mocker.patch("hunknote.git.context.get_last_commits", return_value=[])
        mocker.patch("hunknote.git.context.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.git.context.get_merge_state", return_value={
            "is_merge": False, "merge_head": None, "source_branch": None,
            "has_conflicts": False, "conflicted_files": [], "state": "normal",
        })

        bundle = build_context_bundle()

        assert "New files" in bundle
        assert "+ new_file.py" in bundle

    def test_file_changes_shows_modified_files(self, mocker, temp_dir):
        """Test that modified files are labeled correctly in FILE_CHANGES."""
        mocker.patch("hunknote.git.context.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.git.context.get_branch", return_value="main")
        mocker.patch("hunknote.git.context.get_staged_status", return_value="## main\nM  existing.py")
        mocker.patch("hunknote.git.context.get_last_commits", return_value=[])
        mocker.patch("hunknote.git.context.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.git.context.get_merge_state", return_value={
            "is_merge": False, "merge_head": None, "source_branch": None,
            "has_conflicts": False, "conflicted_files": [], "state": "normal",
        })

        bundle = build_context_bundle()

        assert "Modified files" in bundle
        assert "~ existing.py" in bundle


class TestMergeStateDetection:
    """Tests for merge state detection functions."""

    def test_is_merge_in_progress_true(self, temp_dir):
        """Test detecting merge in progress when MERGE_HEAD exists."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        merge_head = git_dir / "MERGE_HEAD"
        merge_head.write_text("abc123def456\n")

        result = is_merge_in_progress(temp_dir)
        assert result is True

    def test_is_merge_in_progress_false(self, temp_dir):
        """Test no merge when MERGE_HEAD doesn't exist."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()

        result = is_merge_in_progress(temp_dir)
        assert result is False

    def test_get_merge_head_returns_hash(self, temp_dir):
        """Test getting merge head commit hash."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        merge_head = git_dir / "MERGE_HEAD"
        merge_head.write_text("abc123def456789\n")

        result = get_merge_head(temp_dir)
        assert result == "abc123def456789"

    def test_get_merge_head_returns_none_when_no_merge(self, temp_dir):
        """Test merge head is None when no merge in progress."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()

        result = get_merge_head(temp_dir)
        assert result is None

    def test_has_unresolved_conflicts_true(self, mocker):
        """Test detecting unresolved conflicts."""
        mocker.patch(
            "hunknote.git.merge._run_git_command",
            return_value="UU file1.py\nAA file2.py"
        )

        result = has_unresolved_conflicts()
        assert result is True

    def test_has_unresolved_conflicts_false(self, mocker):
        """Test no conflicts detected."""
        mocker.patch(
            "hunknote.git.merge._run_git_command",
            return_value="M  file1.py\nA  file2.py"
        )

        result = has_unresolved_conflicts()
        assert result is False

    def test_get_conflicted_files(self, mocker):
        """Test getting list of conflicted files."""
        mocker.patch(
            "hunknote.git.merge._run_git_command",
            return_value="UU file1.py\nAA file2.py\nM  file3.py"
        )

        result = get_conflicted_files()
        assert "file1.py" in result
        assert "file2.py" in result
        assert "file3.py" not in result

    def test_get_merge_source_branch_from_merge_msg(self, temp_dir):
        """Test getting source branch from MERGE_MSG."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        merge_msg = git_dir / "MERGE_MSG"
        merge_msg.write_text("Merge branch 'feature-auth' into main\n")

        result = get_merge_source_branch(temp_dir)
        assert result == "feature-auth"

    def test_get_merge_source_branch_without_quotes(self, temp_dir):
        """Test getting source branch from MERGE_MSG without quotes."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        merge_msg = git_dir / "MERGE_MSG"
        merge_msg.write_text("Merge branch feature-branch\n")

        result = get_merge_source_branch(temp_dir)
        assert result == "feature-branch"

    def test_get_merge_source_branch_none_when_no_merge(self, temp_dir):
        """Test source branch is None when no merge msg."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()

        result = get_merge_source_branch(temp_dir)
        assert result is None

    def test_get_merge_state_normal(self, temp_dir):
        """Test merge state when no merge in progress."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()

        result = get_merge_state(temp_dir)
        assert result["state"] == "normal"
        assert result["is_merge"] is False
        assert result["merge_head"] is None
        assert result["source_branch"] is None
        assert result["has_conflicts"] is False

    def test_get_merge_state_merge(self, temp_dir, mocker):
        """Test merge state during merge."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        merge_head = git_dir / "MERGE_HEAD"
        merge_head.write_text("abc123\n")
        # Create MERGE_MSG with branch name
        merge_msg = git_dir / "MERGE_MSG"
        merge_msg.write_text("Merge branch 'feature-branch'\n")

        mocker.patch(
            "hunknote.git.merge._run_git_command",
            return_value="M  file1.py"
        )

        result = get_merge_state(temp_dir)
        assert result["state"] == "merge"
        assert result["is_merge"] is True
        assert result["merge_head"] == "abc123"
        assert result["source_branch"] == "feature-branch"

    def test_get_merge_state_conflict(self, temp_dir, mocker):
        """Test merge state with conflicts."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        merge_head = git_dir / "MERGE_HEAD"
        merge_head.write_text("abc123\n")

        mocker.patch(
            "hunknote.git.merge._run_git_command",
            return_value="UU conflict.py"
        )

        result = get_merge_state(temp_dir)
        assert result["state"] == "merge-conflict"
        assert result["has_conflicts"] is True
        assert "conflict.py" in result["conflicted_files"]


class TestBuildContextBundleMergeState:
    """Tests for merge state in context bundle."""

    def test_bundle_includes_merge_state_section(self, mocker, temp_dir):
        """Test that context bundle includes MERGE_STATE section."""
        mocker.patch("hunknote.git.context.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.git.context.get_branch", return_value="main")
        mocker.patch("hunknote.git.context.get_staged_status", return_value="## main\nM  file.py")
        mocker.patch("hunknote.git.context.get_last_commits", return_value=[])
        mocker.patch("hunknote.git.context.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.git.context.get_merge_state", return_value={
            "is_merge": False,
            "merge_head": None,
            "source_branch": None,
            "has_conflicts": False,
            "conflicted_files": [],
            "state": "normal",
        })

        bundle = build_context_bundle()

        assert "[MERGE_STATE]" in bundle
        assert "No merge in progress" in bundle

    def test_bundle_shows_merge_in_progress(self, mocker, temp_dir):
        """Test that context bundle shows merge in progress."""
        mocker.patch("hunknote.git.context.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.git.context.get_branch", return_value="main")
        mocker.patch("hunknote.git.context.get_staged_status", return_value="## main\nM  file.py")
        mocker.patch("hunknote.git.context.get_last_commits", return_value=[])
        mocker.patch("hunknote.git.context.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.git.context.get_merge_state", return_value={
            "is_merge": True,
            "merge_head": "abc123def456",
            "source_branch": "feature-branch",
            "has_conflicts": False,
            "conflicted_files": [],
            "state": "merge",
        })

        bundle = build_context_bundle()

        assert "[MERGE_STATE]" in bundle
        assert "MERGE IN PROGRESS" in bundle
        assert "Merging branch: feature-branch" in bundle
        assert "abc123def456"[:12] in bundle

    def test_bundle_shows_merge_conflict(self, mocker, temp_dir):
        """Test that context bundle shows merge conflict."""
        mocker.patch("hunknote.git.context.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.git.context.get_branch", return_value="main")
        mocker.patch("hunknote.git.context.get_staged_status", return_value="## main\nM  file.py")
        mocker.patch("hunknote.git.context.get_last_commits", return_value=[])
        mocker.patch("hunknote.git.context.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.git.context.get_merge_state", return_value={
            "is_merge": True,
            "merge_head": "abc123def456",
            "source_branch": "bugfix-branch",
            "has_conflicts": True,
            "conflicted_files": ["conflict.py"],
            "state": "merge-conflict",
        })

        bundle = build_context_bundle()

        assert "[MERGE_STATE]" in bundle
        assert "MERGE CONFLICT" in bundle
        assert "Merging branch: bugfix-branch" in bundle
        assert "conflict.py" in bundle


# ============================================================================
# Additional Test Cases for Complete Coverage
# ============================================================================


class TestGetStagedFilesList:
    """Tests for _get_staged_files_list function."""

    def test_returns_list_of_files(self, mocker):
        """Test that staged files list is returned."""
        mock_result = MagicMock()
        mock_result.stdout = "file1.py\nfile2.js\nfile3.txt\n"
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        from hunknote.git_ctx import _get_staged_files_list
        result = _get_staged_files_list()

        assert result == ["file1.py", "file2.js", "file3.txt"]

    def test_returns_empty_list_when_no_staged(self, mocker):
        """Test empty list when no staged files."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        from hunknote.git_ctx import _get_staged_files_list
        result = _get_staged_files_list()

        assert result == []


class TestParseFileChanges:
    """Tests for _parse_file_changes function."""

    def test_parses_new_files(self):
        """Test parsing new files."""
        from hunknote.git_ctx import _parse_file_changes

        status = "## main\nA  new_file.py"
        result = _parse_file_changes(status)

        assert "New files" in result
        assert "+ new_file.py" in result

    def test_parses_modified_files(self):
        """Test parsing modified files."""
        from hunknote.git_ctx import _parse_file_changes

        status = "## main\nM  existing.py"
        result = _parse_file_changes(status)

        assert "Modified files" in result
        assert "~ existing.py" in result

    def test_parses_deleted_files(self):
        """Test parsing deleted files."""
        from hunknote.git_ctx import _parse_file_changes

        status = "## main\nD  removed.py"
        result = _parse_file_changes(status)

        assert "Deleted files" in result
        assert "- removed.py" in result

    def test_parses_renamed_files(self):
        """Test parsing renamed files."""
        from hunknote.git_ctx import _parse_file_changes

        status = "## main\nR  old.py -> new.py"
        result = _parse_file_changes(status)

        assert "Renamed files" in result
        assert "> old.py -> new.py" in result

    def test_parses_mixed_changes(self):
        """Test parsing mixed file changes."""
        from hunknote.git_ctx import _parse_file_changes

        status = "## main\nA  new.py\nM  modified.py\nD  deleted.py"
        result = _parse_file_changes(status)

        assert "New files" in result
        assert "Modified files" in result
        assert "Deleted files" in result

    def test_returns_no_files_for_empty_status(self):
        """Test empty status returns no files message."""
        from hunknote.git_ctx import _parse_file_changes

        status = "## main"
        result = _parse_file_changes(status)

        assert "(no files)" in result


class TestFormatMergeState:
    """Tests for _format_merge_state function."""

    def test_formats_normal_state(self):
        """Test formatting normal (no merge) state."""
        from hunknote.git_ctx import _format_merge_state

        state = {
            "is_merge": False,
            "merge_head": None,
            "source_branch": None,
            "has_conflicts": False,
            "conflicted_files": [],
            "state": "normal",
        }
        result = _format_merge_state(state)

        assert "No merge in progress" in result

    def test_formats_merge_state(self):
        """Test formatting merge in progress state."""
        from hunknote.git_ctx import _format_merge_state

        state = {
            "is_merge": True,
            "merge_head": "abc123def456",
            "source_branch": "feature-branch",
            "has_conflicts": False,
            "conflicted_files": [],
            "state": "merge",
        }
        result = _format_merge_state(state)

        assert "MERGE IN PROGRESS" in result
        assert "Merging branch: feature-branch" in result
        assert "abc123def456"[:12] in result

    def test_formats_merge_conflict_state(self):
        """Test formatting merge conflict state."""
        from hunknote.git_ctx import _format_merge_state

        state = {
            "is_merge": True,
            "merge_head": "abc123",
            "source_branch": "bugfix",
            "has_conflicts": True,
            "conflicted_files": ["conflict.py", "another.py"],
            "state": "merge-conflict",
        }
        result = _format_merge_state(state)

        assert "MERGE CONFLICT" in result
        assert "conflict.py" in result
        assert "another.py" in result


class TestNewModuleImports:
    """Tests for new module import paths."""

    def test_imports_from_exceptions_module(self):
        """Test importing from exceptions module."""
        from hunknote.git.exceptions import GitError, NoStagedChangesError
        assert GitError is not None
        assert NoStagedChangesError is not None
        assert issubclass(NoStagedChangesError, GitError)

    def test_imports_from_runner_module(self):
        """Test importing from runner module."""
        from hunknote.git.runner import _run_git_command, get_repo_root
        assert callable(_run_git_command)
        assert callable(get_repo_root)

    def test_imports_from_branch_module(self):
        """Test importing from branch module."""
        from hunknote.git.branch import get_branch, get_last_commits
        assert callable(get_branch)
        assert callable(get_last_commits)

    def test_imports_from_merge_module(self):
        """Test importing from merge module."""
        from hunknote.git.merge import (
            is_merge_in_progress,
            get_merge_head,
            get_merge_source_branch,
            has_unresolved_conflicts,
            get_conflicted_files,
            get_merge_state,
        )
        assert callable(is_merge_in_progress)
        assert callable(get_merge_head)
        assert callable(get_merge_source_branch)
        assert callable(has_unresolved_conflicts)
        assert callable(get_conflicted_files)
        assert callable(get_merge_state)

    def test_imports_from_status_module(self):
        """Test importing from status module."""
        from hunknote.git.status import (
            get_status,
            get_staged_status,
            _get_staged_files_list,
        )
        assert callable(get_status)
        assert callable(get_staged_status)
        assert callable(_get_staged_files_list)

    def test_imports_from_diff_module(self):
        """Test importing from diff module."""
        from hunknote.git.diff import (
            get_staged_diff,
            _should_exclude_file,
            DEFAULT_DIFF_EXCLUDE_PATTERNS,
        )
        assert callable(get_staged_diff)
        assert callable(_should_exclude_file)
        assert isinstance(DEFAULT_DIFF_EXCLUDE_PATTERNS, list)

    def test_imports_from_context_module(self):
        """Test importing from context module."""
        from hunknote.git.context import (
            build_context_bundle,
            _parse_file_changes,
            _format_merge_state,
        )
        assert callable(build_context_bundle)
        assert callable(_parse_file_changes)
        assert callable(_format_merge_state)

    def test_package_level_imports(self):
        """Test importing from package level."""
        from hunknote.git import (
            GitError,
            NoStagedChangesError,
            get_repo_root,
            get_branch,
            build_context_bundle,
        )
        assert GitError is not None
        assert NoStagedChangesError is not None
        assert callable(get_repo_root)
        assert callable(get_branch)
        assert callable(build_context_bundle)


class TestGitExceptions:
    """Tests for git exception classes."""

    def test_git_error_is_exception(self):
        """Test that GitError is an Exception."""
        from hunknote.git.exceptions import GitError
        error = GitError("test error")
        assert isinstance(error, Exception)
        assert str(error) == "test error"

    def test_no_staged_changes_error_is_git_error(self):
        """Test that NoStagedChangesError is a GitError."""
        from hunknote.git.exceptions import NoStagedChangesError, GitError
        error = NoStagedChangesError("no changes")
        assert isinstance(error, GitError)
        assert isinstance(error, Exception)

    def test_can_catch_no_staged_as_git_error(self):
        """Test that NoStagedChangesError can be caught as GitError."""
        from hunknote.git.exceptions import NoStagedChangesError, GitError
        try:
            raise NoStagedChangesError("test")
        except GitError as e:
            assert "test" in str(e)


class TestGetMergeSourceBranchEdgeCases:
    """Additional tests for get_merge_source_branch edge cases."""

    def test_handles_missing_git_dir(self, temp_dir):
        """Test handling when .git directory doesn't exist."""
        # No .git directory
        result = get_merge_source_branch(temp_dir)
        assert result is None

    def test_handles_empty_merge_msg(self, temp_dir):
        """Test handling empty MERGE_MSG file."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        merge_msg = git_dir / "MERGE_MSG"
        merge_msg.write_text("")

        result = get_merge_source_branch(temp_dir)
        assert result is None


class TestGetStagedDiffEdgeCases:
    """Additional tests for get_staged_diff edge cases."""

    def test_raises_when_no_files_staged(self, mocker):
        """Test that NoStagedChangesError is raised when no files staged."""
        mocker.patch(
            "hunknote.git.diff._get_staged_files_list",
            return_value=[]
        )

        with pytest.raises(NoStagedChangesError):
            get_staged_diff()

    def test_handles_repo_root_parameter(self, mocker, temp_dir):
        """Test that repo_root parameter is used correctly."""
        mocker.patch(
            "hunknote.git.diff._get_staged_files_list",
            return_value=["file.py"]
        )
        mock_ignore = mocker.patch(
            "hunknote.git.diff.get_ignore_patterns",
            return_value=[]
        )
        mock_result = MagicMock()
        mock_result.stdout = "diff content\n"
        mock_result.returncode = 0
        mocker.patch("subprocess.run", return_value=mock_result)

        get_staged_diff(repo_root=temp_dir)

        # Verify get_ignore_patterns was called with the provided repo_root
        mock_ignore.assert_called_once_with(temp_dir)


class TestGetBranchEdgeCases:
    """Additional tests for get_branch edge cases."""

    def test_detached_head_state(self, mocker):
        """Test handling detached HEAD state."""
        mock_result = MagicMock()
        mock_result.stdout = ""  # Empty output means detached HEAD
        mock_result.returncode = 0

        mocker.patch("subprocess.run", return_value=mock_result)

        result = get_branch()
        assert "detached" in result.lower()

