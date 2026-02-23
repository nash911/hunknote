"""Tests for hunknote.cache module."""


from hunknote.cache import (
    CacheMetadata,
    ComposeCacheMetadata,
    compute_context_hash,
    extract_staged_files,
    get_cache_dir,
    get_compose_hash_file,
    get_compose_hunk_ids_file,
    get_compose_metadata_file,
    get_compose_plan_file,
    get_diff_preview,
    get_hash_file,
    get_message_file,
    get_metadata_file,
    get_raw_json_file,
    invalidate_cache,
    invalidate_compose_cache,
    is_cache_valid,
    is_compose_cache_valid,
    load_cache_metadata,
    load_cached_message,
    load_compose_hunk_ids,
    load_compose_metadata,
    load_compose_plan,
    save_cache,
    save_compose_cache,
    save_compose_hunk_ids,
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

    def test_create_metadata_with_char_counts(self):
        """Test creating cache metadata with character counts."""
        metadata = CacheMetadata(
            context_hash="abc123",
            generated_at="2024-01-01T00:00:00+00:00",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file1.py"],
            original_message="Test message",
            diff_preview="diff content",
            input_chars=5000,
            prompt_chars=8000,
            output_chars=1500,
        )
        assert metadata.input_chars == 5000
        assert metadata.prompt_chars == 8000
        assert metadata.output_chars == 1500

    def test_char_counts_default_to_zero(self):
        """Test that character counts default to zero for backward compatibility."""
        metadata = CacheMetadata(
            context_hash="abc123",
            generated_at="2024-01-01T00:00:00+00:00",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file1.py"],
            original_message="Test message",
            diff_preview="diff content",
        )
        assert metadata.input_chars == 0
        assert metadata.prompt_chars == 0
        assert metadata.output_chars == 0


class TestGetCacheDir:
    """Tests for get_cache_dir function."""

    def test_creates_cache_dir(self, temp_dir):
        """Test that cache directory is created."""
        cache_dir = get_cache_dir(temp_dir)
        assert cache_dir.exists()
        assert cache_dir.name == ".hunknote"

    def test_returns_existing_dir(self, temp_dir):
        """Test that existing directory is returned."""
        hunknote_dir = temp_dir / ".hunknote"
        hunknote_dir.mkdir()

        cache_dir = get_cache_dir(temp_dir)
        assert cache_dir == hunknote_dir


class TestCacheFilePaths:
    """Tests for cache file path functions."""

    def test_get_message_file(self, temp_dir):
        """Test message file path."""
        path = get_message_file(temp_dir)
        assert path.name == "hunknote_message.txt"
        assert path.parent.name == ".hunknote"

    def test_get_hash_file(self, temp_dir):
        """Test hash file path."""
        path = get_hash_file(temp_dir)
        assert path.name == "hunknote_context_hash.txt"

    def test_get_metadata_file(self, temp_dir):
        """Test metadata file path."""
        path = get_metadata_file(temp_dir)
        assert path.name == "hunknote_metadata.json"

    def test_get_raw_json_file(self, temp_dir):
        """Test raw JSON response file path."""
        path = get_raw_json_file(temp_dir)
        assert path.name == "hunknote_llm_response.json"
        assert path.parent.name == ".hunknote"
        path = get_metadata_file(temp_dir)
        assert path.name == "hunknote_metadata.json"


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
        cache_dir = temp_dir / ".hunknote"
        cache_dir.mkdir()

        hash_file = cache_dir / "hunknote_context_hash.txt"
        message_file = cache_dir / "hunknote_message.txt"

        hash_file.write_text("abc123")
        message_file.write_text("test message")

        assert is_cache_valid(temp_dir, "abc123") is True

    def test_different_hash_invalid(self, temp_dir):
        """Test that different hash is invalid."""
        cache_dir = temp_dir / ".hunknote"
        cache_dir.mkdir()

        hash_file = cache_dir / "hunknote_context_hash.txt"
        message_file = cache_dir / "hunknote_message.txt"

        hash_file.write_text("abc123")
        message_file.write_text("test message")

        assert is_cache_valid(temp_dir, "xyz789") is False

    def test_missing_message_file_invalid(self, temp_dir):
        """Test that missing message file means invalid."""
        cache_dir = temp_dir / ".hunknote"
        cache_dir.mkdir()

        hash_file = cache_dir / "hunknote_context_hash.txt"
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

        cache_dir = temp_dir / ".hunknote"
        assert (cache_dir / "hunknote_context_hash.txt").exists()
        assert (cache_dir / "hunknote_message.txt").exists()
        assert (cache_dir / "hunknote_metadata.json").exists()

    def test_saves_raw_json_response(self, temp_dir):
        """Test that raw JSON response is saved."""
        raw_json = '{"type": "feat", "scope": "api", "title": "Add endpoint"}'
        save_cache(
            repo_root=temp_dir,
            context_hash="abc123",
            message="Test commit message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file1.py"],
            diff_preview="diff preview",
            raw_response=raw_json,
        )

        cache_dir = temp_dir / ".hunknote"
        assert (cache_dir / "hunknote_llm_response.json").exists()
        assert (cache_dir / "hunknote_llm_response.json").read_text() == raw_json

    def test_raw_json_not_saved_when_empty(self, temp_dir):
        """Test that raw JSON file is not created when empty."""
        save_cache(
            repo_root=temp_dir,
            context_hash="abc123",
            message="Test commit message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file1.py"],
            diff_preview="diff preview",
            raw_response="",
        )

        cache_dir = temp_dir / ".hunknote"
        assert not (cache_dir / "hunknote_llm_response.json").exists()

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

    def test_saves_char_counts(self, temp_dir):
        """Test that character counts are saved in metadata."""
        save_cache(
            repo_root=temp_dir,
            context_hash="hash123",
            message="message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file.py"],
            diff_preview="preview",
            input_chars=5000,
            prompt_chars=8000,
            output_chars=1500,
        )

        metadata = load_cache_metadata(temp_dir)
        assert metadata is not None
        assert metadata.input_chars == 5000
        assert metadata.prompt_chars == 8000
        assert metadata.output_chars == 1500

    def test_char_counts_default_to_zero_in_metadata(self, temp_dir):
        """Test that character counts default to zero when not provided."""
        save_cache(
            repo_root=temp_dir,
            context_hash="hash123",
            message="message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file.py"],
            diff_preview="preview",
        )

        metadata = load_cache_metadata(temp_dir)
        assert metadata is not None
        assert metadata.input_chars == 0
        assert metadata.prompt_chars == 0
        assert metadata.output_chars == 0


