"""Tests for hunknote.formatters module."""

import pytest
from pydantic import ValidationError

from hunknote.formatters import CommitMessageJSON, render_commit_message, sanitize_title


class TestCommitMessageJSON:
    """Tests for CommitMessageJSON Pydantic model."""

    def test_valid_commit_message(self):
        """Test creating a valid commit message."""
        msg = CommitMessageJSON(
            title="Add new feature",
            body_bullets=["Add user authentication", "Update database schema"],
        )
        assert msg.title == "Add new feature"
        assert len(msg.body_bullets) == 2

    def test_title_stripped(self):
        """Test that title whitespace is stripped."""
        msg = CommitMessageJSON(
            title="  Add feature  ",
            body_bullets=["Change something"],
        )
        assert msg.title == "Add feature"

    def test_empty_title_raises_error(self):
        """Test that empty title raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            CommitMessageJSON(title="", body_bullets=["Change"])
        assert "Title cannot be empty" in str(exc_info.value)

    def test_whitespace_only_title_raises_error(self):
        """Test that whitespace-only title raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            CommitMessageJSON(title="   ", body_bullets=["Change"])
        assert "Title cannot be empty" in str(exc_info.value)

    def test_empty_body_bullets_raises_error(self):
        """Test that empty body_bullets raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            CommitMessageJSON(title="Add feature", body_bullets=[])
        assert "body_bullets cannot be empty" in str(exc_info.value)

    def test_body_bullets_with_only_empty_strings_raises_error(self):
        """Test that body_bullets with only empty strings raises error."""
        with pytest.raises(ValidationError) as exc_info:
            CommitMessageJSON(title="Add feature", body_bullets=["", "   "])
        assert "at least one non-empty item" in str(exc_info.value)

    def test_body_bullets_filters_empty_strings(self):
        """Test that empty strings are filtered from body_bullets."""
        msg = CommitMessageJSON(
            title="Add feature",
            body_bullets=["Valid bullet", "", "  ", "Another valid"],
        )
        assert len(msg.body_bullets) == 2
        assert "Valid bullet" in msg.body_bullets
        assert "Another valid" in msg.body_bullets

    def test_body_bullets_strips_whitespace(self):
        """Test that body_bullets items are stripped."""
        msg = CommitMessageJSON(
            title="Add feature",
            body_bullets=["  First bullet  ", "  Second bullet  "],
        )
        assert msg.body_bullets[0] == "First bullet"
        assert msg.body_bullets[1] == "Second bullet"


class TestSanitizeTitle:
    """Tests for sanitize_title function."""

    def test_normal_title(self):
        """Test that normal title passes through."""
        assert sanitize_title("Add new feature") == "Add new feature"

    def test_title_with_whitespace(self):
        """Test that whitespace is stripped."""
        assert sanitize_title("  Add feature  ") == "Add feature"

    def test_multiline_title_takes_first_line(self):
        """Test that only first line is kept."""
        title = "First line\nSecond line\nThird line"
        assert sanitize_title(title) == "First line"

    def test_long_title_truncated(self):
        """Test that long titles are truncated with ellipsis."""
        long_title = "A" * 100
        result = sanitize_title(long_title)
        assert len(result) == 72
        assert result.endswith("...")

    def test_title_at_max_length_not_truncated(self):
        """Test that title exactly at max length is not truncated."""
        title = "A" * 72
        result = sanitize_title(title)
        assert result == title
        assert len(result) == 72

    def test_custom_max_length(self):
        """Test custom max_length parameter."""
        title = "A" * 50
        result = sanitize_title(title, max_length=30)
        assert len(result) == 30
        assert result.endswith("...")

    def test_truncation_preserves_word_boundary_ellipsis(self):
        """Test that truncation adds ellipsis correctly."""
        title = "This is a very long title that should be truncated"
        result = sanitize_title(title, max_length=30)
        assert len(result) == 30
        assert result == "This is a very long title t..."


class TestRenderCommitMessage:
    """Tests for render_commit_message function."""

    def test_basic_render(self):
        """Test basic commit message rendering."""
        msg = CommitMessageJSON(
            title="Add new feature",
            body_bullets=["First change", "Second change"],
        )
        result = render_commit_message(msg)
        expected = "Add new feature\n\n- First change\n- Second change"
        assert result == expected

    def test_render_with_long_title(self):
        """Test rendering with long title gets truncated."""
        msg = CommitMessageJSON(
            title="A" * 100,
            body_bullets=["Change"],
        )
        result = render_commit_message(msg)
        lines = result.split("\n")
        assert len(lines[0]) == 72
        assert lines[0].endswith("...")

    def test_render_strips_bullet_whitespace(self):
        """Test that bullet whitespace is stripped in output."""
        msg = CommitMessageJSON(
            title="Add feature",
            body_bullets=["  First  ", "  Second  "],
        )
        result = render_commit_message(msg)
        assert "- First\n- Second" in result

    def test_render_format(self):
        """Test the exact format of rendered message."""
        msg = CommitMessageJSON(
            title="Fix bug",
            body_bullets=["Fix null pointer", "Add validation"],
        )
        result = render_commit_message(msg)

        # Check structure
        parts = result.split("\n\n")
        assert len(parts) == 2

        # Check title
        assert parts[0] == "Fix bug"

        # Check bullets
        bullets = parts[1].split("\n")
        assert bullets[0] == "- Fix null pointer"
        assert bullets[1] == "- Add validation"

    def test_render_single_bullet(self):
        """Test rendering with a single bullet point."""
        msg = CommitMessageJSON(
            title="Quick fix",
            body_bullets=["Fix typo"],
        )
        result = render_commit_message(msg)
        assert result == "Quick fix\n\n- Fix typo"

    def test_render_many_bullets(self):
        """Test rendering with many bullet points."""
        msg = CommitMessageJSON(
            title="Major refactor",
            body_bullets=[f"Change {i}" for i in range(7)],
        )
        result = render_commit_message(msg)
        # 7 bullets means 7 lines starting with "- "
        assert result.count("- ") == 7
        assert "- Change 0" in result
        assert "- Change 6" in result
