"""User configuration management for hunknote.

Handles reading and writing the .hunknote/config.yaml file in each repository.

Backward compatibility:
- Falls back to .aicommit/ if .hunknote/ doesn't exist
- Warns users about deprecated paths
"""

import sys
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

# Backward compatibility tracking
_REPO_MIGRATION_WARNED = set()


def _warn_deprecated_repo_path(repo_root: Path) -> None:
    """Warn user about deprecated repo configuration path.

    Args:
        repo_root: The repository root directory.
    """
    repo_key = str(repo_root.absolute())
    if repo_key not in _REPO_MIGRATION_WARNED:
        old_path = repo_root / ".aicommit"
        new_path = repo_root / ".hunknote"
        print(f"\n⚠️  WARNING: Using deprecated repository configuration", file=sys.stderr)
        print(f"   Repo: {repo_root}", file=sys.stderr)
        print(f"   Old: {old_path}", file=sys.stderr)
        print(f"   New: {new_path}", file=sys.stderr)
        print(f"   Run 'hunknote migrate' to update your configuration.", file=sys.stderr)
        print(f"   (This warning will only show once per repo)\n", file=sys.stderr)
        _REPO_MIGRATION_WARNED.add(repo_key)


def get_config_dir(repo_root: Path) -> Path:
    """Get the repository config directory (.hunknote or .aicommit for backward compat).

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to .hunknote/ (or .aicommit/ for backward compatibility)
    """
    new_dir = repo_root / ".hunknote"
    old_dir = repo_root / ".aicommit"

    # If new directory exists, use it
    if new_dir.exists():
        return new_dir

    # If old directory exists but new doesn't, use old and warn
    if old_dir.exists():
        _warn_deprecated_repo_path(repo_root)
        return old_dir

    # Neither exists, return new (will be created when needed)
    return new_dir


def get_config_file(repo_root: Path) -> Path:
    """Return path to the config.yaml file.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to .hunknote/config.yaml (or .aicommit/config.yaml for backward compatibility).
    """
    return get_config_dir(repo_root) / "config.yaml"


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

    # Ensure directory exists
    config_file.parent.mkdir(exist_ok=True)

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
