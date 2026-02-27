"""Cache data models for hunknote.

Contains Pydantic models for cache metadata:
- CacheMetadata: Metadata for commit message cache
- ComposeCacheMetadata: Metadata for compose plan cache
"""

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


class ComposeCacheMetadata(BaseModel):
    """Metadata stored alongside the cached compose plan."""

    context_hash: str
    generated_at: str  # ISO format timestamp
    model: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0
    changed_files: list[str]
    total_hunks: int
    num_commits: int
    style: str
    max_commits: int
    # File relationships text (Strategy 2 output for debugging)
    file_relationships_text: Optional[str] = None
    # Retry statistics (for debugging purposes)
    retry_count: int = 0
    retry_stats: Optional[list[dict]] = None  # Per-retry token usage

