"""Cache file path utilities for hunknote.

Contains functions for getting paths to cache files:
- get_cache_dir: Get the .hunknote directory
- get_message_file: Get path to cached message file
- get_hash_file: Get path to context hash file
- get_metadata_file: Get path to metadata JSON file
- get_raw_json_file: Get path to raw LLM response file
- get_compose_hash_file: Get path to compose hash file
- get_compose_plan_file: Get path to compose plan file
- get_compose_metadata_file: Get path to compose metadata file
- get_compose_hunk_ids_file: Get path to compose hunk IDs file
"""

from pathlib import Path


def get_cache_dir(repo_root: Path) -> Path:
    """Return the .hunknote directory, creating it if needed.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to the .hunknote cache directory.
    """
    cache_dir = repo_root / ".hunknote"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir


def get_message_file(repo_root: Path) -> Path:
    """Return path to the cached message file.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to hunknote_message.txt.
    """
    return get_cache_dir(repo_root) / "hunknote_message.txt"


def get_hash_file(repo_root: Path) -> Path:
    """Return path to the context hash file.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to hunknote_context_hash.txt.
    """
    return get_cache_dir(repo_root) / "hunknote_context_hash.txt"


def get_metadata_file(repo_root: Path) -> Path:
    """Return path to the metadata JSON file.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to hunknote_metadata.json.
    """
    return get_cache_dir(repo_root) / "hunknote_metadata.json"


def get_raw_json_file(repo_root: Path) -> Path:
    """Return path to the raw LLM JSON response file.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to hunknote_llm_response.json.
    """
    return get_cache_dir(repo_root) / "hunknote_llm_response.json"


# ============================================================================
# Compose Cache Paths
# ============================================================================


def get_compose_hash_file(repo_root: Path) -> Path:
    """Return path to the compose context hash file.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to hunknote_compose_hash.txt.
    """
    return get_cache_dir(repo_root) / "hunknote_compose_hash.txt"


def get_compose_plan_file(repo_root: Path) -> Path:
    """Return path to the cached compose plan JSON file.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to hunknote_compose_plan.json.
    """
    return get_cache_dir(repo_root) / "hunknote_compose_plan.json"


def get_compose_metadata_file(repo_root: Path) -> Path:
    """Return path to the compose metadata JSON file.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to hunknote_compose_metadata.json.
    """
    return get_cache_dir(repo_root) / "hunknote_compose_metadata.json"


def get_compose_hunk_ids_file(repo_root: Path) -> Path:
    """Return path to the compose hunk IDs JSON file.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to hunknote_hunk_ids.json.
    """
    return get_cache_dir(repo_root) / "hunknote_hunk_ids.json"

