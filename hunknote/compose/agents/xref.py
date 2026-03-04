"""Language-specific import → definition cross-reference builders.

Given extracted symbol data (imports_added, defines, exports_added) from
HunkSymbols, these functions match imports in one hunk to definitions in
another hunk.  Each language handler understands the module/import naming
conventions of its language and can split qualified import paths to find
matching definitions.

The general pattern is:
    1. Build a symbol-to-hunk index from all ``defines`` and ``exports_added``.
    2. Build a file-path-to-hunk index for new files.
    3. For each hunk's ``imports_added``, run the appropriate language
       handler to extract candidate symbol names and module paths.
    4. Match against the indexes to produce cross-reference lines.
"""

from __future__ import annotations

import os
from typing import Callable

from hunknote.compose.models import FileDiff, HunkSymbols


# ────────────────────────────────────────────────────────────
# Types used across handlers
# ────────────────────────────────────────────────────────────

# (hunk_id, file_path)
_Provider = tuple[str, str]

# Each handler returns a list of candidate symbol names that
# should be looked up in the symbol-to-hunk index.
# It may also return module-path prefixes that should be matched
# against the new-file module index.


def build_import_xref(
    symbol_analyses: dict[str, HunkSymbols],
    file_diffs: list[FileDiff],
) -> str:
    """Build a cross-reference of imports → definitions across hunks.

    Language-agnostic dispatcher: routes each hunk's imports to the
    appropriate language handler to extract candidate names, then
    matches them against the symbol-to-hunk index.

    Args:
        symbol_analyses: Per-hunk symbol data.
        file_diffs: File diffs (used to identify new files).

    Returns:
        Multi-line text with cross-reference entries.
    """
    # ── 1. Build symbol → defining-hunk index (by simple name) ──
    symbol_to_hunk: dict[str, list[_Provider]] = {}
    for hid, sym in symbol_analyses.items():
        for s in sym.defines:
            symbol_to_hunk.setdefault(s, []).append((hid, sym.file_path))
        for s in sym.exports_added:
            symbol_to_hunk.setdefault(s, []).append((hid, sym.file_path))

    # ── 2. Build file-path → hunk IDs for new files ──
    new_file_hunks: dict[str, list[str]] = {}
    for fd in file_diffs:
        if fd.is_new_file:
            for h in fd.hunks:
                new_file_hunks.setdefault(fd.file_path, []).append(h.id)

    # ── 3. Build module-path → new-file mapping ──
    file_to_modules: dict[str, list[str]] = {}
    for fp in new_file_hunks:
        file_to_modules[fp] = _file_path_to_modules(fp)

    # ── 4. Match imports ──
    lines: list[str] = []
    seen_edges: set[tuple[str, str]] = set()

    for hid, sym in symbol_analyses.items():
        lang = (sym.language or "").lower()
        handler = _get_handler(lang)

        for imp in sym.imports_added:
            candidates = handler(imp)

            # Match by symbol name
            for candidate in candidates:
                if candidate in symbol_to_hunk:
                    for provider_hid, provider_file in symbol_to_hunk[candidate]:
                        if provider_hid != hid:
                            edge_key = (hid, provider_hid)
                            if edge_key not in seen_edges:
                                seen_edges.add(edge_key)
                                lines.append(
                                    f"  {hid} imports '{candidate}' ← "
                                    f"defined by {provider_hid} ({provider_file})"
                                )

            # Match by module path (for new-file imports)
            for fp, modules in file_to_modules.items():
                if fp == sym.file_path:
                    continue

                # Also check if the import path (or its stripped form)
                # appears as a suffix of the file path.
                # This handles C/C++ includes like "mylib/utils.h"
                # matching file "include/mylib/utils.h"
                imp_stripped = imp.strip("<>\"' ")
                fp_norm = fp.replace("\\", "/")

                # Direct file-path suffix match
                if fp_norm.endswith(imp_stripped):
                    for provider_hid in new_file_hunks[fp]:
                        if provider_hid != hid:
                            edge_key = (hid, provider_hid)
                            if edge_key not in seen_edges:
                                seen_edges.add(edge_key)
                                lines.append(
                                    f"  {hid} imports from new file '{fp}' ← "
                                    f"created by {provider_hid}"
                                )
                    continue  # Already matched this file

                for mod in modules:
                    # Direct prefix match: import starts with module path
                    # e.g., "hunknote.compose.agents.base.BaseSubAgent"
                    #        starts with "hunknote.compose.agents.base"
                    # Suffix match: module path is a suffix of the import
                    # e.g., import "myapp/pkg/handler" ends with "pkg/handler"
                    #        (Go module prefix not in file path)
                    matched = (
                        imp.startswith(mod)
                        or imp == mod
                        or imp.endswith("/" + mod)
                        or imp.endswith("." + mod)
                    )
                    if matched:
                        for provider_hid in new_file_hunks[fp]:
                            if provider_hid != hid:
                                edge_key = (hid, provider_hid)
                                if edge_key not in seen_edges:
                                    seen_edges.add(edge_key)
                                    lines.append(
                                        f"  {hid} imports from new file '{fp}' ← "
                                        f"created by {provider_hid}"
                                    )
                        break  # One match per file is enough

    if not lines:
        return (
            "  No direct cross-references found in symbol data. "
            "Use tools to inspect further."
        )
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────
# Module-path generation from file paths
# ────────────────────────────────────────────────────────────

