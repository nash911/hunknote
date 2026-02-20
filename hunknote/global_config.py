"""Global configuration management for hunknote.

Handles user-level configuration stored in ~/.hunknote/:
- config.yaml: Provider, model, and preference settings
- credentials: API keys for LLM providers
"""

import os
import stat
from pathlib import Path
from typing import Dict, Optional, Any

import yaml

from hunknote.config import LLMProvider


class GlobalConfigError(Exception):
    """Raised when there's an error with global configuration."""
    pass


_CONFIG_DIR = Path.home() / ".hunknote"


def get_global_config_dir() -> Path:
    """Get the global hunknote configuration directory.

    Returns:
        Path to ~/.hunknote/
    """
    return _CONFIG_DIR


def ensure_global_config_dir() -> Path:
    """Ensure the global config directory exists.

    Returns:
        Path to ~/.hunknote/
    """
    config_dir = get_global_config_dir()
    config_dir.mkdir(exist_ok=True)
    return config_dir


def get_config_file_path() -> Path:
    """Get path to config.yaml file.

    Returns:
        Path to ~/.hunknote/config.yaml
    """
    return get_global_config_dir() / "config.yaml"


def get_credentials_file_path() -> Path:
    """Get path to credentials file.

    Returns:
        Path to ~/.hunknote/credentials
    """
    return get_global_config_dir() / "credentials"


def load_global_config() -> Dict[str, Any]:
    """Load global configuration from ~/.hunknote/config.yaml.

    Returns:
        Dictionary with configuration values. Empty dict if file doesn't exist.
    """
    config_file = get_config_file_path()

    if not config_file.exists():
        return {}

    try:
        with open(config_file, "r") as f:
            config = yaml.safe_load(f) or {}
        return config
    except Exception as e:
        raise GlobalConfigError(f"Failed to load config from {config_file}: {e}")


