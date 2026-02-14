"""Tests for hunknote.global_config module."""

import yaml
from pathlib import Path

from hunknote.global_config import (
    get_global_config_dir,
    ensure_global_config_dir,
    get_config_file_path,
    get_credentials_file_path,
    load_global_config,
    save_global_config,
    load_credentials,
    save_credential,
    get_credential,
    get_active_provider,
    get_active_model,
    set_provider_and_model,
    get_editor_preference,
    set_editor_preference,
    get_default_ignore_patterns,
    set_default_ignore_patterns,
    get_max_tokens,
    get_temperature,
    is_configured,
)
from hunknote.config import LLMProvider


class TestGlobalConfigDir:
    """Tests for global config directory functions."""

    def test_get_global_config_dir_returns_path(self):
        """Test that get_global_config_dir returns a Path."""
        result = get_global_config_dir()
        assert isinstance(result, Path)
        assert ".hunknote" in str(result)

    def test_ensure_global_config_dir_creates_directory(self, temp_dir, mocker):
        """Test that ensure_global_config_dir creates the directory."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = ensure_global_config_dir()

        assert mock_dir.exists()
        assert result == mock_dir


class TestConfigFilePaths:
    """Tests for config file path functions."""

    def test_get_config_file_path_returns_yaml(self, mocker, temp_dir):
        """Test that config file path ends with config.yaml."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = get_config_file_path()

        assert result.name == "config.yaml"
        assert ".hunknote" in str(result)

    def test_get_credentials_file_path_returns_credentials(self, mocker, temp_dir):
        """Test that credentials file path ends with credentials."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = get_credentials_file_path()

        assert result.name == "credentials"


class TestLoadSaveGlobalConfig:
    """Tests for loading and saving global config."""

    def test_load_global_config_returns_empty_if_missing(self, mocker, temp_dir):
        """Test that load returns empty dict if file doesn't exist."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = load_global_config()

        assert result == {}

    def test_load_global_config_returns_content(self, mocker, temp_dir):
        """Test loading existing config."""
        mock_dir = temp_dir / ".hunknote"
        mock_dir.mkdir(parents=True)
        config_file = mock_dir / "config.yaml"
        config_file.write_text("provider: google\nmodel: gemini-2.0-flash\n")
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = load_global_config()

        assert result["provider"] == "google"
        assert result["model"] == "gemini-2.0-flash"

    def test_save_global_config_creates_file(self, mocker, temp_dir):
        """Test saving config creates the file."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        config = {"provider": "anthropic", "model": "claude-3-5-sonnet-latest"}
        save_global_config(config)

        config_file = mock_dir / "config.yaml"
        assert config_file.exists()
        content = yaml.safe_load(config_file.read_text())
        assert content["provider"] == "anthropic"


class TestCredentials:
    """Tests for credentials management."""

    def test_load_credentials_returns_empty_if_missing(self, mocker, temp_dir):
        """Test load returns empty dict if no credentials file."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = load_credentials()

        assert result == {}

    def test_load_credentials_parses_file(self, mocker, temp_dir):
        """Test loading credentials from file."""
        mock_dir = temp_dir / ".hunknote"
        mock_dir.mkdir(parents=True)
        creds_file = mock_dir / "credentials"
        creds_file.write_text("GOOGLE_API_KEY=test-key-123\nANTHROPIC_API_KEY=other-key\n")
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = load_credentials()

        assert result["GOOGLE_API_KEY"] == "test-key-123"
        assert result["ANTHROPIC_API_KEY"] == "other-key"

    def test_load_credentials_ignores_comments(self, mocker, temp_dir):
        """Test that comments are ignored."""
        mock_dir = temp_dir / ".hunknote"
        mock_dir.mkdir(parents=True)
        creds_file = mock_dir / "credentials"
        creds_file.write_text("# This is a comment\nGOOGLE_API_KEY=key\n")
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = load_credentials()

        assert "# This is a comment" not in result
        assert result["GOOGLE_API_KEY"] == "key"

    def test_save_credential_creates_file(self, mocker, temp_dir):
        """Test saving a credential creates/updates the file."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        save_credential("TEST_API_KEY", "test-value-123")

        creds_file = mock_dir / "credentials"
        assert creds_file.exists()
        content = creds_file.read_text()
        assert "TEST_API_KEY=test-value-123" in content

    def test_get_credential_returns_value(self, mocker, temp_dir):
        """Test getting a specific credential."""
        mock_dir = temp_dir / ".hunknote"
        mock_dir.mkdir(parents=True)
        creds_file = mock_dir / "credentials"
        creds_file.write_text("GOOGLE_API_KEY=my-google-key\n")
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = get_credential("GOOGLE_API_KEY")

        assert result == "my-google-key"

    def test_get_credential_returns_none_if_missing(self, mocker, temp_dir):
        """Test getting a missing credential returns None."""
        mock_dir = temp_dir / ".hunknote"
        mock_dir.mkdir(parents=True)
        creds_file = mock_dir / "credentials"
        creds_file.write_text("OTHER_KEY=value\n")
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = get_credential("GOOGLE_API_KEY")

        assert result is None


class TestProviderAndModel:
    """Tests for provider and model functions."""

    def test_get_active_provider_returns_enum(self, mocker, temp_dir):
        """Test getting active provider returns LLMProvider enum."""
        mock_dir = temp_dir / ".hunknote"
        mock_dir.mkdir(parents=True)
        config_file = mock_dir / "config.yaml"
        config_file.write_text("provider: google\n")
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = get_active_provider()

        assert result == LLMProvider.GOOGLE

    def test_get_active_provider_returns_none_if_missing(self, mocker, temp_dir):
        """Test returns None if no provider configured."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = get_active_provider()

        assert result is None

    def test_get_active_model_returns_string(self, mocker, temp_dir):
        """Test getting active model returns string."""
        mock_dir = temp_dir / ".hunknote"
        mock_dir.mkdir(parents=True)
        config_file = mock_dir / "config.yaml"
        config_file.write_text("model: gemini-2.0-flash\n")
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = get_active_model()

        assert result == "gemini-2.0-flash"

    def test_set_provider_and_model_saves_config(self, mocker, temp_dir):
        """Test setting provider and model."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        set_provider_and_model(LLMProvider.ANTHROPIC, "claude-3-5-sonnet-latest")

        config = load_global_config()
        assert config["provider"] == "anthropic"
        assert config["model"] == "claude-3-5-sonnet-latest"


class TestEditorPreference:
    """Tests for editor preference functions."""

    def test_get_editor_preference_returns_value(self, mocker, temp_dir):
        """Test getting editor preference."""
        mock_dir = temp_dir / ".hunknote"
        mock_dir.mkdir(parents=True)
        config_file = mock_dir / "config.yaml"
        config_file.write_text("editor: vim\n")
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = get_editor_preference()

        assert result == "vim"

    def test_set_editor_preference_saves_config(self, mocker, temp_dir):
        """Test setting editor preference."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        set_editor_preference("nano")

        config = load_global_config()
        assert config["editor"] == "nano"


