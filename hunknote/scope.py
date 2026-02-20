"""Scope inference for hunknote.

Provides deterministic scope inference from staged files to generate
accurate commit message scopes like feat(api), fix(ui), etc.

Supports multiple strategies:
- monorepo: Infer scope from package/app directories
- path-prefix: Use most common path segment
- mapping: Explicit path-to-scope mapping
- none: Disable scope inference
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from collections import Counter


class ScopeStrategy(Enum):
    """Available scope inference strategies."""

    MONOREPO = "monorepo"
    PATH_PREFIX = "path-prefix"
    MAPPING = "mapping"
    NONE = "none"
    AUTO = "auto"  # Try all strategies in order


# Default stop words to exclude from path-based scope inference
DEFAULT_STOP_WORDS = {
    "src",
    "lib",
    "libs",
    "source",
    "sources",
    "tests",
    "test",
    "spec",
    "specs",
    "__tests__",
    "__pycache__",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "out",
    "target",
    "bin",
    "obj",
    "pkg",
    "cmd",
    "internal",
    "public",
    "private",
    "static",
    "assets",
    "resources",
    "main",
    "index",
    "app",  # Often too generic
    "common",
    "shared",
    "utils",
    "util",
    "helpers",
    "helper",
}

# Default monorepo root directories
DEFAULT_MONOREPO_ROOTS = [
    "packages/",
    "apps/",
    "libs/",
    "modules/",
    "services/",
    "plugins/",
    "workspaces/",
]


@dataclass
class ScopeConfig:
    """Configuration for scope inference."""

    enabled: bool = True
    strategy: ScopeStrategy = ScopeStrategy.AUTO
    min_files: int = 1  # Minimum files to consider a cluster valid
    max_depth: int = 2  # How deep into paths to look for scope
    dominant_threshold: float = 0.6  # Fraction required for dominant scope

    # Explicit path-to-scope mapping
    mapping: dict[str, str] = field(default_factory=dict)

    # Monorepo configuration
    monorepo_roots: list[str] = field(default_factory=lambda: DEFAULT_MONOREPO_ROOTS.copy())

    # Stop words to exclude from path-based inference
    stop_words: set[str] = field(default_factory=lambda: DEFAULT_STOP_WORDS.copy())

    # Special handling for docs/tests only changes
    docs_scope: Optional[str] = "docs"  # Scope for docs-only changes (None to skip)
    tests_scope: Optional[str] = None  # Scope for tests-only changes (None to infer from path)


@dataclass
class ScopeResult:
    """Result of scope inference."""

    scope: Optional[str]
    confidence: float  # 0.0 to 1.0
    strategy_used: Optional[ScopeStrategy]
    candidates: list[tuple[str, int]]  # List of (scope, file_count) candidates
    reason: str  # Human-readable explanation


def normalize_path(path: str) -> str:
    """Normalize a file path for consistent processing.

    Args:
        path: The file path to normalize.

    Returns:
        Normalized path with forward slashes.
    """
    return path.replace("\\", "/").strip("/")


def get_path_segments(path: str, max_depth: int = 2) -> list[str]:
    """Extract path segments up to max_depth.

    Args:
        path: The file path.
        max_depth: Maximum number of segments to return.

    Returns:
        List of path segments.
    """
    normalized = normalize_path(path)
    parts = normalized.split("/")
    # Exclude the filename (last part)
    dir_parts = parts[:-1] if len(parts) > 1 else []
    return dir_parts[:max_depth]


def is_docs_file(path: str) -> bool:
    """Check if a file is a documentation file.

    Args:
        path: The file path.

    Returns:
        True if the file is a documentation file.
    """
    normalized = normalize_path(path).lower()

    # Check extension
    doc_extensions = {".md", ".rst", ".txt", ".adoc", ".asciidoc", ".mdx"}
    if any(normalized.endswith(ext) for ext in doc_extensions):
        return True

    # Check directory
    doc_dirs = {"docs", "doc", "documentation", "wiki"}
    parts = normalized.split("/")
    return any(part in doc_dirs for part in parts)


def is_test_file(path: str) -> bool:
    """Check if a file is a test file.

    Args:
        path: The file path.

    Returns:
        True if the file is a test file.
    """
    normalized = normalize_path(path).lower()

    # Check patterns
    test_patterns = [
        "test_",
        "_test.",
        ".test.",
        "tests/",
        "test/",
        "spec/",
        "specs/",
        "__tests__/",
        ".spec.",
        "_spec.",
    ]
    return any(pattern in normalized for pattern in test_patterns)


def infer_scope_from_mapping(
    files: list[str],
    mapping: dict[str, str],
) -> Optional[ScopeResult]:
    """Infer scope using explicit path mapping.

    Args:
        files: List of staged file paths.
        mapping: Dictionary mapping path prefixes to scopes.

    Returns:
        ScopeResult if a mapping matches, None otherwise.
    """
    if not mapping:
        return None

    scope_counts: Counter[str] = Counter()

    for file_path in files:
        normalized = normalize_path(file_path)
        for prefix, scope in mapping.items():
            norm_prefix = normalize_path(prefix)
            if normalized.startswith(norm_prefix):
                scope_counts[scope] += 1
                break  # Use first matching prefix

    if not scope_counts:
        return None

    # Get the most common scope
    most_common = scope_counts.most_common()
    top_scope, top_count = most_common[0]

    confidence = top_count / len(files) if files else 0.0

    return ScopeResult(
        scope=top_scope,
        confidence=confidence,
        strategy_used=ScopeStrategy.MAPPING,
        candidates=most_common,
        reason=f"Matched {top_count}/{len(files)} files via mapping",
    )


def infer_scope_from_monorepo(
    files: list[str],
    monorepo_roots: list[str],
) -> Optional[ScopeResult]:
    """Infer scope from monorepo package/app structure.

    Args:
        files: List of staged file paths.
        monorepo_roots: List of monorepo root directories.

    Returns:
        ScopeResult if monorepo structure found, None otherwise.
    """
    scope_counts: Counter[str] = Counter()

    for file_path in files:
        normalized = normalize_path(file_path)

        for root in monorepo_roots:
            norm_root = normalize_path(root)
            if not norm_root.endswith("/"):
                norm_root += "/"

            if normalized.startswith(norm_root):
                # Extract package name (first segment after root)
                remainder = normalized[len(norm_root):]
                if "/" in remainder:
                    package_name = remainder.split("/")[0]
                    if package_name:
                        scope_counts[package_name] += 1
                        break

    if not scope_counts:
        return None

    most_common = scope_counts.most_common()
    top_scope, top_count = most_common[0]

    confidence = top_count / len(files) if files else 0.0

    return ScopeResult(
        scope=top_scope,
        confidence=confidence,
        strategy_used=ScopeStrategy.MONOREPO,
        candidates=most_common,
        reason=f"Monorepo package '{top_scope}' covers {top_count}/{len(files)} files",
    )


def infer_scope_from_path_prefix(
    files: list[str],
    max_depth: int = 2,
    stop_words: set[str] | None = None,
) -> Optional[ScopeResult]:
    """Infer scope from the most common path segment.

    Args:
        files: List of staged file paths.
        max_depth: Maximum path depth to consider.
        stop_words: Set of segments to ignore.

    Returns:
        ScopeResult based on common path segments.
    """
    if stop_words is None:
        stop_words = DEFAULT_STOP_WORDS

    segment_counts: Counter[str] = Counter()

    for file_path in files:
        segments = get_path_segments(file_path, max_depth)
        # Filter out stop words and add remaining segments
        valid_segments = [s for s in segments if s.lower() not in stop_words and len(s) > 1]
        if valid_segments:
            # Use the deepest valid segment (most specific)
            segment_counts[valid_segments[-1]] += 1

    if not segment_counts:
        return None

    most_common = segment_counts.most_common()
    top_scope, top_count = most_common[0]

    confidence = top_count / len(files) if files else 0.0

    return ScopeResult(
        scope=top_scope,
        confidence=confidence,
        strategy_used=ScopeStrategy.PATH_PREFIX,
        candidates=most_common,
        reason=f"Path segment '{top_scope}' appears in {top_count}/{len(files)} files",
    )


def infer_scope(
    files: list[str],
    config: ScopeConfig | None = None,
) -> ScopeResult:
    """Infer scope from staged files using configured strategy.

    Args:
        files: List of staged file paths.
        config: Scope inference configuration.

    Returns:
        ScopeResult with inferred scope or None scope.
    """
    if config is None:
        config = ScopeConfig()

    if not config.enabled:
        return ScopeResult(
            scope=None,
            confidence=1.0,
            strategy_used=ScopeStrategy.NONE,
            candidates=[],
            reason="Scope inference disabled",
        )

    if not files:
        return ScopeResult(
            scope=None,
            confidence=1.0,
            strategy_used=None,
            candidates=[],
            reason="No files to analyze",
        )

    # Check for special cases first
    # All docs files
    if config.docs_scope and all(is_docs_file(f) for f in files):
        return ScopeResult(
            scope=config.docs_scope,
            confidence=1.0,
            strategy_used=ScopeStrategy.AUTO,
            candidates=[(config.docs_scope, len(files))],
            reason="All files are documentation",
        )

    # All test files - try to infer from test paths
    all_tests = all(is_test_file(f) for f in files)
    if all_tests and config.tests_scope:
        return ScopeResult(
            scope=config.tests_scope,
            confidence=1.0,
            strategy_used=ScopeStrategy.AUTO,
            candidates=[(config.tests_scope, len(files))],
            reason="All files are tests",
        )

    # Apply strategy
    result = None

    if config.strategy == ScopeStrategy.NONE:
        return ScopeResult(
            scope=None,
            confidence=1.0,
            strategy_used=ScopeStrategy.NONE,
            candidates=[],
            reason="Scope strategy set to none",
        )

    if config.strategy == ScopeStrategy.MAPPING:
        result = infer_scope_from_mapping(files, config.mapping)

    elif config.strategy == ScopeStrategy.MONOREPO:
        result = infer_scope_from_monorepo(files, config.monorepo_roots)

    elif config.strategy == ScopeStrategy.PATH_PREFIX:
        result = infer_scope_from_path_prefix(files, config.max_depth, config.stop_words)

    elif config.strategy == ScopeStrategy.AUTO:
        # Try strategies in order: mapping -> monorepo -> path-prefix
        if config.mapping:
            result = infer_scope_from_mapping(files, config.mapping)

        if not result or result.confidence < config.dominant_threshold:
            monorepo_result = infer_scope_from_monorepo(files, config.monorepo_roots)
            if monorepo_result and (not result or monorepo_result.confidence > result.confidence):
                result = monorepo_result

        if not result or result.confidence < config.dominant_threshold:
            path_result = infer_scope_from_path_prefix(files, config.max_depth, config.stop_words)
            if path_result and (not result or path_result.confidence > result.confidence):
                result = path_result

    # Apply confidence threshold
    if result:
        if result.confidence >= config.dominant_threshold:
            return result
        elif len(result.candidates) == 1:
            # Single candidate, use it even if below threshold
            return result
        else:
            # Mixed changes, prefer no scope to avoid wrong scope
            return ScopeResult(
                scope=None,
                confidence=result.confidence,
                strategy_used=result.strategy_used,
                candidates=result.candidates,
                reason=f"Mixed changes across scopes (confidence {result.confidence:.0%} < {config.dominant_threshold:.0%} threshold)",
            )

    return ScopeResult(
        scope=None,
        confidence=0.0,
        strategy_used=None,
        candidates=[],
        reason="Could not determine scope from file paths",
    )


def load_scope_config_from_dict(config_dict: dict) -> ScopeConfig:
    """Load ScopeConfig from a configuration dictionary.

    Args:
        config_dict: Dictionary with scope configuration.

    Returns:
        ScopeConfig instance.
    """
    scope_section = config_dict.get("scope", {})

    # Parse strategy
    strategy_str = scope_section.get("strategy", "auto")
    try:
        strategy = ScopeStrategy(strategy_str)
    except ValueError:
        strategy = ScopeStrategy.AUTO

    # Parse stop words
    stop_words = scope_section.get("stop_words", None)
    if stop_words is None:
        stop_words = DEFAULT_STOP_WORDS.copy()
    else:
        stop_words = set(stop_words)

    return ScopeConfig(
        enabled=scope_section.get("enabled", True),
        strategy=strategy,
        min_files=scope_section.get("min_files", 1),
        max_depth=scope_section.get("max_depth", 2),
        dominant_threshold=scope_section.get("dominant_threshold", 0.6),
        mapping=scope_section.get("mapping", {}),
        monorepo_roots=scope_section.get("monorepo_roots", DEFAULT_MONOREPO_ROOTS.copy()),
        stop_words=stop_words,
        docs_scope=scope_section.get("docs_scope", "docs"),
        tests_scope=scope_section.get("tests_scope", None),
    )


def scope_config_to_dict(config: ScopeConfig) -> dict:
    """Convert ScopeConfig to a dictionary for saving.

    Args:
        config: ScopeConfig instance.

    Returns:
        Dictionary representation.
    """
    return {
        "scope": {
            "enabled": config.enabled,
            "strategy": config.strategy.value,
            "min_files": config.min_files,
            "max_depth": config.max_depth,
            "dominant_threshold": config.dominant_threshold,
            "mapping": config.mapping,
            "monorepo_roots": config.monorepo_roots,
            "docs_scope": config.docs_scope,
            "tests_scope": config.tests_scope,
        }
    }