class TestLoadRawJsonResponse:
    """Tests for load_raw_json_response function."""

    def test_loads_existing_json(self, temp_dir):
        """Test loading existing raw JSON response."""
        from hunknote.cache import load_raw_json_response

        raw_json = '{"type": "feat", "scope": "api"}'
        save_cache(
            repo_root=temp_dir,
            context_hash="hash",
            message="message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=[],
            diff_preview="",
            raw_response=raw_json,
        )

        result = load_raw_json_response(temp_dir)
        assert result == raw_json

    def test_returns_none_when_not_exists(self, temp_dir):
        """Test returns None when file doesn't exist."""
        from hunknote.cache import load_raw_json_response

        result = load_raw_json_response(temp_dir)
        assert result is None

    def test_returns_none_when_cache_without_json(self, temp_dir):
        """Test returns None when cache exists but no JSON file."""
        from hunknote.cache import load_raw_json_response

        # Save without raw_response
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

        result = load_raw_json_response(temp_dir)
        assert result is None


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
        cache_dir = temp_dir / ".hunknote"
        cache_dir.mkdir()

        metadata_file = cache_dir / "hunknote_metadata.json"
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
            raw_response='{"type": "feat", "scope": "test"}',
        )

        # Verify files exist
        cache_dir = temp_dir / ".hunknote"
        assert (cache_dir / "hunknote_context_hash.txt").exists()
        assert (cache_dir / "hunknote_message.txt").exists()
        assert (cache_dir / "hunknote_metadata.json").exists()
        assert (cache_dir / "hunknote_llm_response.json").exists()

        # Invalidate
        invalidate_cache(temp_dir)

        # Verify files removed
        assert not (cache_dir / "hunknote_context_hash.txt").exists()
        assert not (cache_dir / "hunknote_message.txt").exists()
        assert not (cache_dir / "hunknote_metadata.json").exists()
        assert not (cache_dir / "hunknote_llm_response.json").exists()

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