def save_global_config(config: Dict[str, Any]) -> None:
    """Save global configuration to ~/.hunknote/config.yaml.

    Args:
        config: Configuration dictionary to save.
    """
    ensure_global_config_dir()
    config_file = get_config_file_path()

    try:
        with open(config_file, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise GlobalConfigError(f"Failed to save config to {config_file}: {e}")


def load_credentials() -> Dict[str, str]:
    """Load API keys from ~/.hunknote/credentials.

    Returns:
        Dictionary mapping provider names to API keys.
    """
    credentials_file = get_credentials_file_path()

    if not credentials_file.exists():
        return {}

    credentials = {}

    try:
        with open(credentials_file, "r") as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                # Parse KEY=value format
                if "=" in line:
                    key, value = line.split("=", 1)
                    credentials[key.strip()] = value.strip()

        return credentials
    except Exception as e:
        raise GlobalConfigError(f"Failed to load credentials from {credentials_file}: {e}")


def save_credential(provider_key: str, api_key: str) -> None:
    """Save or update an API key in the credentials file.

    Args:
        provider_key: Environment variable name (e.g., "ANTHROPIC_API_KEY")
        api_key: The API key value.
    """
    ensure_global_config_dir()
    credentials_file = get_credentials_file_path()

    # Load existing credentials
    existing_creds = {}
    if credentials_file.exists():
        try:
            with open(credentials_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        existing_creds[key.strip()] = value.strip()
        except Exception as e:
            raise GlobalConfigError(f"Failed to read existing credentials: {e}")

    # Update the credential
    existing_creds[provider_key] = api_key

    # Write back all credentials
    try:
        with open(credentials_file, "w") as f:
            f.write("# hunknote API credentials\n")
            f.write("# This file stores API keys for LLM providers\n")
            f.write("# Format: PROVIDER_API_KEY=your_key_here\n\n")

            for key, value in existing_creds.items():
                f.write(f"{key}={value}\n")

        # Set secure permissions (owner read/write only)
        os.chmod(credentials_file, stat.S_IRUSR | stat.S_IWUSR)

    except Exception as e:
        raise GlobalConfigError(f"Failed to save credential: {e}")


def get_credential(provider_key: str) -> Optional[str]:
    """Get an API key from credentials file.

    Args:
        provider_key: Environment variable name (e.g., "ANTHROPIC_API_KEY")

    Returns:
        The API key if found, None otherwise.
    """
    credentials = load_credentials()
    return credentials.get(provider_key)


def get_active_provider() -> Optional[LLMProvider]:
    """Get the active LLM provider from global config.

    Returns:
        LLMProvider enum value, or None if not configured.
    """
    config = load_global_config()
    provider_str = config.get("provider")

    if not provider_str:
        return None

    try:
        return LLMProvider(provider_str)
    except ValueError:
        return None


def get_active_model() -> Optional[str]:
    """Get the active model from global config.

    Returns:
        Model name string, or None if not configured.
    """
    config = load_global_config()
    return config.get("model")


def set_provider_and_model(provider: LLMProvider, model: str) -> None:
    """Set the active provider and model in global config.

    Args:
        provider: The LLM provider to use.
        model: The model name to use.
    """
    config = load_global_config()
    config["provider"] = provider.value
    config["model"] = model
    save_global_config(config)


def get_editor_preference() -> Optional[str]:
    """Get the user's preferred editor from global config.

    Returns:
        Editor command string, or None if not set.
    """
    config = load_global_config()
    return config.get("editor")


def set_editor_preference(editor: str) -> None:
    """Set the user's preferred editor in global config.

    Args:
        editor: Editor command (e.g., "gedit", "nano", "vim")
    """
    config = load_global_config()
    config["editor"] = editor
    save_global_config(config)


def get_default_ignore_patterns() -> list:
    """Get default ignore patterns from global config.

    Returns:
        List of ignore patterns, or empty list if not configured.
    """
    config = load_global_config()
    return config.get("default_ignore", [])


def set_default_ignore_patterns(patterns: list) -> None:
    """Set default ignore patterns in global config.

    Args:
        patterns: List of glob patterns to ignore.
    """
    config = load_global_config()
    config["default_ignore"] = patterns
    save_global_config(config)


def get_max_tokens() -> Optional[int]:
    """Get max_tokens setting from global config.

    Returns:
        Max tokens value, or None if not configured.
    """
    config = load_global_config()
    return config.get("max_tokens")


def get_temperature() -> Optional[float]:
    """Get temperature setting from global config.

    Returns:
        Temperature value, or None if not configured.
    """
    config = load_global_config()
    return config.get("temperature")


def get_style_profile() -> Optional[str]:
    """Get the active style profile from global config.

    Returns:
        Style profile name (default, conventional, ticket, kernel), or None.
    """
    config = load_global_config()
    style_section = config.get("style", {})
    return style_section.get("profile")


def set_style_profile(profile: str) -> None:
    """Set the active style profile in global config.

    Args:
        profile: Style profile name (default, conventional, ticket, kernel).
    """
    config = load_global_config()
    if "style" not in config:
        config["style"] = {}
    config["style"]["profile"] = profile
    save_global_config(config)


def get_style_config() -> dict:
    """Get the full style configuration section from global config.

    Returns:
        Dictionary with style configuration.
    """
    config = load_global_config()
    return config.get("style", {})


def set_style_config(style_config: dict) -> None:
    """Set the full style configuration section in global config.

    Args:
        style_config: Dictionary with style configuration.
    """
    config = load_global_config()
    config["style"] = style_config
    save_global_config(config)


def get_scope_config() -> dict:
    """Get the scope configuration section from global config.

    Returns:
        Dictionary with scope configuration.
    """
    config = load_global_config()
    return config.get("scope", {})


def set_scope_config(scope_config: dict) -> None:
    """Set the full scope configuration section in global config.

    Args:
        scope_config: Dictionary with scope configuration.
    """
    config = load_global_config()
    config["scope"] = scope_config
    save_global_config(config)


def initialize_default_config() -> None:
    """Initialize config.yaml with default values if it doesn't exist."""
    config_file = get_config_file_path()

    if config_file.exists():
        return

    ensure_global_config_dir()

    default_config = {
        "provider": "google",
        "model": "gemini-2.0-flash",
        "max_tokens": 1500,
        "temperature": 0.3,
        "editor": "gedit",
        "default_ignore": [
            "poetry.lock",
            "package-lock.json",
            "*.min.js",
            "*.min.css",
        ],
        "style": {
            "profile": "default",
            "include_body": True,
            "max_bullets": 6,
            "wrap_width": 72,
        },
        "scope": {
            "enabled": True,
            "strategy": "auto",
        }
    }

    save_global_config(default_config)


def is_configured() -> bool:
    """Check if hunknote has been configured.

    Returns:
        True if config.yaml exists, False otherwise.
    """
    return get_config_file_path().exists()

