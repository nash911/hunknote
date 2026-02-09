"""Tests for aicommit.cache module."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aicommit.cache import (
    CacheMetadata,
    compute_context_hash,
    extract_staged_files,
    get_cache_dir,
    get_diff_preview,
    get_hash_file,
    get_message_file,
    get_metadata_file,
    invalidate_cache,
    is_cache_valid,
    load_cache_metadata,
    load_cached_message,
    save_cache,
    update_message_cache,
)


class TestCacheMetadata:
    """Tests for CacheMetadata model."""

    def test_create_metadata(self):
        """Test creating cache metadata."""
        metadata = CacheMetadata(
            context_hash="abc123",
            generated_at="2024-01-01T00:00:00+00:00",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file1.py", "file2.py"],
            original_message="Test message",
            diff_preview="diff content",
        )
        assert metadata.context_hash == "abc123"
        assert metadata.model == "gpt-4"
        assert len(metadata.staged_files) == 2


class TestGetCacheDir:
    """Tests for get_cache_dir function."""

    def test_creates_cache_dir(self, temp_dir):
        """Test that cache directory is created."""
        cache_dir = get_cache_dir(temp_dir)
        assert cache_dir.exists()
        assert cache_dir.name == ".aicommit"

    def test_returns_existing_dir(self, temp_dir):
        """Test that existing directory is returned."""
        aicommit_dir = temp_dir / ".aicommit"
        aicommit_dir.mkdir()

        cache_dir = get_cache_dir(temp_dir)
        assert cache_dir == aicommit_dir


class TestCacheFilePaths:
    """Tests for cache file path functions."""

    def test_get_message_file(self, temp_dir):
        """Test message file path."""
        path = get_message_file(temp_dir)
        assert path.name == "aicommit_message.txt"
        assert path.parent.name == ".aicommit"

    def test_get_hash_file(self, temp_dir):
        """Test hash file path."""
        path = get_hash_file(temp_dir)
        assert path.name == "aicommit_context_hash.txt"

    def test_get_metadata_file(self, temp_dir):
        """Test metadata file path."""
        path = get_metadata_file(temp_dir)
        assert path.name == "aicommit_metadata.json"


class TestComputeContextHash:
    """Tests for compute_context_hash function."""

    def test_computes_hash(self):
        """Test that hash is computed."""
        context = "test context"
        hash_result = compute_context_hash(context)
        assert isinstance(hash_result, str)
        assert len(hash_result) == 64  # SHA256 hex digest

    def test_same_context_same_hash(self):
        """Test that same context produces same hash."""
        context = "test context"
        hash1 = compute_context_hash(context)
        hash2 = compute_context_hash(context)
        assert hash1 == hash2

    def test_different_context_different_hash(self):
        """Test that different context produces different hash."""
        hash1 = compute_context_hash("context 1")
        hash2 = compute_context_hash("context 2")
        assert hash1 != hash2


class TestIsCacheValid:
    """Tests for is_cache_valid function."""

    def test_no_cache_files_invalid(self, temp_dir):
        """Test that missing cache files means invalid."""
        assert is_cache_valid(temp_dir, "abc123") is False

    def test_matching_hash_valid(self, temp_dir):
        """Test that matching hash is valid."""
        cache_dir = temp_dir / ".aicommit"
        cache_dir.mkdir()

        hash_file = cache_dir / "aicommit_context_hash.txt"
        message_file = cache_dir / "aicommit_message.txt"

        hash_file.write_text("abc123")
        message_file.write_text("test message")

        assert is_cache_valid(temp_dir, "abc123") is True

    def test_different_hash_invalid(self, temp_dir):
        """Test that different hash is invalid."""
        cache_dir = temp_dir / ".aicommit"
        cache_dir.mkdir()

        hash_file = cache_dir / "aicommit_context_hash.txt"
        message_file = cache_dir / "aicommit_message.txt"

        hash_file.write_text("abc123")
        message_file.write_text("test message")

        assert is_cache_valid(temp_dir, "xyz789") is False

    def test_missing_message_file_invalid(self, temp_dir):
        """Test that missing message file means invalid."""
        cache_dir = temp_dir / ".aicommit"
        cache_dir.mkdir()

        hash_file = cache_dir / "aicommit_context_hash.txt"
        hash_file.write_text("abc123")

        assert is_cache_valid(temp_dir, "abc123") is False


class TestSaveCache:
    """Tests for save_cache function."""

    def test_saves_all_files(self, temp_dir):
        """Test that all cache files are saved."""
        save_cache(
            repo_root=temp_dir,
            context_hash="abc123",
            message="Test commit message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file1.py"],
            diff_preview="diff preview",
        )

        cache_dir = temp_dir / ".aicommit"
        assert (cache_dir / "aicommit_context_hash.txt").exists()
        assert (cache_dir / "aicommit_message.txt").exists()
        assert (cache_dir / "aicommit_metadata.json").exists()

    def test_hash_content(self, temp_dir):
        """Test that hash is saved correctly."""
        save_cache(
            repo_root=temp_dir,
            context_hash="test_hash_123",
            message="message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=[],
            diff_preview="",
        )

        hash_content = get_hash_file(temp_dir).read_text()
        assert hash_content == "test_hash_123"

    def test_message_content(self, temp_dir):
        """Test that message is saved correctly."""
        save_cache(
            repo_root=temp_dir,
            context_hash="hash",
            message="My commit message\n\n- Bullet 1",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=[],
            diff_preview="",
        )

        message_content = get_message_file(temp_dir).read_text()
        assert message_content == "My commit message\n\n- Bullet 1"

    def test_metadata_content(self, temp_dir):
        """Test that metadata is saved correctly."""
        save_cache(
            repo_root=temp_dir,
            context_hash="hash123",
            message="message",
            model="claude-3",
            input_tokens=200,
            output_tokens=75,
            staged_files=["a.py", "b.py"],
            diff_preview="preview",
        )

        metadata = load_cache_metadata(temp_dir)
        assert metadata is not None
        assert metadata.context_hash == "hash123"
        assert metadata.model == "claude-3"
        assert metadata.input_tokens == 200
        assert metadata.output_tokens == 75
        assert metadata.staged_files == ["a.py", "b.py"]


class TestUpdateMessageCache:
    """Tests for update_message_cache function."""

    def test_updates_message(self, temp_dir):
        """Test that message is updated."""
        # First save
        save_cache(
            repo_root=temp_dir,
            context_hash="hash",
            message="original message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=[],
            diff_preview="",
        )

        # Update
        update_message_cache(temp_dir, "updated message")

        message = load_cached_message(temp_dir)
        assert message == "updated message"


class TestLoadCacheMetadata:
    """Tests for load_cache_metadata function."""

    def test_loads_valid_metadata(self, temp_dir):
        """Test loading valid metadata."""
        save_cache(
            repo_root=temp_dir,
            context_hash="hash",
            message="message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file.py"],
            diff_preview="diff",
        )

        metadata = load_cache_metadata(temp_dir)
        assert metadata is not None
        assert metadata.model == "gpt-4"

    def test_returns_none_if_missing(self, temp_dir):
        """Test that None is returned if metadata file missing."""
        metadata = load_cache_metadata(temp_dir)
        assert metadata is None

    def test_returns_none_if_corrupted(self, temp_dir):
        """Test that None is returned if metadata is corrupted."""
        cache_dir = temp_dir / ".aicommit"
        cache_dir.mkdir()

        metadata_file = cache_dir / "aicommit_metadata.json"
        metadata_file.write_text("not valid json")

        metadata = load_cache_metadata(temp_dir)
        assert metadata is None


class TestInvalidateCache:
    """Tests for invalidate_cache function."""

    def test_removes_all_files(self, temp_dir):
        """Test that all cache files are removed."""
        save_cache(
            repo_root=temp_dir,
            context_hash="hash",
            message="message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=[],
            diff_preview="",
        )

        # Verify files exist
        cache_dir = temp_dir / ".aicommit"
        assert (cache_dir / "aicommit_context_hash.txt").exists()
        assert (cache_dir / "aicommit_message.txt").exists()
        assert (cache_dir / "aicommit_metadata.json").exists()

        # Invalidate
        invalidate_cache(temp_dir)

        # Verify files removed
        assert not (cache_dir / "aicommit_context_hash.txt").exists()
        assert not (cache_dir / "aicommit_message.txt").exists()
        assert not (cache_dir / "aicommit_metadata.json").exists()

    def test_handles_missing_files(self, temp_dir):
        """Test that invalidate doesn't error on missing files."""
        # Should not raise
        invalidate_cache(temp_dir)