class TestLoadCachedMessage:
    """Tests for load_cached_message function."""

    def test_returns_message_when_exists(self, temp_dir):
        """Test that message is returned when file exists."""
        save_cache(
            repo_root=temp_dir,
            context_hash="hash",
            message="Test commit message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file.py"],
            diff_preview="diff",
        )

        result = load_cached_message(temp_dir)
        assert result == "Test commit message"

    def test_returns_none_when_file_missing(self, temp_dir):
        """Test that None is returned when message file doesn't exist."""
        # Create .hunknote dir but no message file
        cache_dir = temp_dir / ".hunknote"
        cache_dir.mkdir()

        result = load_cached_message(temp_dir)
        assert result is None

    def test_returns_none_when_dir_missing(self, temp_dir):
        """Test that None is returned when .hunknote dir doesn't exist."""
        result = load_cached_message(temp_dir)
        assert result is None


class TestUpdateMetadataOverrides:
    """Tests for update_metadata_overrides function."""

    def test_updates_scope_override(self, temp_dir):
        """Test updating scope override in metadata."""
        from hunknote.cache import update_metadata_overrides

        # First create initial cache
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

        # Update with scope override
        update_metadata_overrides(temp_dir, scope_override="api")

        metadata = load_cache_metadata(temp_dir)
        assert metadata.scope_override == "api"

    def test_updates_ticket_override(self, temp_dir):
        """Test updating ticket override in metadata."""
        from hunknote.cache import update_metadata_overrides

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

        update_metadata_overrides(temp_dir, ticket_override="PROJ-123")

        metadata = load_cache_metadata(temp_dir)
        assert metadata.ticket_override == "PROJ-123"

    def test_updates_no_scope_override(self, temp_dir):
        """Test updating no_scope override in metadata."""
        from hunknote.cache import update_metadata_overrides

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

        update_metadata_overrides(temp_dir, no_scope_override=True)

        metadata = load_cache_metadata(temp_dir)
        assert metadata.no_scope_override is True

    def test_updates_multiple_overrides(self, temp_dir):
        """Test updating multiple overrides at once."""
        from hunknote.cache import update_metadata_overrides

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

        update_metadata_overrides(
            temp_dir,
            scope_override="ui",
            ticket_override="BUG-456",
            no_scope_override=False,
        )

        metadata = load_cache_metadata(temp_dir)
        assert metadata.scope_override == "ui"
        assert metadata.ticket_override == "BUG-456"
        assert metadata.no_scope_override is False

    def test_does_nothing_if_no_metadata(self, temp_dir):
        """Test that update does nothing if metadata doesn't exist."""
        from hunknote.cache import update_metadata_overrides

        # Should not raise error
        update_metadata_overrides(temp_dir, scope_override="api")

        # Metadata should still not exist
        metadata = load_cache_metadata(temp_dir)
        assert metadata is None


# ============================================================================
# Compose Cache Tests
# ============================================================================


