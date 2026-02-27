"""Compose plan cache operations for hunknote.

Contains functions for caching compose plans:
- is_compose_cache_valid: Check if compose cache is valid
- save_compose_cache: Save compose plan and metadata
- load_compose_plan: Load cached compose plan
- load_compose_metadata: Load compose cache metadata
- invalidate_compose_cache: Remove all compose cache files
- save_compose_hunk_ids: Save hunk ID assignments
- load_compose_hunk_ids: Load hunk ID assignments
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hunknote.cache.models import ComposeCacheMetadata
from hunknote.cache.paths import (
    get_compose_hash_file,
    get_compose_hunk_ids_file,
    get_compose_metadata_file,
    get_compose_plan_file,
)


def is_compose_cache_valid(repo_root: Path, current_hash: str) -> bool:
    """Check if cached compose plan is still valid for the current context.

    Args:
        repo_root: The root directory of the git repository.
        current_hash: The hash of the current context (diff + style + max_commits).

    Returns:
        True if cache is valid, False otherwise.
    """
    hash_file = get_compose_hash_file(repo_root)
    plan_file = get_compose_plan_file(repo_root)

    if not hash_file.exists() or not plan_file.exists():
        return False

    stored_hash = hash_file.read_text().strip()
    return stored_hash == current_hash


def save_compose_cache(
    repo_root: Path,
    context_hash: str,
    plan_json: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    changed_files: list[str],
    total_hunks: int,
    num_commits: int,
    style: str,
    max_commits: int,
    file_relationships_text: Optional[str] = None,
    retry_count: int = 0,
    retry_stats: list[dict] | None = None,
    thinking_tokens: int = 0,
) -> None:
    """Save the generated compose plan and its metadata to cache.

    Args:
        repo_root: The root directory of the git repository.
        context_hash: SHA256 hash of the compose context.
        plan_json: The compose plan as JSON string.
        model: The LLM model used for generation.
        input_tokens: Number of input tokens used.
        output_tokens: Number of output tokens generated.
        changed_files: List of changed file paths.
        total_hunks: Total number of hunks in the diff.
        num_commits: Number of commits in the plan.
        style: The style profile used.
        max_commits: Maximum commits setting.
        file_relationships_text: Formatted file relationships text from Strategy 2.
        retry_count: Number of LLM retries performed (0 if none).
        retry_stats: Per-retry statistics [{input_tokens, output_tokens, success}].
        thinking_tokens: Number of internal thinking tokens used (thinking models).
    """
    # Save hash
    get_compose_hash_file(repo_root).write_text(context_hash)

    # Save plan
    get_compose_plan_file(repo_root).write_text(plan_json)

    # Save metadata
    metadata = ComposeCacheMetadata(
        context_hash=context_hash,
        generated_at=datetime.now(timezone.utc).isoformat(),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thinking_tokens=thinking_tokens,
        changed_files=changed_files,
        total_hunks=total_hunks,
        num_commits=num_commits,
        style=style,
        max_commits=max_commits,
        file_relationships_text=file_relationships_text,
        retry_count=retry_count,
        retry_stats=retry_stats,
    )
    get_compose_metadata_file(repo_root).write_text(metadata.model_dump_json(indent=2))


def load_compose_plan(repo_root: Path) -> Optional[str]:
    """Load the cached compose plan JSON.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        The cached compose plan JSON string, or None if not found.
    """
    plan_file = get_compose_plan_file(repo_root)
    if not plan_file.exists():
        return None
    return plan_file.read_text()


def load_compose_metadata(repo_root: Path) -> Optional[ComposeCacheMetadata]:
    """Load the compose cache metadata.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        ComposeCacheMetadata object or None if not found.
    """
    metadata_file = get_compose_metadata_file(repo_root)
    if not metadata_file.exists():
        return None

    try:
        data = json.loads(metadata_file.read_text())
        return ComposeCacheMetadata(**data)
    except (json.JSONDecodeError, Exception):
        return None


def invalidate_compose_cache(repo_root: Path) -> None:
    """Remove all compose cache files.

    Call this after successfully executing a compose plan.

    Args:
        repo_root: The root directory of the git repository.
    """
    for file_getter in [get_compose_hash_file, get_compose_plan_file, get_compose_metadata_file, get_compose_hunk_ids_file]:
        file_path = file_getter(repo_root)
        if file_path.exists():
            file_path.unlink()


def save_compose_hunk_ids(
    repo_root: Path,
    hunk_ids_data: list[dict],
) -> None:
    """Save the hunk IDs with their diffs and assignments to a JSON file.

    Args:
        repo_root: The root directory of the git repository.
        hunk_ids_data: List of hunk data dictionaries.
    """
    get_compose_hunk_ids_file(repo_root).write_text(
        json.dumps(hunk_ids_data, indent=2)
    )


def load_compose_hunk_ids(repo_root: Path) -> Optional[list[dict]]:
    """Load the compose hunk IDs JSON.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        List of hunk data dictionaries, or None if not found.
    """
    hunk_ids_file = get_compose_hunk_ids_file(repo_root)
    if not hunk_ids_file.exists():
        return None
    try:
        return json.loads(hunk_ids_file.read_text())
    except (json.JSONDecodeError, Exception):
        return None

