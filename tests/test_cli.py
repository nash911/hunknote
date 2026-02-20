"""Tests for hunknote.cli module."""

from unittest.mock import MagicMock

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
        assert "commit" in result.output  # commit is now a subcommand

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
        mocker.patch("hunknote.cli.is_cache_valid", return_value=True)

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


class TestStyleListCommand:
    """Tests for hunknote style list command."""

    def test_lists_all_profiles(self, mocker):
        """Test listing all style profiles."""
        from hunknote.git_ctx import GitError
        mocker.patch("hunknote.cli.get_repo_root", side_effect=GitError("not a repo"))
        mocker.patch("hunknote.cli.global_config.get_style_config", return_value={})

        result = runner.invoke(app, ["style", "list"])

        assert result.exit_code == 0
        assert "default" in result.output
        assert "conventional" in result.output
        assert "ticket" in result.output
        assert "kernel" in result.output

    def test_shows_active_profile(self, mocker):
        """Test that active profile is marked."""
        from hunknote.git_ctx import GitError
        mocker.patch("hunknote.cli.get_repo_root", side_effect=GitError("not a repo"))
        mocker.patch("hunknote.cli.global_config.get_style_config", return_value={"profile": "conventional"})

        result = runner.invoke(app, ["style", "list"])

        assert result.exit_code == 0
        assert "conventional" in result.output
        assert "active" in result.output.lower()


class TestStyleShowCommand:
    """Tests for hunknote style show command."""

    def test_shows_profile_details(self, mocker):
        """Test showing profile details."""
        from hunknote.git_ctx import GitError
        mocker.patch("hunknote.cli.get_repo_root", side_effect=GitError("not a repo"))
        mocker.patch("hunknote.cli.global_config.get_style_profile", return_value="default")

        result = runner.invoke(app, ["style", "show", "conventional"])

        assert result.exit_code == 0
        assert "conventional" in result.output.lower()
        assert "Format" in result.output
        assert "Example" in result.output

    def test_invalid_profile_error(self):
        """Test error for invalid profile."""
        result = runner.invoke(app, ["style", "show", "invalid-profile"])

        assert result.exit_code == 1
        assert "Invalid profile" in result.output or "invalid" in result.output.lower()


class TestStyleSetCommand:
    """Tests for hunknote style set command."""

    def test_sets_global_profile(self, mocker):
        """Test setting global style profile."""
        mock_set = mocker.patch("hunknote.cli.global_config.set_style_profile")

        result = runner.invoke(app, ["style", "set", "conventional"])

        assert result.exit_code == 0
        assert "conventional" in result.output
        mock_set.assert_called_once_with("conventional")

    def test_sets_repo_profile(self, mocker, temp_dir):
        """Test setting repo style profile."""
        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mock_set = mocker.patch("hunknote.cli.set_repo_style_profile")

        result = runner.invoke(app, ["style", "set", "ticket", "--repo"])

        assert result.exit_code == 0
        assert "ticket" in result.output
        mock_set.assert_called_once_with(temp_dir, "ticket")

    def test_invalid_profile_error(self):
        """Test error for invalid profile."""
        result = runner.invoke(app, ["style", "set", "invalid-profile"])

        assert result.exit_code == 1
        assert "Invalid profile" in result.output or "invalid" in result.output.lower()


class TestStyleFlags:
    """Tests for style-related CLI flags."""

    def test_style_flag_in_help(self):
        """Test that --style flag appears in help."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "--style" in result.output

    def test_scope_flag_in_help(self):
        """Test that --scope flag appears in help."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "--scope" in result.output

    def test_ticket_flag_in_help(self):
        """Test that --ticket flag appears in help."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "--ticket" in result.output

    def test_no_scope_flag_in_help(self):
        """Test that --no-scope flag appears in help."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "--no-scope" in result.output

    def test_invalid_style_flag_error(self, mocker, temp_dir):
        """Test error for invalid --style flag value."""
        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)

        result = runner.invoke(app, ["--style", "invalid-style"])

        assert result.exit_code == 1
        assert "Invalid style" in result.output or "invalid" in result.output.lower()


