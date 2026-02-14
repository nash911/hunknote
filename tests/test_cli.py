"""Tests for hunknote.cli module."""

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from hunknote.cli import app


runner = CliRunner()


class TestIgnoreListCommand:
    """Tests for hunknote ignore list command."""

    def test_lists_patterns(self, mocker, temp_dir):
        """Test listing ignore patterns."""
        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mocker.patch(
            "hunknote.cli.get_ignore_patterns",
            return_value=["poetry.lock", "*.log", "build/*"]
        )

        result = runner.invoke(app, ["ignore", "list"])

        assert result.exit_code == 0
        assert "poetry.lock" in result.output
        assert "*.log" in result.output
        assert "build/*" in result.output
        assert "3 pattern" in result.output

    def test_shows_empty_message(self, mocker, temp_dir):
        """Test message when no patterns configured."""
        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.cli.get_ignore_patterns", return_value=[])

        result = runner.invoke(app, ["ignore", "list"])

        assert result.exit_code == 0
        assert "no patterns" in result.output.lower()

    def test_handles_git_error(self, mocker):
        """Test handling of git error."""
        from hunknote.git_ctx import GitError

        mocker.patch("hunknote.cli.get_repo_root", side_effect=GitError("not a repo"))

        result = runner.invoke(app, ["ignore", "list"])

        assert result.exit_code == 1
        assert "error" in result.output.lower()


class TestIgnoreAddCommand:
    """Tests for hunknote ignore add command."""

    def test_adds_pattern(self, mocker, temp_dir):
        """Test adding a pattern."""
        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.cli.get_ignore_patterns", return_value=[])
        mock_add = mocker.patch("hunknote.cli.add_ignore_pattern")

        result = runner.invoke(app, ["ignore", "add", "*.log"])

        assert result.exit_code == 0
        assert "Added" in result.output
        assert "*.log" in result.output
        mock_add.assert_called_once_with(temp_dir, "*.log")

    def test_existing_pattern_message(self, mocker, temp_dir):
        """Test message when pattern already exists."""
        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.cli.get_ignore_patterns", return_value=["*.log"])

        result = runner.invoke(app, ["ignore", "add", "*.log"])

        assert result.exit_code == 0
        assert "already exists" in result.output.lower()

    def test_handles_git_error(self, mocker):
        """Test handling of git error."""
        from hunknote.git_ctx import GitError

        mocker.patch("hunknote.cli.get_repo_root", side_effect=GitError("not a repo"))

        result = runner.invoke(app, ["ignore", "add", "*.log"])

        assert result.exit_code == 1


