"""Cache module for hunknote.

This package provides caching utilities to prevent redundant LLM API calls:
- models: CacheMetadata, ComposeCacheMetadata data models
- paths: Functions for getting cache file paths
- utils: Utility functions (hash computation, file extraction, diff preview)
- message: Commit message cache operations
- compose: Compose plan cache operations
"""

# Models
from hunknote.cache.models import (
    CacheMetadata,
    ComposeCacheMetadata,
)

# Path utilities
from hunknote.cache.paths import (
    get_cache_dir,
    get_compose_hash_file,
    get_compose_hunk_ids_file,
    get_compose_metadata_file,
    get_compose_plan_file,
    get_hash_file,
    get_message_file,
    get_metadata_file,
    get_raw_json_file,
)

# General utilities
from hunknote.cache.utils import (
    compute_context_hash,
    extract_staged_files,
    get_diff_preview,
)

# Message cache operations
from hunknote.cache.message import (
    invalidate_cache,
    is_cache_valid,
    load_cache_metadata,
    load_cached_message,
    load_raw_json_response,
    save_cache,
    update_message_cache,
    update_metadata_overrides,
)

# Compose cache operations
from hunknote.cache.compose import (
    invalidate_compose_cache,
    is_compose_cache_valid,
    load_compose_hunk_ids,
    load_compose_metadata,
    load_compose_plan,
    save_compose_cache,
    save_compose_hunk_ids,
)


__all__ = [
    # Models
    "CacheMetadata",
    "ComposeCacheMetadata",
    # Path utilities
    "get_cache_dir",
    "get_compose_hash_file",
    "get_compose_hunk_ids_file",
    "get_compose_metadata_file",
    "get_compose_plan_file",
    "get_hash_file",
    "get_message_file",
    "get_metadata_file",
    "get_raw_json_file",
    # General utilities
    "compute_context_hash",
    "extract_staged_files",
    "get_diff_preview",
    # Message cache operations
    "invalidate_cache",
    "is_cache_valid",
    "load_cache_metadata",
    "load_cached_message",
    "load_raw_json_response",
    "save_cache",
    "update_message_cache",
    "update_metadata_overrides",
    # Compose cache operations
    "invalidate_compose_cache",
    "is_compose_cache_valid",
    "load_compose_hunk_ids",
    "load_compose_metadata",
    "load_compose_plan",
    "save_compose_cache",
    "save_compose_hunk_ids",
]