class TestCommitSubcommand:
    """Tests for commit subcommand."""

    def test_commit_in_main_help(self):
        """Test that commit subcommand appears in main help."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "commit" in result.output

    def test_commit_help(self):
        """Test that commit subcommand has help."""
        result = runner.invoke(app, ["commit", "--help"])

        assert result.exit_code == 0
        assert "Commit staged changes" in result.output

    def test_yes_flag_in_commit_help(self):
        """Test that --yes flag appears in commit help."""
        result = runner.invoke(app, ["commit", "--help"])

        assert result.exit_code == 0
        assert "--yes" in result.output
        assert "-y" in result.output

    def test_commit_requires_cached_message(self, mocker, temp_dir):
        """Test that commit requires a cached message."""
        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)
        mocker.patch("hunknote.cli.load_cache_metadata", return_value=None)
        mocker.patch("hunknote.cli.load_cached_message", return_value=None)

        result = runner.invoke(app, ["commit"])

        assert result.exit_code == 1
        assert "No cached commit message" in result.output


class TestIntentOptions:
    """Tests for --intent and --intent-file CLI options."""

    def test_intent_flag_in_help(self):
        """Test that --intent flag appears in help."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "--intent" in result.output

    def test_intent_file_flag_in_help(self):
        """Test that --intent-file flag appears in help."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "--intent-file" in result.output

    def test_intent_file_not_found_error(self, mocker, temp_dir):
        """Test error when intent file does not exist."""
        mocker.patch("hunknote.cli.get_repo_root", return_value=temp_dir)

        result = runner.invoke(app, ["--intent-file", "/nonexistent/file.txt"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "error" in result.output.lower()


class TestIntentProcessing:
    """Tests for intent processing helper functions."""

    def test_process_intent_options_with_intent_only(self):
        """Test processing --intent option only."""
        from hunknote.cli import _process_intent_options

        result = _process_intent_options("Fix the bug in login", None)
        assert result == "Fix the bug in login"

    def test_process_intent_options_with_intent_file_only(self, temp_dir):
        """Test processing --intent-file option only."""
        from hunknote.cli import _process_intent_options

        intent_file = temp_dir / "intent.txt"
        intent_file.write_text("This change improves performance")

        result = _process_intent_options(None, intent_file)
        assert result == "This change improves performance"

    def test_process_intent_options_both_combined(self, temp_dir):
        """Test combining --intent and --intent-file with blank line."""
        from hunknote.cli import _process_intent_options

        intent_file = temp_dir / "intent.txt"
        intent_file.write_text("Additional context from file")

        result = _process_intent_options("Primary intent", intent_file)
        assert result == "Primary intent\n\nAdditional context from file"

    def test_process_intent_options_empty_intent_ignored(self):
        """Test that whitespace-only intent is treated as not provided."""
        from hunknote.cli import _process_intent_options

        result = _process_intent_options("   ", None)
        assert result is None

    def test_process_intent_options_none_when_nothing_provided(self):
        """Test that None is returned when no intent is provided."""
        from hunknote.cli import _process_intent_options

        result = _process_intent_options(None, None)
        assert result is None

    def test_compute_intent_fingerprint_returns_12_chars(self):
        """Test that fingerprint is 12 characters."""
        from hunknote.cli import _compute_intent_fingerprint

        fingerprint = _compute_intent_fingerprint("Some intent text")
        assert fingerprint is not None
        assert len(fingerprint) == 12

    def test_compute_intent_fingerprint_none_for_no_content(self):
        """Test that fingerprint is None when no content."""
        from hunknote.cli import _compute_intent_fingerprint

        assert _compute_intent_fingerprint(None) is None
        assert _compute_intent_fingerprint("") is None

    def test_compute_intent_fingerprint_different_for_different_content(self):
        """Test that different intents produce different fingerprints."""
        from hunknote.cli import _compute_intent_fingerprint

        fp1 = _compute_intent_fingerprint("Intent A")
        fp2 = _compute_intent_fingerprint("Intent B")
        assert fp1 != fp2

    def test_inject_intent_into_context(self):
        """Test that intent is injected into context bundle."""
        from hunknote.cli import _inject_intent_into_context

        context = """[BRANCH]
main

[FILE_CHANGES]
Modified files:
  ~ file.py

[LAST_5_COMMITS]
- Previous commit

[STAGED_DIFF]
diff content"""

        result = _inject_intent_into_context(context, "This is the intent")

        assert "[INTENT]" in result
        assert "This is the intent" in result
        # Intent should be before LAST_5_COMMITS
        intent_pos = result.find("[INTENT]")
        commits_pos = result.find("[LAST_5_COMMITS]")
        assert intent_pos < commits_pos

    def test_inject_intent_preserves_original_sections(self):
        """Test that all original sections are preserved."""
        from hunknote.cli import _inject_intent_into_context

        context = """[BRANCH]
main

[FILE_CHANGES]
Modified files

[LAST_5_COMMITS]
- Commit

[STAGED_DIFF]
diff"""

        result = _inject_intent_into_context(context, "Intent text")

        assert "[BRANCH]" in result
        assert "[FILE_CHANGES]" in result
        assert "[LAST_5_COMMITS]" in result
        assert "[STAGED_DIFF]" in result
        assert "[INTENT]" in result