class TestComposeCacheMetadata:
    """Tests for ComposeCacheMetadata model."""

    def test_create_compose_metadata(self):
        """Test creating compose cache metadata."""
        from hunknote.cache import ComposeCacheMetadata

        metadata = ComposeCacheMetadata(
            context_hash="abc123",
            generated_at="2024-01-01T00:00:00+00:00",
            model="gpt-4",
            input_tokens=500,
            output_tokens=200,
            changed_files=["file1.py", "file2.py"],
            total_hunks=5,
            num_commits=3,
            style="conventional",
            max_commits=6,
        )
        assert metadata.context_hash == "abc123"
        assert metadata.model == "gpt-4"
        assert metadata.total_hunks == 5
        assert metadata.num_commits == 3
        assert len(metadata.changed_files) == 2

    def test_compose_metadata_all_fields_required(self):
        """Test that all fields are required for compose metadata."""
        import pytest
        from pydantic import ValidationError
        from hunknote.cache import ComposeCacheMetadata

        with pytest.raises(ValidationError):
            ComposeCacheMetadata(
                context_hash="abc",
                # Missing required fields
            )

    def test_compose_metadata_retry_stats_defaults(self):
        """Test that retry stats have sensible defaults."""
        from hunknote.cache import ComposeCacheMetadata

        metadata = ComposeCacheMetadata(
            context_hash="abc123",
            generated_at="2024-01-01T00:00:00+00:00",
            model="gpt-4",
            input_tokens=500,
            output_tokens=200,
            changed_files=["file1.py"],
            total_hunks=5,
            num_commits=3,
            style="conventional",
            max_commits=6,
        )
        # Defaults should be 0 retries and None stats
        assert metadata.retry_count == 0
        assert metadata.retry_stats is None

    def test_compose_metadata_with_retry_stats(self):
        """Test creating compose metadata with retry statistics."""
        from hunknote.cache import ComposeCacheMetadata

        retry_stats = [
            {
                "retry_number": 1,
                "input_tokens": 1000,
                "output_tokens": 500,
                "errors_before": ["Commit C1 references unknown hunk: H2_wrong"],
                "success": True,
            }
        ]

        metadata = ComposeCacheMetadata(
            context_hash="abc123",
            generated_at="2024-01-01T00:00:00+00:00",
            model="gpt-4",
            input_tokens=1500,  # Total including retry
            output_tokens=700,
            changed_files=["file1.py"],
            total_hunks=5,
            num_commits=3,
            style="conventional",
            max_commits=6,
            retry_count=1,
            retry_stats=retry_stats,
        )
        assert metadata.retry_count == 1
        assert metadata.retry_stats is not None
        assert len(metadata.retry_stats) == 1
        assert metadata.retry_stats[0]["success"] is True
        assert metadata.retry_stats[0]["input_tokens"] == 1000

    def test_compose_metadata_multiple_retries(self):
        """Test compose metadata with multiple retry attempts."""
        from hunknote.cache import ComposeCacheMetadata

        retry_stats = [
            {
                "retry_number": 1,
                "input_tokens": 1000,
                "output_tokens": 400,
                "errors_before": ["Error 1"],
                "success": False,
            },
            {
                "retry_number": 2,
                "input_tokens": 1200,
                "output_tokens": 500,
                "errors_before": ["Error 2"],
                "success": True,
            },
        ]

        metadata = ComposeCacheMetadata(
            context_hash="abc123",
            generated_at="2024-01-01T00:00:00+00:00",
            model="gpt-4",
            input_tokens=2700,  # Total: 500 + 1000 + 1200
            output_tokens=1100,  # Total: 200 + 400 + 500
            changed_files=["file1.py"],
            total_hunks=5,
            num_commits=3,
            style="conventional",
            max_commits=6,
            retry_count=2,
            retry_stats=retry_stats,
        )
        assert metadata.retry_count == 2
        assert len(metadata.retry_stats) == 2
        assert metadata.retry_stats[0]["success"] is False
        assert metadata.retry_stats[1]["success"] is True


class TestComposeFilePaths:
    """Tests for compose cache file path functions."""

    def test_get_compose_hash_file(self, temp_dir):
        """Test compose hash file path."""
        from hunknote.cache import get_compose_hash_file

        path = get_compose_hash_file(temp_dir)
        assert path.name == "hunknote_compose_hash.txt"
        assert path.parent.name == ".hunknote"

    def test_get_compose_plan_file(self, temp_dir):
        """Test compose plan file path."""
        from hunknote.cache import get_compose_plan_file

        path = get_compose_plan_file(temp_dir)
        assert path.name == "hunknote_compose_plan.json"
        assert path.parent.name == ".hunknote"

    def test_get_compose_metadata_file(self, temp_dir):
        """Test compose metadata file path."""
        from hunknote.cache import get_compose_metadata_file

        path = get_compose_metadata_file(temp_dir)
        assert path.name == "hunknote_compose_metadata.json"
        assert path.parent.name == ".hunknote"

    def test_get_compose_hunk_ids_file(self, temp_dir):
        """Test compose hunk IDs file path."""
        from hunknote.cache import get_compose_hunk_ids_file

        path = get_compose_hunk_ids_file(temp_dir)
        assert path.name == "hunknote_hunk_ids.json"
        assert path.parent.name == ".hunknote"