class TestIgnorePatterns:
    """Tests for default ignore pattern functions."""

    def test_get_default_ignore_patterns_returns_list(self, mocker, temp_dir):
        """Test getting default ignore patterns."""
        mock_dir = temp_dir / ".hunknote"
        mock_dir.mkdir(parents=True)
        config_file = mock_dir / "config.yaml"
        config_file.write_text("default_ignore:\n  - poetry.lock\n  - '*.log'\n")
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = get_default_ignore_patterns()

        assert "poetry.lock" in result
        assert "*.log" in result

    def test_get_default_ignore_patterns_returns_empty_list(self, mocker, temp_dir):
        """Test returns empty list if not configured."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = get_default_ignore_patterns()

        assert result == []

    def test_set_default_ignore_patterns_saves_config(self, mocker, temp_dir):
        """Test setting default ignore patterns."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        set_default_ignore_patterns(["*.log", "build/*"])

        config = load_global_config()
        assert "*.log" in config["default_ignore"]
        assert "build/*" in config["default_ignore"]


class TestTokensAndTemperature:
    """Tests for max_tokens and temperature functions."""

    def test_get_max_tokens_returns_value(self, mocker, temp_dir):
        """Test getting max_tokens."""
        mock_dir = temp_dir / ".hunknote"
        mock_dir.mkdir(parents=True)
        config_file = mock_dir / "config.yaml"
        config_file.write_text("max_tokens: 2000\n")
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = get_max_tokens()

        assert result == 2000

    def test_get_temperature_returns_value(self, mocker, temp_dir):
        """Test getting temperature."""
        mock_dir = temp_dir / ".hunknote"
        mock_dir.mkdir(parents=True)
        config_file = mock_dir / "config.yaml"
        config_file.write_text("temperature: 0.5\n")
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = get_temperature()

        assert result == 0.5


class TestIsConfigured:
    """Tests for is_configured function."""

    def test_is_configured_returns_false_if_no_config(self, mocker, temp_dir):
        """Test returns False if config doesn't exist."""
        mock_dir = temp_dir / ".hunknote"
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = is_configured()

        assert result is False

    def test_is_configured_returns_true_if_config_exists(self, mocker, temp_dir):
        """Test returns True if config exists."""
        mock_dir = temp_dir / ".hunknote"
        mock_dir.mkdir(parents=True)
        config_file = mock_dir / "config.yaml"
        config_file.write_text("provider: google\n")
        mocker.patch("hunknote.global_config._CONFIG_DIR", mock_dir)

        result = is_configured()

        assert result is True

