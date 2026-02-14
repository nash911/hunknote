"""Caching utilities for hunknote to prevent redundant LLM API calls."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class CacheMetadata(BaseModel):
    """Metadata stored alongside the cached commit message."""

    context_hash: str
    generated_at: str  # ISO format timestamp
    model: str
    input_tokens: int
    output_tokens: int
    staged_files: list[str]
    original_message: str
    diff_preview: str


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


def compute_context_hash(context_bundle: str) -> str:
    """Compute SHA256 hash of the context bundle.

    Args:
        context_bundle: The full git context string.

    Returns:
        SHA256 hex digest of the context.
    """
    return hashlib.sha256(context_bundle.encode()).hexdigest()


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
    """
    # Save hash
    get_hash_file(repo_root).write_text(context_hash)

    # Save message
    get_message_file(repo_root).write_text(message)

    # Save metadata
    metadata = CacheMetadata(
        context_hash=context_hash,
        generated_at=datetime.now(timezone.utc).isoformat(),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        staged_files=staged_files,
        original_message=message,
        diff_preview=diff_preview,
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


def load_cached_message(repo_root: Path) -> str:
    """Load the cached message.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        The cached commit message string.
    """
    return get_message_file(repo_root).read_text()


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
    for file_getter in [get_hash_file, get_message_file, get_metadata_file]:
        file_path = file_getter(repo_root)
        if file_path.exists():
            file_path.unlink()


def extract_staged_files(status_output: str) -> list[str]:
    """Extract list of staged files from git status output.

    Args:
        status_output: Output from git status --porcelain=v1 -b

    Returns:
        List of staged file paths.
    """
    staged_files = []
    for line in status_output.split("\n"):
        if not line or line.startswith("##"):
            continue
        # Porcelain format: XY filename
        # X = index status, Y = worktree status
        # If X is not space or ?, file is staged
        if len(line) >= 3:
            index_status = line[0]
            if index_status not in (" ", "?"):
                # Handle renamed files: R  old -> new
                filename = line[3:]
                if " -> " in filename:
                    filename = filename.split(" -> ")[1]
                staged_files.append(filename)
    return staged_files


def get_diff_preview(diff: str, max_chars: int = 500) -> str:
    """Get a preview of the diff, truncated if necessary.

    Args:
        diff: The full staged diff.
        max_chars: Maximum characters for the preview.

    Returns:
        Truncated diff preview.
    """
    if len(diff) <= max_chars:
        return diff
    return diff[:max_chars] + "\n...[truncated]"