class TestIsComposeCacheValid:
    """Tests for is_compose_cache_valid function."""

    def test_no_cache_files_invalid(self, temp_dir):
        """Test that missing cache files means invalid."""
        from hunknote.cache import is_compose_cache_valid

        assert is_compose_cache_valid(temp_dir, "abc123") is False

    def test_matching_hash_valid(self, temp_dir):
        """Test that matching hash is valid."""
        from hunknote.cache import (
            is_compose_cache_valid,
            get_compose_hash_file,
            get_compose_plan_file,
            get_cache_dir,
        )

        cache_dir = get_cache_dir(temp_dir)
        get_compose_hash_file(temp_dir).write_text("abc123")
        get_compose_plan_file(temp_dir).write_text('{"commits": []}')

        assert is_compose_cache_valid(temp_dir, "abc123") is True

    def test_different_hash_invalid(self, temp_dir):
        """Test that different hash is invalid."""
        from hunknote.cache import (
            is_compose_cache_valid,
            get_compose_hash_file,
            get_compose_plan_file,
            get_cache_dir,
        )

        cache_dir = get_cache_dir(temp_dir)
        get_compose_hash_file(temp_dir).write_text("abc123")
        get_compose_plan_file(temp_dir).write_text('{"commits": []}')

        assert is_compose_cache_valid(temp_dir, "xyz789") is False

    def test_missing_plan_file_invalid(self, temp_dir):
        """Test that missing plan file means invalid."""
        from hunknote.cache import (
            is_compose_cache_valid,
            get_compose_hash_file,
            get_cache_dir,
        )

        cache_dir = get_cache_dir(temp_dir)
        get_compose_hash_file(temp_dir).write_text("abc123")
        # No plan file

        assert is_compose_cache_valid(temp_dir, "abc123") is False


class TestSaveComposeCache:
    """Tests for save_compose_cache function."""

    def test_saves_all_files(self, temp_dir):
        """Test that all compose cache files are saved."""
        from hunknote.cache import save_compose_cache

        save_compose_cache(
            repo_root=temp_dir,
            context_hash="hash123",
            plan_json='{"commits": []}',
            model="gpt-4",
            input_tokens=500,
            output_tokens=200,
            changed_files=["file.py"],
            total_hunks=3,
            num_commits=2,
            style="conventional",
            max_commits=6,
        )

        cache_dir = temp_dir / ".hunknote"
        assert (cache_dir / "hunknote_compose_hash.txt").exists()
        assert (cache_dir / "hunknote_compose_plan.json").exists()
        assert (cache_dir / "hunknote_compose_metadata.json").exists()

    def test_hash_content(self, temp_dir):
        """Test that compose hash is saved correctly."""
        from hunknote.cache import save_compose_cache, get_compose_hash_file

        save_compose_cache(
            repo_root=temp_dir,
            context_hash="test_compose_hash",
            plan_json='{"commits": []}',
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            changed_files=[],
            total_hunks=1,
            num_commits=1,
            style="default",
            max_commits=6,
        )

        hash_content = get_compose_hash_file(temp_dir).read_text()
        assert hash_content == "test_compose_hash"

    def test_plan_content(self, temp_dir):
        """Test that compose plan is saved correctly."""
        from hunknote.cache import save_compose_cache, get_compose_plan_file

        plan_json = '{"commits": [{"id": "C1", "title": "Test"}]}'
        save_compose_cache(
            repo_root=temp_dir,
            context_hash="hash",
            plan_json=plan_json,
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            changed_files=[],
            total_hunks=1,
            num_commits=1,
            style="default",
            max_commits=6,
        )

        plan_content = get_compose_plan_file(temp_dir).read_text()
        assert plan_content == plan_json

    def test_metadata_content(self, temp_dir):
        """Test that compose metadata is saved correctly."""
        from hunknote.cache import save_compose_cache, load_compose_metadata

        save_compose_cache(
            repo_root=temp_dir,
            context_hash="hash456",
            plan_json='{"commits": []}',
            model="claude-3",
            input_tokens=300,
            output_tokens=150,
            changed_files=["a.py", "b.py"],
            total_hunks=5,
            num_commits=3,
            style="blueprint",
            max_commits=8,
        )

        metadata = load_compose_metadata(temp_dir)
        assert metadata is not None
        assert metadata.context_hash == "hash456"
        assert metadata.model == "claude-3"
        assert metadata.input_tokens == 300
        assert metadata.output_tokens == 150
        assert metadata.changed_files == ["a.py", "b.py"]
        assert metadata.total_hunks == 5
        assert metadata.num_commits == 3
        assert metadata.style == "blueprint"
        assert metadata.max_commits == 8


class TestLoadComposePlan:
    """Tests for load_compose_plan function."""

    def test_loads_existing_plan(self, temp_dir):
        """Test loading existing compose plan."""
        from hunknote.cache import save_compose_cache, load_compose_plan

        plan_json = '{"commits": [{"id": "C1"}]}'
        save_compose_cache(
            repo_root=temp_dir,
            context_hash="hash",
            plan_json=plan_json,
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            changed_files=[],
            total_hunks=1,
            num_commits=1,
            style="default",
            max_commits=6,
        )

        result = load_compose_plan(temp_dir)
        assert result == plan_json

    def test_returns_none_when_not_exists(self, temp_dir):
        """Test returns None when plan file doesn't exist."""
        from hunknote.cache import load_compose_plan

        result = load_compose_plan(temp_dir)
        assert result is None


