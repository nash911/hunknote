"""User configuration management for hunknote.

Handles reading and writing the .hunknote/config.yaml file in each repository.
"""

from pathlib import Path

import yaml


# Default configuration values
DEFAULT_CONFIG = {
    "ignore": [
        # Lock files (auto-generated dependency files)
        "poetry.lock",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.lock",
        "Gemfile.lock",
        "composer.lock",
        "go.sum",
        # Build artifacts
        "*.min.js",
        "*.min.css",
        "*.map",
        # Binary and generated files
        "*.pyc",
        "*.pyo",
        "*.so",
        "*.dll",
        "*.exe",
        # IDE and editor files
        ".idea/*",
        ".vscode/*",
        "*.swp",
        "*.swo",
    ],
}


def get_config_dir(repo_root: Path) -> Path:
    """Get the repository config directory (.hunknote).

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to .hunknote/
    """
    return repo_root / ".hunknote"


def get_config_file(repo_root: Path) -> Path:
    """Return path to the config.yaml file, ensuring the directory exists.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to .hunknote/config.yaml.
    """
    config_dir = get_config_dir(repo_root)
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.yaml"


def ensure_config_dir(repo_root: Path) -> Path:
    """Ensure the config directory exists.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to .hunknote/ directory.
    """
    config_dir = get_config_dir(repo_root)
    config_dir.mkdir(exist_ok=True)
    return config_dir


def load_config(repo_root: Path) -> dict:
    """Load the hunknote configuration from config.yaml.

    If the file doesn't exist, creates it with default values.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Configuration dictionary.
    """
    config_file = get_config_file(repo_root)

    if not config_file.exists():
        # Create default config file
        save_config(repo_root, DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        with open(config_file, "r") as f:
            config = yaml.safe_load(f) or {}
        # Merge with defaults for any missing keys
        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = value
        return config
    except (yaml.YAMLError, Exception):
        # If config is corrupted, return defaults
        return DEFAULT_CONFIG.copy()


def save_config(repo_root: Path, config: dict) -> None:
    """Save the configuration to config.yaml.

    Args:
        repo_root: The root directory of the git repository.
        config: Configuration dictionary to save.
    """
    config_file = get_config_file(repo_root)


    with open(config_file, "w") as f:
        yaml.dump(
            config,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )


def get_ignore_patterns(repo_root: Path) -> list[str]:
    """Get the list of ignore patterns from config.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        List of file patterns to ignore in diffs.
    """
    config = load_config(repo_root)
    return config.get("ignore", DEFAULT_CONFIG["ignore"])


def add_ignore_pattern(repo_root: Path, pattern: str) -> None:
    """Add a pattern to the ignore list.

    Args:
        repo_root: The root directory of the git repository.
        pattern: File pattern to add (e.g., "*.log", "build/*").
    """
    config = load_config(repo_root)
    if "ignore" not in config:
        config["ignore"] = []
    if pattern not in config["ignore"]:
        config["ignore"].append(pattern)
        save_config(repo_root, config)


def remove_ignore_pattern(repo_root: Path, pattern: str) -> bool:
    """Remove a pattern from the ignore list.

    Args:
        repo_root: The root directory of the git repository.
        pattern: File pattern to remove.

    Returns:
        True if pattern was found and removed, False otherwise.
    """
    config = load_config(repo_root)
    if "ignore" in config and pattern in config["ignore"]:
        config["ignore"].remove(pattern)
        save_config(repo_root, config)
        return True
    return False


def get_repo_style_config(repo_root: Path) -> dict:
    """Get the style configuration section from repo config.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Dictionary with style configuration, or empty dict.
    """
    config = load_config(repo_root)
    return config.get("style", {})


def set_repo_style_profile(repo_root: Path, profile: str) -> None:
    """Set the style profile in repo config.

    Args:
        repo_root: The root directory of the git repository.
        profile: Style profile name (default, conventional, ticket, kernel).
    """
    config = load_config(repo_root)
    if "style" not in config:
        config["style"] = {}
    config["style"]["profile"] = profile
    save_config(repo_root, config)


def set_repo_style_config(repo_root: Path, style_config: dict) -> None:
    """Set the full style configuration section in repo config.

    Args:
        repo_root: The root directory of the git repository.
        style_config: Dictionary with style configuration.
    """
    config = load_config(repo_root)
    config["style"] = style_config
    save_config(repo_root, config)


def get_repo_scope_config(repo_root: Path) -> dict:
    """Get the scope configuration section from repo config.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Dictionary with scope configuration, or empty dict.
    """
    config = load_config(repo_root)
    return config.get("scope", {})


def set_repo_scope_config(repo_root: Path, scope_config: dict) -> None:
    """Set the full scope configuration section in repo config.

    Args:
        repo_root: The root directory of the git repository.
        scope_config: Dictionary with scope configuration.
    """
    config = load_config(repo_root)
    config["scope"] = scope_config
    save_config(repo_root, config)
