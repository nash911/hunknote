"""Tests for hunknote.user_config module."""

import yaml

from hunknote.user_config import (
    DEFAULT_CONFIG,
    add_ignore_pattern,
    get_config_file,
    get_ignore_patterns,
    load_config,
    remove_ignore_pattern,
    save_config,
)


class TestGetConfigFile:
    """Tests for get_config_file function."""

    def test_returns_correct_path(self, temp_dir):
        """Test that correct config path is returned."""
        config_file = get_config_file(temp_dir)
        assert config_file.name == "config.yaml"
        assert config_file.parent.name == ".hunknote"

    def test_creates_directory(self, temp_dir):
        """Test that .hunknote directory is created."""
        config_file = get_config_file(temp_dir)
        assert config_file.parent.exists()


class TestLoadConfig:
    """Tests for load_config function."""

    def test_creates_default_config_if_missing(self, temp_dir):
        """Test that default config is created if missing."""
        config = load_config(temp_dir)

        # Check config file was created
        config_file = get_config_file(temp_dir)
        assert config_file.exists()

        # Check default ignore patterns
        assert "ignore" in config
        assert "poetry.lock" in config["ignore"]

    def test_loads_existing_config(self, temp_dir):
        """Test loading existing config file."""
        config_file = get_config_file(temp_dir)
        config_file.parent.mkdir(parents=True, exist_ok=True)

        custom_config = {"ignore": ["custom.lock", "*.log"]}
        with open(config_file, "w") as f:
            yaml.dump(custom_config, f)

        config = load_config(temp_dir)
        assert "custom.lock" in config["ignore"]
        assert "*.log" in config["ignore"]

    def test_merges_with_defaults(self, temp_dir):
        """Test that missing keys are filled from defaults."""
        config_file = get_config_file(temp_dir)
        config_file.parent.mkdir(parents=True, exist_ok=True)

        # Config with only some keys
        partial_config = {"other_key": "value"}
        with open(config_file, "w") as f:
            yaml.dump(partial_config, f)

        config = load_config(temp_dir)
        # Should have default ignore patterns added
        assert "ignore" in config
        assert "poetry.lock" in config["ignore"]

    def test_handles_corrupted_config(self, temp_dir):
        """Test handling corrupted config file."""
        config_file = get_config_file(temp_dir)
        config_file.parent.mkdir(parents=True, exist_ok=True)

        # Write invalid YAML
        config_file.write_text("invalid: yaml: content: [")

        config = load_config(temp_dir)
        # Should return defaults
        assert config == DEFAULT_CONFIG

    def test_handles_empty_config(self, temp_dir):
        """Test handling empty config file."""
        config_file = get_config_file(temp_dir)
        config_file.parent.mkdir(parents=True, exist_ok=True)

        config_file.write_text("")

        config = load_config(temp_dir)
        # Should have defaults merged in
        assert "ignore" in config


class TestSaveConfig:
    """Tests for save_config function."""

    def test_saves_config(self, temp_dir):
        """Test saving config file."""
        config = {"ignore": ["test.lock"], "custom": "value"}
        save_config(temp_dir, config)

        config_file = get_config_file(temp_dir)
        assert config_file.exists()

        with open(config_file, "r") as f:
            loaded = yaml.safe_load(f)

        assert loaded["ignore"] == ["test.lock"]
        assert loaded["custom"] == "value"

    def test_creates_directory(self, temp_dir):
        """Test that directory is created if missing."""
        config = {"ignore": []}
        save_config(temp_dir, config)

        assert (temp_dir / ".hunknote").exists()


class TestGetIgnorePatterns:
    """Tests for get_ignore_patterns function."""

    def test_returns_default_patterns(self, temp_dir):
        """Test that default patterns are returned."""
        patterns = get_ignore_patterns(temp_dir)

        assert "poetry.lock" in patterns
        assert "package-lock.json" in patterns
        assert "yarn.lock" in patterns

    def test_returns_custom_patterns(self, temp_dir):
        """Test returning custom patterns."""
        config = {"ignore": ["custom1.lock", "custom2.log"]}
        save_config(temp_dir, config)

        patterns = get_ignore_patterns(temp_dir)
        assert "custom1.lock" in patterns
        assert "custom2.log" in patterns


class TestAddIgnorePattern:
    """Tests for add_ignore_pattern function."""

    def test_adds_pattern(self, temp_dir):
        """Test adding a new pattern."""
        # First load to create defaults
        load_config(temp_dir)

        add_ignore_pattern(temp_dir, "*.log")

        patterns = get_ignore_patterns(temp_dir)
        assert "*.log" in patterns

    def test_does_not_duplicate(self, temp_dir):
        """Test that duplicate patterns are not added."""
        load_config(temp_dir)

        add_ignore_pattern(temp_dir, "poetry.lock")  # Already in defaults

        patterns = get_ignore_patterns(temp_dir)
        # Count occurrences
        count = patterns.count("poetry.lock")
        assert count == 1

    def test_adds_multiple_patterns(self, temp_dir):
        """Test adding multiple patterns."""
        load_config(temp_dir)

        add_ignore_pattern(temp_dir, "*.log")
        add_ignore_pattern(temp_dir, "*.tmp")
        add_ignore_pattern(temp_dir, "build/*")

        patterns = get_ignore_patterns(temp_dir)
        assert "*.log" in patterns
        assert "*.tmp" in patterns
        assert "build/*" in patterns


class TestRemoveIgnorePattern:
    """Tests for remove_ignore_pattern function."""

    def test_removes_pattern(self, temp_dir):
        """Test removing an existing pattern."""
        load_config(temp_dir)

        # Verify pattern exists
        patterns = get_ignore_patterns(temp_dir)
        assert "poetry.lock" in patterns

        # Remove it
        result = remove_ignore_pattern(temp_dir, "poetry.lock")

        assert result is True
        patterns = get_ignore_patterns(temp_dir)
        assert "poetry.lock" not in patterns

    def test_returns_false_for_missing_pattern(self, temp_dir):
        """Test that False is returned for non-existent pattern."""
        load_config(temp_dir)

        result = remove_ignore_pattern(temp_dir, "nonexistent.pattern")

        assert result is False

    def test_removes_custom_pattern(self, temp_dir):
        """Test removing a custom added pattern."""
        load_config(temp_dir)

        add_ignore_pattern(temp_dir, "custom.lock")
        assert "custom.lock" in get_ignore_patterns(temp_dir)

        result = remove_ignore_pattern(temp_dir, "custom.lock")

        assert result is True
        assert "custom.lock" not in get_ignore_patterns(temp_dir)


class TestDefaultConfig:
    """Tests for DEFAULT_CONFIG constant."""

    def test_has_ignore_key(self):
        """Test that DEFAULT_CONFIG has ignore key."""
        assert "ignore" in DEFAULT_CONFIG

    def test_ignore_has_common_lock_files(self):
        """Test that common lock files are in default ignore."""
        ignore = DEFAULT_CONFIG["ignore"]

        assert "poetry.lock" in ignore
        assert "package-lock.json" in ignore
        assert "yarn.lock" in ignore
        assert "Cargo.lock" in ignore
        assert "go.sum" in ignore

    def test_ignore_has_build_artifacts(self):
        """Test that build artifacts are in default ignore."""
        ignore = DEFAULT_CONFIG["ignore"]

        assert "*.min.js" in ignore
        assert "*.min.css" in ignore