class TestLoadComposeMetadata:
    """Tests for load_compose_metadata function."""

    def test_loads_valid_metadata(self, temp_dir):
        """Test loading valid compose metadata."""
        from hunknote.cache import save_compose_cache, load_compose_metadata

        save_compose_cache(
            repo_root=temp_dir,
            context_hash="hash",
            plan_json='{"commits": []}',
            model="gpt-4",
            input_tokens=200,
            output_tokens=100,
            changed_files=["file.py"],
            total_hunks=4,
            num_commits=2,
            style="conventional",
            max_commits=6,
        )

        metadata = load_compose_metadata(temp_dir)
        assert metadata is not None
        assert metadata.model == "gpt-4"
        assert metadata.total_hunks == 4

    def test_returns_none_if_missing(self, temp_dir):
        """Test that None is returned if metadata file missing."""
        from hunknote.cache import load_compose_metadata

        metadata = load_compose_metadata(temp_dir)
        assert metadata is None

    def test_returns_none_if_corrupted(self, temp_dir):
        """Test that None is returned if metadata is corrupted."""
        from hunknote.cache import load_compose_metadata, get_compose_metadata_file, get_cache_dir

        cache_dir = get_cache_dir(temp_dir)
        metadata_file = get_compose_metadata_file(temp_dir)
        metadata_file.write_text("not valid json")

        metadata = load_compose_metadata(temp_dir)
        assert metadata is None


class TestInvalidateComposeCache:
    """Tests for invalidate_compose_cache function."""

    def test_removes_all_files(self, temp_dir):
        """Test that all compose cache files are removed."""
        from hunknote.cache import (
            save_compose_cache,
            invalidate_compose_cache,
            save_compose_hunk_ids,
        )

        save_compose_cache(
            repo_root=temp_dir,
            context_hash="hash",
            plan_json='{"commits": []}',
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            changed_files=[],
            total_hunks=1,
            num_commits=1,
            style="default",
            max_commits=6,
        )

        # Also save hunk IDs
        save_compose_hunk_ids(temp_dir, [{"hunk_id": "H1"}])

        # Verify files exist
        cache_dir = temp_dir / ".hunknote"
        assert (cache_dir / "hunknote_compose_hash.txt").exists()
        assert (cache_dir / "hunknote_compose_plan.json").exists()
        assert (cache_dir / "hunknote_compose_metadata.json").exists()
        assert (cache_dir / "hunknote_hunk_ids.json").exists()

        # Invalidate
        invalidate_compose_cache(temp_dir)

        # Verify files removed
        assert not (cache_dir / "hunknote_compose_hash.txt").exists()
        assert not (cache_dir / "hunknote_compose_plan.json").exists()
        assert not (cache_dir / "hunknote_compose_metadata.json").exists()
        assert not (cache_dir / "hunknote_hunk_ids.json").exists()

    def test_handles_missing_files(self, temp_dir):
        """Test that invalidate doesn't error on missing files."""
        from hunknote.cache import invalidate_compose_cache

        # Should not raise
        invalidate_compose_cache(temp_dir)


class TestSaveComposeHunkIds:
    """Tests for save_compose_hunk_ids function."""

    def test_saves_hunk_ids(self, temp_dir):
        """Test saving hunk IDs to file."""
        from hunknote.cache import save_compose_hunk_ids, get_compose_hunk_ids_file

        hunk_data = [
            {"hunk_id": "H1", "file": "file1.py", "commit_id": "C1"},
            {"hunk_id": "H2", "file": "file2.py", "commit_id": "C2"},
        ]

        save_compose_hunk_ids(temp_dir, hunk_data)

        hunk_file = get_compose_hunk_ids_file(temp_dir)
        assert hunk_file.exists()

    def test_saves_correct_json(self, temp_dir):
        """Test that hunk IDs are saved as correct JSON."""
        import json
        from hunknote.cache import save_compose_hunk_ids, get_compose_hunk_ids_file

        hunk_data = [
            {"hunk_id": "H1", "file": "test.py", "commit_id": "C1", "header": "@@ -1,5 +1,7 @@"},
        ]

        save_compose_hunk_ids(temp_dir, hunk_data)

        hunk_file = get_compose_hunk_ids_file(temp_dir)
        loaded = json.loads(hunk_file.read_text())
        assert loaded == hunk_data

    def test_saves_empty_list(self, temp_dir):
        """Test saving empty hunk list."""
        import json
        from hunknote.cache import save_compose_hunk_ids, get_compose_hunk_ids_file

        save_compose_hunk_ids(temp_dir, [])

        hunk_file = get_compose_hunk_ids_file(temp_dir)
        loaded = json.loads(hunk_file.read_text())
        assert loaded == []