class TestExtractStagedFiles:
    """Tests for extract_staged_files function."""

    def test_extracts_added_files(self):
        """Test extracting added files."""
        status = "## main\nA  new_file.py"
        files = extract_staged_files(status)
        assert "new_file.py" in files

    def test_extracts_modified_files(self):
        """Test extracting modified files."""
        status = "## main\nM  modified_file.py"
        files = extract_staged_files(status)
        assert "modified_file.py" in files

    def test_extracts_deleted_files(self):
        """Test extracting deleted files."""
        status = "## main\nD  deleted_file.py"
        files = extract_staged_files(status)
        assert "deleted_file.py" in files

    def test_ignores_unstaged_files(self):
        """Test that unstaged files are ignored."""
        status = "## main\n M unstaged.py"
        files = extract_staged_files(status)
        assert "unstaged.py" not in files

    def test_ignores_untracked_files(self):
        """Test that untracked files are ignored."""
        status = "## main\n?? untracked.py"
        files = extract_staged_files(status)
        assert "untracked.py" not in files

    def test_handles_renamed_files(self):
        """Test handling renamed files."""
        status = "## main\nR  old_name.py -> new_name.py"
        files = extract_staged_files(status)
        assert "new_name.py" in files
        assert "old_name.py" not in files

    def test_multiple_files(self):
        """Test extracting multiple files."""
        status = "## main\nA  file1.py\nM  file2.py\nD  file3.py"
        files = extract_staged_files(status)
        assert len(files) == 3
        assert "file1.py" in files
        assert "file2.py" in files
        assert "file3.py" in files

    def test_ignores_branch_line(self):
        """Test that branch line is ignored."""
        status = "## main...origin/main"
        files = extract_staged_files(status)
        assert len(files) == 0


class TestGetDiffPreview:
    """Tests for get_diff_preview function."""

    def test_short_diff_unchanged(self):
        """Test that short diff is unchanged."""
        diff = "short diff"
        result = get_diff_preview(diff, max_chars=100)
        assert result == diff

    def test_long_diff_truncated(self):
        """Test that long diff is truncated."""
        diff = "a" * 1000
        result = get_diff_preview(diff, max_chars=100)
        assert len(result) < 120  # 100 + truncation message
        assert result.endswith("...[truncated]")

    def test_exact_max_chars_unchanged(self):
        """Test that diff at exact max length is unchanged."""
        diff = "a" * 100
        result = get_diff_preview(diff, max_chars=100)
        assert result == diff
