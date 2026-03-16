"""Tests for hunknote.compose.agent.tools — Agent tool definitions and execution."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hunknote.compose.agent.models import HunkSummary
from hunknote.compose.agent.tools import (
    TOOL_DEFINITIONS,
    TOOL_OUTPUT_MAX_CHARS,
    ToolResult,
    execute_tool,
    format_tool_definitions,
)
from hunknote.compose.models import HunkRef


@pytest.fixture
def inventory():
    return {
        "H1_abc123": HunkRef(
            id="H1_abc123", file_path="foo.py", header="@@ -1,3 +1,5 @@",
            old_start=1, old_len=3, new_start=1, new_len=5,
            lines=["+def hello():", "+    pass"],
        ),
        "H2_def456": HunkRef(
            id="H2_def456", file_path="bar.py", header="@@ -1,2 +1,4 @@",
            old_start=1, old_len=2, new_start=1, new_len=4,
            lines=["+from foo import hello", "+hello()"],
        ),
    }


@pytest.fixture
def summaries():
    return {
        "H1_abc123": HunkSummary(
            hunk_id="H1_abc123", file_path="foo.py",
            intent="Add hello function", category="feature",
        ),
    }


class TestToolDefinitions:
    """Tests for tool definition structure."""

    def test_all_tools_have_required_fields(self):
        """Each tool definition has name, description, and parameters."""
        for tool in TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool

    def test_expected_tools_exist(self):
        """All expected tools are defined."""
        names = {t["name"] for t in TOOL_DEFINITIONS}
        expected = {"ripgrep", "read_file", "read_staged_file", "get_hunk", "list_hunks"}
        assert expected == names


class TestFormatToolDefinitions:
    """Tests for tool definition formatting."""

    def test_formats_all_tools(self):
        """Format includes all tool names."""
        output = format_tool_definitions()
        for tool in TOOL_DEFINITIONS:
            assert tool["name"] in output

    def test_filters_by_name(self):
        """Only specified tools are included."""
        output = format_tool_definitions(["ripgrep", "get_hunk"])
        assert "ripgrep" in output
        assert "get_hunk" in output
        assert "list_hunks" not in output


class TestExecuteGetHunk:
    """Tests for the get_hunk tool."""

    def test_existing_hunk(self, inventory, summaries):
        """Returns hunk content for valid ID."""
        result = execute_tool(
            "get_hunk", {"hunk_id": "H1_abc123"},
            Path("."), inventory, summaries,
        )
        assert result.success is True
        assert "hello" in result.output

    def test_nonexistent_hunk(self, inventory, summaries):
        """Returns error for invalid ID."""
        result = execute_tool(
            "get_hunk", {"hunk_id": "H99_fake"},
            Path("."), inventory, summaries,
        )
        assert result.success is False
        assert "not found" in result.output.lower()

    def test_missing_hunk_id(self, inventory, summaries):
        """Missing hunk_id raises TypeError (unpacked as **args)."""
        with pytest.raises(TypeError):
            execute_tool(
                "get_hunk", {},
                Path("."), inventory, summaries,
            )


class TestExecuteListHunks:
    """Tests for the list_hunks tool."""

    def test_lists_all_hunks(self, inventory, summaries):
        """Returns all hunks with their file paths."""
        result = execute_tool(
            "list_hunks", {},
            Path("."), inventory, summaries,
        )
        assert result.success is True
        assert "H1_abc123" in result.output
        assert "H2_def456" in result.output
        assert "foo.py" in result.output

    def test_output_contains_file_paths(self, inventory, summaries):
        """Output includes file paths for each hunk."""
        result = execute_tool(
            "list_hunks", {},
            Path("."), inventory, summaries,
        )
        assert "bar.py" in result.output


class TestExecuteRipgrep:
    """Tests for the ripgrep tool."""

    @patch("subprocess.run")
    def test_successful_search(self, mock_run, inventory, summaries):
        """Ripgrep returns search results."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="foo.py:1:def hello():\n", stderr="",
        )
        result = execute_tool(
            "ripgrep", {"pattern": "hello"},
            Path("/repo"), inventory, summaries,
        )
        assert result.success is True
        assert "hello" in result.output

    @patch("subprocess.run")
    def test_no_matches(self, mock_run, inventory, summaries):
        """Ripgrep returns no matches gracefully."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        result = execute_tool(
            "ripgrep", {"pattern": "nonexistent"},
            Path("/repo"), inventory, summaries,
        )
        # rg exit code 1 = no matches, still success
        assert "no matches" in result.output.lower() or result.output == ""

    @patch("subprocess.run")
    def test_output_truncation(self, mock_run, inventory, summaries):
        """Large outputs are truncated for LLM but full in full_output."""
        large_output = "x" * (TOOL_OUTPUT_MAX_CHARS + 1000)
        mock_run.return_value = MagicMock(
            returncode=0, stdout=large_output, stderr="",
        )
        result = execute_tool(
            "ripgrep", {"pattern": "x"},
            Path("/repo"), inventory, summaries,
        )
        assert len(result.output) <= TOOL_OUTPUT_MAX_CHARS + 100  # some margin for truncation message
        assert result.truncated is True
        assert len(result.full_output) > TOOL_OUTPUT_MAX_CHARS

    @patch("subprocess.run")
    def test_missing_pattern(self, mock_run, inventory, summaries):
        """Missing pattern raises TypeError (unpacked as **args)."""
        with pytest.raises(TypeError):
            execute_tool(
                "ripgrep", {},
                Path("/repo"), inventory, summaries,
            )


class TestExecuteReadFile:
    """Tests for the read_file tool."""

    @patch("subprocess.run")
    def test_reads_head_version(self, mock_run, inventory, summaries):
        """read_file uses git show HEAD:<path>."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="file content here", stderr="",
        )
        result = execute_tool(
            "read_file", {"file_path": "foo.py"},
            Path("/repo"), inventory, summaries,
        )
        assert result.success is True
        assert "file content" in result.output
        # Verify git show HEAD: was called
        call_args = mock_run.call_args[0][0]
        assert "git" in call_args
        assert "show" in call_args


class TestExecuteReadStagedFile:
    """Tests for the read_staged_file tool."""

    @patch("subprocess.run")
    def test_reads_staged_version(self, mock_run, inventory, summaries):
        """read_staged_file uses git show :<path>."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="staged content", stderr="",
        )
        result = execute_tool(
            "read_staged_file", {"file_path": "foo.py"},
            Path("/repo"), inventory, summaries,
        )
        assert result.success is True
        assert "staged content" in result.output


class TestUnknownTool:
    """Tests for unknown tool handling."""

    def test_unknown_tool_returns_error(self, inventory, summaries):
        """Unknown tool name returns failure."""
        result = execute_tool(
            "nonexistent_tool", {},
            Path("."), inventory, summaries,
        )
        assert result.success is False
        assert "unknown" in result.output.lower()