class TestLoadComposeHunkIds:
    """Tests for load_compose_hunk_ids function."""

    def test_loads_existing_hunk_ids(self, temp_dir):
        """Test loading existing hunk IDs."""
        from hunknote.cache import save_compose_hunk_ids, load_compose_hunk_ids

        hunk_data = [
            {"hunk_id": "H1", "file": "file.py", "commit_id": "C1"},
            {"hunk_id": "H2", "file": "file.py", "commit_id": "C1"},
        ]

        save_compose_hunk_ids(temp_dir, hunk_data)

        result = load_compose_hunk_ids(temp_dir)
        assert result == hunk_data

    def test_returns_none_when_not_exists(self, temp_dir):
        """Test returns None when hunk IDs file doesn't exist."""
        from hunknote.cache import load_compose_hunk_ids

        result = load_compose_hunk_ids(temp_dir)
        assert result is None

    def test_returns_none_when_corrupted(self, temp_dir):
        """Test returns None when hunk IDs file is corrupted."""
        from hunknote.cache import load_compose_hunk_ids, get_compose_hunk_ids_file, get_cache_dir

        cache_dir = get_cache_dir(temp_dir)
        hunk_file = get_compose_hunk_ids_file(temp_dir)
        hunk_file.write_text("not valid json")

        result = load_compose_hunk_ids(temp_dir)
        assert result is None


class TestSaveCacheWithOverrides:
    """Tests for save_cache with rendering overrides."""

    def test_saves_scope_override(self, temp_dir):
        """Test saving cache with scope override."""
        save_cache(
            repo_root=temp_dir,
            context_hash="hash",
            message="message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file.py"],
            diff_preview="diff",
            scope_override="api",
        )

        metadata = load_cache_metadata(temp_dir)
        assert metadata.scope_override == "api"

    def test_saves_ticket_override(self, temp_dir):
        """Test saving cache with ticket override."""
        save_cache(
            repo_root=temp_dir,
            context_hash="hash",
            message="message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file.py"],
            diff_preview="diff",
            ticket_override="PROJ-123",
        )

        metadata = load_cache_metadata(temp_dir)
        assert metadata.ticket_override == "PROJ-123"

    def test_saves_no_scope_override(self, temp_dir):
        """Test saving cache with no_scope override."""
        save_cache(
            repo_root=temp_dir,
            context_hash="hash",
            message="message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file.py"],
            diff_preview="diff",
            no_scope_override=True,
        )

        metadata = load_cache_metadata(temp_dir)
        assert metadata.no_scope_override is True

    def test_saves_all_overrides(self, temp_dir):
        """Test saving cache with all overrides."""
        save_cache(
            repo_root=temp_dir,
            context_hash="hash",
            message="message",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file.py"],
            diff_preview="diff",
            scope_override="ui",
            ticket_override="BUG-456",
            no_scope_override=False,
        )

        metadata = load_cache_metadata(temp_dir)
        assert metadata.scope_override == "ui"
        assert metadata.ticket_override == "BUG-456"
        assert metadata.no_scope_override is False

    def test_overrides_default_to_none(self, temp_dir):
        """Test that overrides default to None/False when not provided."""
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
        assert metadata.scope_override is None
        assert metadata.ticket_override is None
        assert metadata.no_scope_override is False