def _file_path_to_modules(file_path: str) -> list[str]:
    """Convert a file path to possible module import paths.

    Returns multiple forms so that different language conventions
    can be matched.

    Examples:
        "src/models.py"             → ["src.models", "src/models"]
        "src/utils/index.ts"        → ["src/utils/index", "src/utils", "@/utils"]
        "pkg/handler.go"            → ["pkg/handler", "pkg"]
        "src/lib.rs"                → ["src"]
        "include/mylib/utils.h"     → ["mylib/utils", "include/mylib/utils"]
    """
    modules: list[str] = []
    norm = file_path.replace("\\", "/")

    # Strip common extensions
    base = norm
    for ext in (
        ".py", ".pyi",
        ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
        ".go",
        ".rs",
        ".rb",
        ".java", ".kt", ".kts", ".scala",
        ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
        ".cs",
        ".swift",
        ".lua",
        ".ex", ".exs",
        ".hs",
        ".ml", ".mli",
    ):
        if norm.endswith(ext):
            base = norm[: -len(ext)]
            break

    # Dotted module path (Python, Java, Kotlin, Scala)
    dotted = base.replace("/", ".")
    modules.append(dotted)

    # Slash-based path (Go, TS/JS, C/C++)
    modules.append(base)

    # Parent directory (Go package convention, C/C++ include directory)
    # e.g., "pkg/handler/handler.go" → "pkg/handler" is the Go package
    # e.g., "include/mylib/utils.h" → "mylib/utils" is the include path
    dirpath_full = os.path.dirname(norm)
    if dirpath_full:
        modules.append(dirpath_full)
        modules.append(dirpath_full.replace("/", "."))

    # For index files, also add the directory
    basename = os.path.basename(norm)
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    if stem in ("index", "__init__", "mod", "lib", "main", "package"):
        dirpath = os.path.dirname(base)
        if dirpath:
            modules.append(dirpath)
            modules.append(dirpath.replace("/", "."))

    return modules


# ────────────────────────────────────────────────────────────
# Language handler dispatcher
# ────────────────────────────────────────────────────────────

def _get_handler(language: str) -> Callable[[str], list[str]]:
    """Return the import-candidate extractor for a language."""
    return _HANDLERS.get(language, _handle_fallback)


# Handler type: takes a raw import string, returns candidate names


# ────────────────────────────────────────────────────────────
# Per-language handlers
# ────────────────────────────────────────────────────────────


def _handle_python(imp: str) -> list[str]:
    """Extract candidate names from a Python-style import.

    Examples:
        "hunknote.compose.agents.base.BaseSubAgent" → ["BaseSubAgent", "base"]
        "hunknote.compose.agents.base"              → ["base"]
        "os.path"                                    → ["path"]
        "typing"                                     → ["typing"]
    """
    parts = imp.split(".")
    candidates = [parts[-1]]  # Always include the last segment
    if len(parts) >= 2:
        candidates.append(parts[-2])  # Also the module name
    return candidates


def _handle_typescript(imp: str) -> list[str]:
    """Extract candidate names from a TS/JS-style import.

    Import strings may look like:
        "react"                   → ["react"]
        "@/utils/helpers"         → ["helpers", "utils"]
        "./models/User"           → ["User", "models"]
        "../components/Button"    → ["Button", "components"]
        "lodash/debounce"         → ["debounce"]
    """
    # Strip relative prefix
    clean = imp.lstrip("./").lstrip("@/")
    parts = clean.split("/")
    candidates = [parts[-1]]
    if len(parts) >= 2:
        candidates.append(parts[-2])
    # Also include full path for exact matching
    candidates.append(clean)
    return candidates


def _handle_go(imp: str) -> list[str]:
    """Extract candidate names from a Go import path.

    Go imports are full module paths:
        "fmt"                                → ["fmt"]
        "github.com/user/repo/pkg/handler"   → ["handler", "pkg"]
        "net/http"                            → ["http", "net"]
    """
    parts = imp.split("/")
    candidates = [parts[-1]]
    if len(parts) >= 2:
        candidates.append(parts[-2])
    return candidates


