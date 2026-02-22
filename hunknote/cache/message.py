"""Commit message cache operations for hunknote.

Contains functions for caching commit messages:
- is_cache_valid: Check if cache is valid for current context
- save_cache: Save generated message and metadata to cache
- update_message_cache: Update cached message without changing metadata
- load_cached_message: Load cached message
- load_raw_json_response: Load raw LLM JSON response
- load_cache_metadata: Load cache metadata
- invalidate_cache: Remove all cache files
- update_metadata_overrides: Update rendering overrides in metadata
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hunknote.cache.models import CacheMetadata
from hunknote.cache.paths import (
    get_hash_file,
    get_message_file,
    get_metadata_file,
    get_raw_json_file,
)


def is_cache_valid(repo_root: Path, current_hash: str) -> bool:
    """Check if cached message is still valid for the current context.

    Args:
        repo_root: The root directory of the git repository.
        current_hash: The hash of the current context bundle.

    Returns:
        True if cache is valid, False otherwise.
    """
    hash_file = get_hash_file(repo_root)
    message_file = get_message_file(repo_root)

    if not hash_file.exists() or not message_file.exists():
        return False

    stored_hash = hash_file.read_text().strip()
    return stored_hash == current_hash


def save_cache(
    repo_root: Path,
    context_hash: str,
    message: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    staged_files: list[str],
    diff_preview: str,
    raw_response: str = "",
    input_chars: int = 0,
    prompt_chars: int = 0,
    output_chars: int = 0,
    scope_override: Optional[str] = None,
    ticket_override: Optional[str] = None,
    no_scope_override: bool = False,
) -> None:
    """Save the generated message and its metadata to cache.

    Args:
        repo_root: The root directory of the git repository.
        context_hash: SHA256 hash of the context bundle.
        message: The rendered commit message.
        model: The LLM model used for generation.
        input_tokens: Number of input tokens used.
        output_tokens: Number of output tokens generated.
        staged_files: List of staged file paths.
        diff_preview: Preview of the staged diff.
        raw_response: Raw JSON response from the LLM.
        input_chars: Number of characters in context bundle.
        prompt_chars: Number of characters in full prompt.
        output_chars: Number of characters in LLM response.
        scope_override: CLI scope override.
        ticket_override: CLI ticket override.
        no_scope_override: Whether scope is disabled.
    """
    # Save hash
    get_hash_file(repo_root).write_text(context_hash)

    # Save message
    get_message_file(repo_root).write_text(message)

    # Save raw LLM response
    if raw_response:
        get_raw_json_file(repo_root).write_text(raw_response)

    # Save metadata (including rendering overrides)
    metadata = CacheMetadata(
        context_hash=context_hash,
        generated_at=datetime.now(timezone.utc).isoformat(),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        staged_files=staged_files,
        original_message=message,
        diff_preview=diff_preview,
        input_chars=input_chars,
        prompt_chars=prompt_chars,
        output_chars=output_chars,
        scope_override=scope_override,
        ticket_override=ticket_override,
        no_scope_override=no_scope_override,
    )
    get_metadata_file(repo_root).write_text(metadata.model_dump_json(indent=2))


def update_message_cache(repo_root: Path, message: str) -> None:
    """Update the cached message without changing metadata.

    Used when user edits the message - keeps original_message intact.

    Args:
        repo_root: The root directory of the git repository.
        message: The updated commit message.
    """
    get_message_file(repo_root).write_text(message)


def load_cached_message(repo_root: Path) -> Optional[str]:
    """Load the cached message.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        The cached commit message string, or None if not found.
    """
    message_file = get_message_file(repo_root)
    if not message_file.exists():
        return None
    return message_file.read_text()


def load_raw_json_response(repo_root: Path) -> Optional[str]:
    """Load the raw LLM JSON response from cache.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        The raw JSON response string or None if not found.
    """
    raw_json_file = get_raw_json_file(repo_root)
    if raw_json_file.exists():
        return raw_json_file.read_text()
    return None


def load_cache_metadata(repo_root: Path) -> Optional[CacheMetadata]:
    """Load the cache metadata.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        CacheMetadata object or None if not found.
    """
    metadata_file = get_metadata_file(repo_root)
    if not metadata_file.exists():
        return None

    try:
        data = json.loads(metadata_file.read_text())
        return CacheMetadata(**data)
    except (json.JSONDecodeError, Exception):
        return None


def invalidate_cache(repo_root: Path) -> None:
    """Remove all cache files.

    Call this after a successful commit.

    Args:
        repo_root: The root directory of the git repository.
    """
    for file_getter in [get_hash_file, get_message_file, get_metadata_file, get_raw_json_file]:
        file_path = file_getter(repo_root)
        if file_path.exists():
            file_path.unlink()


def update_metadata_overrides(
    repo_root: Path,
    scope_override: Optional[str] = None,
    ticket_override: Optional[str] = None,
    no_scope_override: bool = False,
) -> None:
    """Update rendering overrides in the cached metadata.

    Args:
        repo_root: The root directory of the git repository.
        scope_override: CLI scope override.
        ticket_override: CLI ticket override.
        no_scope_override: Whether scope is disabled.
    """
    metadata = load_cache_metadata(repo_root)
    if metadata:
        metadata.scope_override = scope_override
        metadata.ticket_override = ticket_override
        metadata.no_scope_override = no_scope_override
        get_metadata_file(repo_root).write_text(metadata.model_dump_json(indent=2))

