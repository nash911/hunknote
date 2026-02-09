"""Tests for aicommit.git_ctx module."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aicommit.git_ctx import (
    DEFAULT_DIFF_EXCLUDE_PATTERNS,
    GitError,
    NoStagedChangesError,
    _get_staged_files_list,
    _run_git_command,
    _should_exclude_file,
    build_context_bundle,
    get_branch,
    get_last_commits,
    get_repo_root,
    get_staged_diff,
    get_staged_status,
    get_status,
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
        mocker.patch("aicommit.git_ctx.get_repo_root", return_value=temp_dir)

        with pytest.raises(NoStagedChangesError):
            get_staged_diff()

    def test_truncates_long_diff(self, mocker, temp_dir):
        """Test that long diff is truncated."""
        long_diff = "a" * 100000

        # Mock _get_staged_files_list
        mocker.patch(
            "aicommit.git_ctx._get_staged_files_list",
            return_value=["file.py"]
        )
        mocker.patch("aicommit.git_ctx.get_repo_root", return_value=temp_dir)
        mocker.patch(
            "aicommit.git_ctx.get_ignore_patterns",
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
            "aicommit.git_ctx._get_staged_files_list",
            return_value=["poetry.lock"]
        )
        mocker.patch("aicommit.git_ctx.get_repo_root", return_value=temp_dir)
        mocker.patch(
            "aicommit.git_ctx.get_ignore_patterns",
            return_value=["poetry.lock"]
        )

        result = get_staged_diff()
        assert "ignored files" in result.lower()


class TestBuildContextBundle:
    """Tests for build_context_bundle function."""

    def test_contains_all_sections(self, mocker, temp_dir):
        """Test that bundle contains all required sections."""
        mocker.patch("aicommit.git_ctx.get_branch", return_value="main")
        mocker.patch("aicommit.git_ctx.get_staged_status", return_value="## main\nA  file.py")
        mocker.patch("aicommit.git_ctx.get_last_commits", return_value=["Commit 1", "Commit 2"])
        mocker.patch("aicommit.git_ctx.get_staged_diff", return_value="diff content")

        bundle = build_context_bundle()

        assert "[BRANCH]" in bundle
        assert "[FILE_CHANGES]" in bundle
        assert "[LAST_5_COMMITS]" in bundle
        assert "[STAGED_DIFF]" in bundle

    def test_includes_branch(self, mocker, temp_dir):
        """Test that branch is included."""
        mocker.patch("aicommit.git_ctx.get_branch", return_value="feature/test")
        mocker.patch("aicommit.git_ctx.get_staged_status", return_value="## feature/test\nA  file.py")
        mocker.patch("aicommit.git_ctx.get_last_commits", return_value=[])
        mocker.patch("aicommit.git_ctx.get_staged_diff", return_value="diff")

        bundle = build_context_bundle()

        assert "feature/test" in bundle

    def test_includes_commits(self, mocker, temp_dir):
        """Test that commits are included."""
        mocker.patch("aicommit.git_ctx.get_branch", return_value="main")
        mocker.patch("aicommit.git_ctx.get_staged_status", return_value="## main\nM  file.py")
        mocker.patch("aicommit.git_ctx.get_last_commits", return_value=["Fix bug", "Add feature"])
        mocker.patch("aicommit.git_ctx.get_staged_diff", return_value="diff")

        bundle = build_context_bundle()

        assert "- Fix bug" in bundle
        assert "- Add feature" in bundle

    def test_no_commits_message(self, mocker, temp_dir):
        """Test message when no commits exist."""
        mocker.patch("aicommit.git_ctx.get_branch", return_value="main")
        mocker.patch("aicommit.git_ctx.get_staged_status", return_value="## main\nA  file.py")
        mocker.patch("aicommit.git_ctx.get_last_commits", return_value=[])
        mocker.patch("aicommit.git_ctx.get_staged_diff", return_value="diff")

        bundle = build_context_bundle()

        assert "no commits yet" in bundle

    def test_passes_max_chars(self, mocker, temp_dir):
        """Test that max_chars is passed to get_staged_diff."""
        mocker.patch("aicommit.git_ctx.get_branch", return_value="main")
        mocker.patch("aicommit.git_ctx.get_staged_status", return_value="## main\nA  file.py")
        mocker.patch("aicommit.git_ctx.get_last_commits", return_value=[])
        mock_diff = mocker.patch("aicommit.git_ctx.get_staged_diff", return_value="diff")

        build_context_bundle(max_chars=10000)

        mock_diff.assert_called_once_with(max_chars=10000)

    def test_file_changes_shows_new_files(self, mocker, temp_dir):
        """Test that new files are labeled correctly in FILE_CHANGES."""
        mocker.patch("aicommit.git_ctx.get_branch", return_value="main")
        mocker.patch("aicommit.git_ctx.get_staged_status", return_value="## main\nA  new_file.py")
        mocker.patch("aicommit.git_ctx.get_last_commits", return_value=[])
        mocker.patch("aicommit.git_ctx.get_staged_diff", return_value="diff")

        bundle = build_context_bundle()

        assert "New files" in bundle
        assert "+ new_file.py" in bundle

    def test_file_changes_shows_modified_files(self, mocker, temp_dir):
        """Test that modified files are labeled correctly in FILE_CHANGES."""
        mocker.patch("aicommit.git_ctx.get_branch", return_value="main")
        mocker.patch("aicommit.git_ctx.get_staged_status", return_value="## main\nM  existing.py")
        mocker.patch("aicommit.git_ctx.get_last_commits", return_value=[])
        mocker.patch("aicommit.git_ctx.get_staged_diff", return_value="diff")

        bundle = build_context_bundle()

        assert "Modified files" in bundle
        assert "~ existing.py" in bundle