def _handle_rust(imp: str) -> list[str]:
    """Extract candidate names from a Rust use path.

    Rust uses :: separated paths:
        "crate::models::User"        → ["User", "models"]
        "std::collections::HashMap"  → ["HashMap", "collections"]
        "super::utils"               → ["utils"]
    """
    # Handle :: and . separated paths
    if "::" in imp:
        parts = imp.split("::")
    else:
        parts = imp.split(".")
    # Filter out crate/self/super prefixes
    parts = [p for p in parts if p not in ("crate", "self", "super", "")]
    candidates = [parts[-1]] if parts else []
    if len(parts) >= 2:
        candidates.append(parts[-2])
    return candidates


def _handle_ruby(imp: str) -> list[str]:
    """Extract candidate names from a Ruby require path.

    Ruby uses / separated paths:
        "json"              → ["json"]
        "models/user"       → ["user", "models"]
        "active_support/core_ext" → ["core_ext", "active_support"]
    """
    parts = imp.split("/")
    candidates = [parts[-1]]
    if len(parts) >= 2:
        candidates.append(parts[-2])
    return candidates


def _handle_java(imp: str) -> list[str]:
    """Extract candidate names from a Java/Kotlin/Scala import.

    Java uses dot-separated fully qualified names:
        "java.util.List"                    → ["List", "util"]
        "com.example.models.User"           → ["User", "models"]
        "kotlinx.coroutines.flow.Flow"      → ["Flow", "flow"]
    """
    parts = imp.split(".")
    candidates = [parts[-1]]
    if len(parts) >= 2:
        candidates.append(parts[-2])
    return candidates


def _handle_c_cpp(imp: str) -> list[str]:
    """Extract candidate names from a C/C++ #include path.

    Include paths use / and may or may not have extensions:
        "stdio.h"                 → ["stdio"]
        "mylib/utils.h"           → ["utils", "mylib"]
        "boost/algorithm/string"  → ["string", "algorithm"]
        "vector"                  → ["vector"]
    """
    # Strip angle brackets / quotes if present
    clean = imp.strip("<>\"' ")
    # Strip common header extensions
    for ext in (".h", ".hh", ".hpp", ".hxx", ".inc"):
        if clean.endswith(ext):
            clean = clean[: -len(ext)]
            break
    parts = clean.split("/")
    candidates = [parts[-1]]
    if len(parts) >= 2:
        candidates.append(parts[-2])
    return candidates


def _handle_csharp(imp: str) -> list[str]:
    """Extract candidate names from a C# using directive.

    C# uses dot-separated namespaces:
        "System.Collections.Generic" → ["Generic", "Collections"]
        "MyApp.Models"               → ["Models", "MyApp"]
    """
    return _handle_java(imp)  # Same convention


def _handle_swift(imp: str) -> list[str]:
    """Extract candidate names from a Swift import.

    Swift imports are module names:
        "Foundation"    → ["Foundation"]
        "UIKit"         → ["UIKit"]
        "MyModule.Sub"  → ["Sub", "MyModule"]
    """
    parts = imp.split(".")
    candidates = [parts[-1]]
    if len(parts) >= 2:
        candidates.append(parts[-2])
    return candidates


def _handle_fallback(imp: str) -> list[str]:
    """Generic fallback for unknown languages.

    Tries all common separators (., /, ::) and returns the last segments.
    """
    # Try multiple separators
    for sep in ("::", "/", "."):
        if sep in imp:
            parts = imp.split(sep)
            parts = [p for p in parts if p]
            candidates = [parts[-1]] if parts else []
            if len(parts) >= 2:
                candidates.append(parts[-2])
            return candidates
    # Single token
    return [imp] if imp else []


# ────────────────────────────────────────────────────────────
# Handler registry
# ────────────────────────────────────────────────────────────

_HANDLERS: dict[str, Callable[[str], list[str]]] = {
    "python": _handle_python,
    "typescript": _handle_typescript,
    "javascript": _handle_typescript,  # Same conventions
    "tsx": _handle_typescript,
    "jsx": _handle_typescript,
    "go": _handle_go,
    "golang": _handle_go,
    "rust": _handle_rust,
    "ruby": _handle_ruby,
    "java": _handle_java,
    "kotlin": _handle_java,
    "scala": _handle_java,
    "c": _handle_c_cpp,
    "cpp": _handle_c_cpp,
    "c++": _handle_c_cpp,
    "cxx": _handle_c_cpp,
    "objective-c": _handle_c_cpp,
    "c#": _handle_csharp,
    "csharp": _handle_csharp,
    "swift": _handle_swift,
}




