"""Symbol extraction from hunks for the Compose Agent.

Implements:
- extract_symbols_from_hunk: Extract module-scope symbols from a single hunk
- extract_all_symbols: Extract symbols from all hunks in an inventory
- annotate_large_hunks: Detect and annotate large new-file hunks
"""

from pathlib import Path

from hunknote.compose.extractors import get_extractor
from hunknote.compose.models import (
    FileDiff,
    HunkRef,
    HunkSymbols,
    LargeHunkAnnotation,
)

# Configurable threshold for large-hunk detection
LARGE_HUNK_LINE_THRESHOLD = 50

# Map file extension to language name
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java", ".kt": "kotlin",
    ".rb": "ruby",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".php": "php",
    ".proto": "protobuf",
    ".graphql": "graphql", ".gql": "graphql",
    ".yaml": "yaml", ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".sql": "sql",
}


def _detect_language(file_path: str) -> str:
    """Detect the language from file path extension."""
    ext = Path(file_path).suffix
    return _EXT_TO_LANGUAGE.get(ext, "unknown")


def extract_symbols_from_hunk(hunk: HunkRef) -> HunkSymbols:
    """Extract module-scope symbols from a single hunk.

    Parses the +/- lines (not context lines) to determine what
    the hunk defines, removes, modifies, references, and imports.

    Args:
        hunk: The hunk to analyse.

    Returns:
        HunkSymbols with extracted module-scope symbols.
    """
    added_lines = [
        line[1:] for line in hunk.lines
        if line.startswith("+") and not line.startswith("+++")
    ]
    removed_lines = [
        line[1:] for line in hunk.lines
        if line.startswith("-") and not line.startswith("---")
    ]

    added_code = "\n".join(added_lines)
    removed_code = "\n".join(removed_lines)

    # Get the appropriate language-specific extractor
    extractor = get_extractor(hunk.file_path)

    # Extract symbols from added and removed code
    added = extractor.extract_all(added_code)
    removed = extractor.extract_all(removed_code)

    language = _detect_language(hunk.file_path)

    return HunkSymbols(
        file_path=hunk.file_path,
        language=language,
        defines=added.definitions - removed.definitions,
        removes=removed.definitions - added.definitions,
        modifies=added.definitions & removed.definitions,
        references=added.references,
        imports_added=added.imports - removed.imports,
        imports_removed=removed.imports - added.imports,
        exports_added=added.exports - removed.exports,
        exports_removed=removed.exports - added.exports,
    )


def extract_all_symbols(
    inventory: dict[str, HunkRef],
) -> dict[str, HunkSymbols]:
    """Extract symbols from all hunks in the inventory.

    Args:
        inventory: Dictionary mapping hunk ID to HunkRef.

    Returns:
        Dictionary mapping hunk ID to HunkSymbols.
    """
    return {
        hunk_id: extract_symbols_from_hunk(hunk)
        for hunk_id, hunk in inventory.items()
    }


def annotate_large_hunks(
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
    symbol_analyses: dict[str, HunkSymbols],
    threshold: int = LARGE_HUNK_LINE_THRESHOLD,
) -> dict[str, LargeHunkAnnotation]:
    """Detect and annotate large new-file hunks.

    When a new file is added with many lines, Git treats the entire file
    as a single hunk. This function detects such hunks and provides
    metadata about their internal structure.

    Args:
        inventory: Dictionary mapping hunk ID to HunkRef.
        file_diffs: Parsed file diffs for is_new_file detection.
        symbol_analyses: Pre-computed symbol analyses.
        threshold: Minimum added lines to consider a hunk "large".

    Returns:
        Dictionary mapping hunk ID to LargeHunkAnnotation (only for
        hunks that qualify as large or new-file).
    """
    # Build a lookup for is_new_file
    new_file_paths: set[str] = {
        fd.file_path for fd in file_diffs if fd.is_new_file
    }

    annotations: dict[str, LargeHunkAnnotation] = {}

    for hunk_id, hunk in inventory.items():
        added_line_count = sum(
            1 for line in hunk.lines
            if line.startswith("+") and not line.startswith("+++")
        )

        is_new = hunk.file_path in new_file_paths
        is_large = added_line_count > threshold

        if not is_new and not is_large:
            continue

        symbols = symbol_analyses.get(hunk_id)
        definitions_list = sorted(symbols.defines) if symbols else []
        definitions_count = len(definitions_list)

        # Estimate logical sections by counting distinct definition types
        has_classes = False
        has_functions = False
        has_constants = False
        if symbols:
            for defn in definitions_list:
                if defn[0].isupper() and not defn.isupper():
                    has_classes = True
                elif defn.isupper():
                    has_constants = True
                else:
                    has_functions = True

        section_count = sum([has_classes, has_functions, has_constants])
        has_multiple = section_count > 1

        annotations[hunk_id] = LargeHunkAnnotation(
            is_new_file=is_new,
            is_large_hunk=is_large,
            line_count=added_line_count,
            definitions_count=definitions_count,
            definitions=definitions_list,
            has_multiple_logical_sections=has_multiple,
            estimated_sections=max(1, section_count),
        )

    return annotations

