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
    # Character counts (optional for backward compatibility with existing cache)
    input_chars: int = 0  # Characters in context bundle
    prompt_chars: int = 0  # Characters in full prompt (system + user)
    output_chars: int = 0  # Characters in LLM response
    # Rendering overrides (persist with the cached message)
    scope_override: Optional[str] = None  # CLI scope override (--scope)
    ticket_override: Optional[str] = None  # CLI ticket override (--ticket)
    no_scope_override: bool = False  # Whether scope is disabled (--no-scope)


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


# ============================================================================
# Compose Caching
# ============================================================================


class ComposeCacheMetadata(BaseModel):
    """Metadata stored alongside the cached compose plan."""

    context_hash: str
    generated_at: str  # ISO format timestamp
    model: str
    input_tokens: int
    output_tokens: int
    changed_files: list[str]
    total_hunks: int
    num_commits: int
    style: str
    max_commits: int


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
        changed_files=changed_files,
        total_hunks=total_hunks,
        num_commits=num_commits,
        style=style,
        max_commits=max_commits,
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


def get_compose_hunk_ids_file(repo_root: Path) -> Path:
    """Return path to the compose hunk IDs JSON file.

    Args:
        repo_root: The root directory of the git repository.

    Returns:
        Path to hunknote_hunk_ids.json.
    """
    return get_cache_dir(repo_root) / "hunknote_hunk_ids.json"


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