class TestIgnoreRemoveCommand:
    """Tests for hunknote ignore remove command."""

    def test_removes_pattern(self, mocker, temp_dir):
        """Test removing a pattern."""
        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.cli.remove_ignore_pattern", return_value=True)

        result = runner.invoke(app, ["ignore", "remove", "*.log"])

        assert result.exit_code == 0
        assert "Removed" in result.output
        assert "*.log" in result.output

    def test_pattern_not_found(self, mocker, temp_dir):
        """Test message when pattern not found."""
        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.cli.remove_ignore_pattern", return_value=False)

        result = runner.invoke(app, ["ignore", "remove", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_handles_git_error(self, mocker):
        """Test handling of git error."""
        from hunknote.git_ctx import GitError

        mocker.patch("hunknote.cli.get_repo_root", side_effect=GitError("not a repo"))

        result = runner.invoke(app, ["ignore", "remove", "*.log"])

        assert result.exit_code == 1


class TestMainCommand:
    """Tests for main hunknote command."""

    def test_shows_help(self):
        """Test that help is displayed."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "AI-powered" in result.output
        assert "--edit" in result.output
        assert "--commit" in result.output

    def test_no_staged_changes_error(self, mocker, temp_dir):
        """Test error when no staged changes."""
        from hunknote.git_ctx import NoStagedChangesError

        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mocker.patch(
            "hunknote.cli.build_context_bundle",
            side_effect=NoStagedChangesError("No staged changes")
        )

        result = runner.invoke(app, [])

        assert result.exit_code == 1
        # Check for informative message
        assert "stage" in result.output.lower() or "nothing" in result.output.lower()

    def test_missing_api_key_error(self, mocker, temp_dir):
        """Test error when API key is missing."""
        from hunknote.llm.base import MissingAPIKeyError

        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.cli.build_context_bundle", return_value="context")
        mocker.patch("hunknote.cli.compute_context_hash", return_value="hash")
        mocker.patch("hunknote.cli.get_status", return_value="## main")
        mocker.patch("hunknote.cli.extract_staged_files", return_value=["file.py"])
        mocker.patch("hunknote.cli.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.cli.get_diff_preview", return_value="preview")
        mocker.patch("hunknote.cli.is_cache_valid", return_value=False)
        mocker.patch(
            "hunknote.cli.generate_commit_json",
            side_effect=MissingAPIKeyError("ANTHROPIC_API_KEY not set")
        )

        result = runner.invoke(app, [])

        assert result.exit_code == 1
        assert "API" in result.output or "key" in result.output.lower()

    def test_uses_cached_message(self, mocker, temp_dir):
        """Test that cached message is used when valid."""
        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.cli.build_context_bundle", return_value="context")
        mocker.patch("hunknote.cli.compute_context_hash", return_value="hash")
        mocker.patch("hunknote.cli.get_status", return_value="## main")
        mocker.patch("hunknote.cli.extract_staged_files", return_value=["file.py"])
        mocker.patch("hunknote.cli.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.cli.get_diff_preview", return_value="preview")
        mocker.patch("hunknote.cli.is_cache_valid", return_value=True)
        mocker.patch("hunknote.cli.load_cached_message", return_value="Cached message\n\n- Bullet")
        mocker.patch("hunknote.cli.load_cache_metadata", return_value=MagicMock())
        mocker.patch("hunknote.cli.get_message_file", return_value=temp_dir / "msg.txt")

        result = runner.invoke(app, [])

        assert result.exit_code == 0
        assert "cached" in result.output.lower() or "Cached message" in result.output

    def test_regenerate_flag_bypasses_cache(self, mocker, temp_dir):
        """Test that --regenerate flag bypasses cache."""
        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.cli.build_context_bundle", return_value="context")
        mocker.patch("hunknote.cli.compute_context_hash", return_value="hash")
        mocker.patch("hunknote.cli.get_status", return_value="## main")
        mocker.patch("hunknote.cli.extract_staged_files", return_value=["file.py"])
        mocker.patch("hunknote.cli.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.cli.get_diff_preview", return_value="preview")
        mock_is_valid = mocker.patch("hunknote.cli.is_cache_valid", return_value=True)

        from hunknote.formatters import CommitMessageJSON
        from hunknote.llm.base import LLMResult

        mock_result = LLMResult(
            commit_json=CommitMessageJSON(title="New message", body_bullets=["Change"]),
            model="test",
            input_tokens=100,
            output_tokens=50,
        )
        mocker.patch("hunknote.cli.generate_commit_json", return_value=mock_result)
        mocker.patch("hunknote.cli.save_cache")
        mocker.patch("hunknote.cli.load_cache_metadata", return_value=MagicMock())
        mocker.patch("hunknote.cli.get_message_file", return_value=temp_dir / "msg.txt")

        result = runner.invoke(app, ["--regenerate"])

        # With --regenerate, is_cache_valid should not determine behavior
        # (the cache_valid should be False due to regenerate flag)
        assert "Generating" in result.output or "New message" in result.output


class TestHelperFunctions:
    """Tests for CLI helper functions."""

    def test_generate_message_diff_same(self):
        """Test diff of identical messages."""
        from hunknote.cli import _generate_message_diff

        original = "Same message"
        current = "Same message"

        diff = _generate_message_diff(original, current)

        # Should have no diff lines (or empty)
        assert "+" not in diff or "-" not in diff

    def test_generate_message_diff_different(self):
        """Test diff of different messages."""
        from hunknote.cli import _generate_message_diff

        original = "Original message"
        current = "Modified message"

        diff = _generate_message_diff(original, current)

        assert len(diff) > 0
        # Should show changes
        assert "-" in diff or "+" in diff

    def test_find_editor_returns_list(self, mocker):
        """Test that _find_editor returns a list."""
        from hunknote.cli import _find_editor

        mocker.patch("shutil.which", return_value="/usr/bin/nano")

        editor = _find_editor()

        assert isinstance(editor, list)
        assert len(editor) > 0


class TestConfigShowCommand:
    """Tests for hunknote config show command."""

    def test_shows_configuration(self, mocker):
        """Test showing current configuration."""
        mocker.patch("hunknote.cli.global_config.is_configured", return_value=True)
        mocker.patch(
            "hunknote.cli.global_config.load_global_config",
            return_value={
                "provider": "google",
                "model": "gemini-2.0-flash",
                "max_tokens": 1500,
                "temperature": 0.3,
            }
        )
        mocker.patch("hunknote.cli.global_config.get_credential", return_value="test-api-key-12345")

        result = runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        assert "google" in result.output
        assert "gemini-2.0-flash" in result.output

    def test_shows_not_configured_message(self, mocker):
        """Test message when not configured."""
        mocker.patch("hunknote.cli.global_config.is_configured", return_value=False)

        result = runner.invoke(app, ["config", "show"])

        assert result.exit_code == 0
        assert "No configuration found" in result.output or "hunknote init" in result.output


class TestConfigListProvidersCommand:
    """Tests for hunknote config list-providers command."""

    def test_lists_all_providers(self):
        """Test listing all providers."""
        result = runner.invoke(app, ["config", "list-providers"])

        assert result.exit_code == 0
        assert "anthropic" in result.output
        assert "openai" in result.output
        assert "google" in result.output
        assert "mistral" in result.output
        assert "cohere" in result.output
        assert "groq" in result.output
        assert "openrouter" in result.output


class TestConfigListModelsCommand:
    """Tests for hunknote config list-models command."""

    def test_lists_models_for_provider(self):
        """Test listing models for a specific provider."""
        result = runner.invoke(app, ["config", "list-models", "google"])

        assert result.exit_code == 0
        assert "gemini" in result.output

    def test_lists_all_models_when_no_provider(self):
        """Test listing all models when no provider specified."""
        result = runner.invoke(app, ["config", "list-models"])

        assert result.exit_code == 0
        # Should contain models from multiple providers
        assert "claude" in result.output or "anthropic" in result.output
        assert "gemini" in result.output or "google" in result.output

    def test_invalid_provider_error(self):
        """Test error for invalid provider."""
        result = runner.invoke(app, ["config", "list-models", "invalid-provider"])

        assert result.exit_code == 1
        assert "Invalid provider" in result.output or "invalid" in result.output.lower()


class TestConfigSetKeyCommand:
    """Tests for hunknote config set-key command."""

    def test_sets_api_key(self, mocker):
        """Test setting an API key."""
        mocker.patch("hunknote.cli.global_config.ensure_global_config_dir")
        mock_save = mocker.patch("hunknote.cli.global_config.save_credential")

        result = runner.invoke(app, ["config", "set-key", "google"], input="test-api-key\n")

        assert result.exit_code == 0
        assert "saved" in result.output.lower() or "✓" in result.output
        mock_save.assert_called_once()

    def test_invalid_provider_error(self):
        """Test error for invalid provider."""
        result = runner.invoke(app, ["config", "set-key", "invalid-provider"], input="key\n")

        assert result.exit_code == 1
        assert "Invalid provider" in result.output or "invalid" in result.output.lower()


class TestConfigSetProviderCommand:
    """Tests for hunknote config set-provider command."""

    def test_sets_provider_with_model_option(self, mocker):
        """Test setting provider with model specified."""
        mock_set = mocker.patch("hunknote.cli.global_config.set_provider_and_model")

        result = runner.invoke(app, ["config", "set-provider", "anthropic", "--model", "claude-sonnet-4-20250514"])

        assert result.exit_code == 0
        assert "anthropic" in result.output.lower()
        mock_set.assert_called_once()

    def test_invalid_provider_error(self):
        """Test error for invalid provider."""
        result = runner.invoke(app, ["config", "set-provider", "invalid-provider"])

        assert result.exit_code == 1
        assert "Invalid provider" in result.output or "invalid" in result.output.lower()


class TestInitCommand:
    """Tests for hunknote init command."""

    def test_init_shows_welcome(self, mocker):
        """Test that init shows welcome message."""
        mocker.patch("hunknote.cli.global_config.is_configured", return_value=False)
        mocker.patch("hunknote.cli.global_config.set_provider_and_model")
        mocker.patch("hunknote.cli.global_config.save_credential")

        # Simulate user input: provider 3 (Google), model 1, API key
        result = runner.invoke(app, ["init"], input="3\n1\ntest-api-key\n")

        assert "Welcome" in result.output or "hunknote" in result.output

    def test_init_aborts_if_configured_and_user_declines(self, mocker):
        """Test init aborts when config exists and user declines overwrite."""
        mocker.patch("hunknote.cli.global_config.is_configured", return_value=True)

        # User says "n" to overwrite
        result = runner.invoke(app, ["init"], input="n\n")

        assert result.exit_code == 0
        assert "Keeping existing" in result.output or "existing" in result.output.lower()


class TestDebugFlag:
    """Tests for the --debug flag."""

    def test_debug_flag_shows_metadata(self, mocker, temp_dir):
        """Test that --debug flag shows cache metadata."""
        from hunknote.cache import CacheMetadata

        mock_metadata = CacheMetadata(
            context_hash="abc123",
            generated_at="2026-02-14T12:00:00Z",
            model="gemini-2.0-flash",
            input_tokens=500,
            output_tokens=100,
            staged_files=["file1.py", "file2.py"],
            original_message="Test message",
            diff_preview="diff preview here",
        )

        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.cli.build_context_bundle", return_value="context")
        mocker.patch("hunknote.cli.compute_context_hash", return_value="hash")
        mocker.patch("hunknote.cli.get_status", return_value="## main")
        mocker.patch("hunknote.cli.extract_staged_files", return_value=["file.py"])
        mocker.patch("hunknote.cli.get_staged_diff", return_value="diff")
        mocker.patch("hunknote.cli.get_diff_preview", return_value="preview")
        mocker.patch("hunknote.cli.is_cache_valid", return_value=True)
        mocker.patch("hunknote.cli.load_cached_message", return_value="Cached message")
        mocker.patch("hunknote.cli.load_cache_metadata", return_value=mock_metadata)
        mocker.patch("hunknote.cli.get_message_file", return_value=temp_dir / "msg.txt")

        result = runner.invoke(app, ["--debug"])

        assert result.exit_code == 0
        assert "DEBUG" in result.output or "gemini" in result.output.lower()