class TestCacheMetadataOverrideFields:
    """Tests for override fields in CacheMetadata model."""

    def test_scope_override_field(self):
        """Test scope_override field in CacheMetadata."""
        metadata = CacheMetadata(
            context_hash="abc123",
            generated_at="2024-01-01T00:00:00+00:00",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file.py"],
            original_message="Test",
            diff_preview="diff",
            scope_override="api",
        )
        assert metadata.scope_override == "api"

    def test_ticket_override_field(self):
        """Test ticket_override field in CacheMetadata."""
        metadata = CacheMetadata(
            context_hash="abc123",
            generated_at="2024-01-01T00:00:00+00:00",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file.py"],
            original_message="Test",
            diff_preview="diff",
            ticket_override="PROJ-123",
        )
        assert metadata.ticket_override == "PROJ-123"

    def test_no_scope_override_field(self):
        """Test no_scope_override field in CacheMetadata."""
        metadata = CacheMetadata(
            context_hash="abc123",
            generated_at="2024-01-01T00:00:00+00:00",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file.py"],
            original_message="Test",
            diff_preview="diff",
            no_scope_override=True,
        )
        assert metadata.no_scope_override is True

    def test_override_fields_default_correctly(self):
        """Test that override fields default to None/False."""
        metadata = CacheMetadata(
            context_hash="abc123",
            generated_at="2024-01-01T00:00:00+00:00",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            staged_files=["file.py"],
            original_message="Test",
            diff_preview="diff",
        )
        assert metadata.scope_override is None
        assert metadata.ticket_override is None
        assert metadata.no_scope_override is False


class TestComposeCacheIntegration:
    """Integration tests for compose caching workflow."""

    def test_full_compose_cache_workflow(self, temp_dir):
        """Test the full compose cache save/load/invalidate workflow."""
        from hunknote.cache import (
            save_compose_cache,
            load_compose_plan,
            load_compose_metadata,
            is_compose_cache_valid,
            invalidate_compose_cache,
            save_compose_hunk_ids,
            load_compose_hunk_ids,
        )

        context_hash = "workflow_test_hash"
        plan_json = '{"commits": [{"id": "C1", "title": "Test commit"}]}'
        hunk_data = [{"hunk_id": "H1", "file": "test.py", "commit_id": "C1"}]

        # Step 1: Save cache
        save_compose_cache(
            repo_root=temp_dir,
            context_hash=context_hash,
            plan_json=plan_json,
            model="gpt-4",
            input_tokens=500,
            output_tokens=250,
            changed_files=["test.py"],
            total_hunks=1,
            num_commits=1,
            style="conventional",
            max_commits=6,
        )
        save_compose_hunk_ids(temp_dir, hunk_data)

        # Step 2: Verify cache is valid
        assert is_compose_cache_valid(temp_dir, context_hash) is True
        assert is_compose_cache_valid(temp_dir, "different_hash") is False

        # Step 3: Load and verify data
        loaded_plan = load_compose_plan(temp_dir)
        assert loaded_plan == plan_json

        loaded_metadata = load_compose_metadata(temp_dir)
        assert loaded_metadata is not None
        assert loaded_metadata.model == "gpt-4"

        loaded_hunks = load_compose_hunk_ids(temp_dir)
        assert loaded_hunks == hunk_data

        # Step 4: Invalidate and verify
        invalidate_compose_cache(temp_dir)

        assert is_compose_cache_valid(temp_dir, context_hash) is False
        assert load_compose_plan(temp_dir) is None
        assert load_compose_metadata(temp_dir) is None
        assert load_compose_hunk_ids(temp_dir) is None

    def test_cache_overwrite(self, temp_dir):
        """Test that saving cache overwrites existing cache."""
        from hunknote.cache import (
            save_compose_cache,
            load_compose_plan,
            is_compose_cache_valid,
        )

        # Save first cache
        save_compose_cache(
            repo_root=temp_dir,
            context_hash="hash1",
            plan_json='{"commits": [{"id": "C1"}]}',
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            changed_files=[],
            total_hunks=1,
            num_commits=1,
            style="default",
            max_commits=6,
        )

        assert is_compose_cache_valid(temp_dir, "hash1") is True

        # Save second cache with different hash
        save_compose_cache(
            repo_root=temp_dir,
            context_hash="hash2",
            plan_json='{"commits": [{"id": "C2"}]}',
            model="claude-3",
            input_tokens=200,
            output_tokens=100,
            changed_files=[],
            total_hunks=2,
            num_commits=2,
            style="blueprint",
            max_commits=8,
        )

        # Old hash should be invalid, new hash should be valid
        assert is_compose_cache_valid(temp_dir, "hash1") is False
        assert is_compose_cache_valid(temp_dir, "hash2") is True

        # Plan should be the new one
        plan = load_compose_plan(temp_dir)
        assert "C2" in plan

