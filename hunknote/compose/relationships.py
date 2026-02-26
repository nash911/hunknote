"""File relationship detection for hunknote compose module.

Contains file-relationship detection for Strategy 2 (Compose Coherence):
- Tiered import extraction (ast for Python, regex for other languages)
- Module-to-file resolution
- Transitive dependency closure
- Path-based heuristic fallbacks
- Formatting relationships for LLM prompts

These utilities detect import dependencies between changed files so the LLM
can group causally dependent hunks into the same commit.
"""

import ast
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ============================================================
# Data Models
# ============================================================

@dataclass
class FileRelationship:
    """A detected dependency relationship between two changed files."""

    source: str       # The file that imports/depends on the target
    target: str       # The file being imported/depended on
    kind: str         # "direct" or "transitive"
    via: Optional[str] = None  # For transitive: the intermediate file


# ============================================================
# Tier 1: Python AST-based import extraction (100% accurate)
# ============================================================

def extract_python_imports(source: str) -> list[str]:
    """Extract all import module paths from Python source using ast.

    Handles:
    - import foo
    - import foo.bar
    - from foo.bar import baz
    - importlib.import_module("foo.bar")  (string literal only)
    - __import__("foo.bar")  (string literal only)

    Args:
        source: Python source code as a string.

    Returns:
        List of dotted module paths (e.g., ["src.master_rl.config", "os"]).
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        # Static imports: import X / from X import Y
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

        # Dynamic imports with string literal arguments
        elif isinstance(node, ast.Call):
            # importlib.import_module("module.path")
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                imports.append(node.args[0].value)
            # __import__("module.path")
            elif (isinstance(node.func, ast.Name)
                  and node.func.id == "__import__"
                  and node.args
                  and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, str)):
                imports.append(node.args[0].value)

    return imports


# ============================================================
# Tier 2: Regex-based import extraction (multi-language)
# ============================================================

# Map of file extension -> list of regex patterns to extract imports.
# Each regex should capture the module/path in group 1.
IMPORT_PATTERNS: dict[str, list[re.Pattern]] = {
    # JavaScript / TypeScript
    ".js": [
        re.compile(r'''(?:import|from)\s+['"]([^'"]+)['"]'''),
        re.compile(r'''require\(\s*['"]([^'"]+)['"]\s*\)'''),
    ],
    ".jsx": [
        re.compile(r'''(?:import|from)\s+['"]([^'"]+)['"]'''),
        re.compile(r'''require\(\s*['"]([^'"]+)['"]\s*\)'''),
    ],
    ".ts": [
        re.compile(r'''(?:import|from)\s+['"]([^'"]+)['"]'''),
        re.compile(r'''require\(\s*['"]([^'"]+)['"]\s*\)'''),
    ],
    ".tsx": [
        re.compile(r'''(?:import|from)\s+['"]([^'"]+)['"]'''),
        re.compile(r'''require\(\s*['"]([^'"]+)['"]\s*\)'''),
    ],
    # Java / Kotlin
    ".java": [
        re.compile(r'^\s*import\s+(?:static\s+)?([\w.]+)', re.MULTILINE),
        re.compile(r'''Class\.forName\(\s*["']([\w.]+)["']\s*\)'''),
        re.compile(r'''ClassLoader.*\.loadClass\(\s*["']([\w.]+)["']\s*\)'''),
    ],
    ".kt": [
        re.compile(r'^\s*import\s+([\w.]+)', re.MULTILINE),
        re.compile(r'''Class\.forName\(\s*["']([\w.]+)["']\s*\)'''),
    ],
    # Go
    ".go": [
        re.compile(r'''"([\w./\-]+)"'''),
    ],
    # Rust
    ".rs": [
        re.compile(r'^\s*(?:use|mod)\s+([\w:]+)', re.MULTILINE),
    ],
    # Ruby
    ".rb": [
        re.compile(r'''^\s*require\s+['"]([^'"]+)['"]''', re.MULTILINE),
        re.compile(r'''^\s*require_relative\s+['"]([^'"]+)['"]''', re.MULTILINE),
        re.compile(r'''^\s*load\s+['"]([^'"]+)['"]''', re.MULTILINE),
    ],
    # C / C++
    ".c": [
        re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]', re.MULTILINE),
    ],
    ".cpp": [
        re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]', re.MULTILINE),
    ],
    ".cc": [
        re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]', re.MULTILINE),
    ],
    ".h": [
        re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]', re.MULTILINE),
    ],
    ".hpp": [
        re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]', re.MULTILINE),
    ],
    # Swift
    ".swift": [
        re.compile(r'^\s*import\s+(\w+)', re.MULTILINE),
    ],
}


def extract_imports_regex(source: str, file_ext: str) -> list[str]:
    """Extract import paths from source code using regex patterns.

    Args:
        source: File source code as a string.
        file_ext: File extension including dot (e.g., ".js", ".java").

    Returns:
        List of imported module/path strings.
    """
    patterns = IMPORT_PATTERNS.get(file_ext, [])
    if not patterns:
        return []

    imports: list[str] = []
    for pattern in patterns:
        imports.extend(pattern.findall(source))
    return imports


# ============================================================
# Module-to-file resolution
# ============================================================

def resolve_module_to_file(
    module_path: str,
    repo_root: Path,
    file_ext: str = ".py",
) -> Optional[str]:
    """Resolve a dotted/path module reference to a file path relative to repo root.

    Tries common resolution strategies:
    - Dotted path → directory separator (Python, Java)
    - Relative path (JS/TS: ./module, ../module)
    - Direct header path (C/C++: #include "path.h")

    Args:
        module_path: The imported module path string.
        repo_root: Absolute path to the repository root.
        file_ext: Extension of the file doing the importing.

    Returns:
        Relative file path from repo root, or None if not resolved.
    """
    # Python / Java: dotted module → path
    if file_ext in (".py", ".java", ".kt"):
        parts = module_path.replace(".", "/")
        candidates = [
            Path(f"{parts}.py"),
            Path(parts) / "__init__.py",
            Path(f"{parts}.java"),
            Path(f"{parts}.kt"),
        ]
        for candidate in candidates:
            if (repo_root / candidate).is_file():
                return str(candidate)
        return None

    # JS/TS: relative paths (./module, ../module)
    if file_ext in (".js", ".jsx", ".ts", ".tsx"):
        # Skip package imports (no . or / prefix)
        if not module_path.startswith((".", "/")):
            return None
        # Try with common extensions
        for ext in ("", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js"):
            candidate = Path(module_path + ext)
            if (repo_root / candidate).is_file():
                return str(candidate)
        return None

    # C/C++: direct header paths
    if file_ext in (".c", ".cpp", ".cc", ".h", ".hpp"):
        candidate = Path(module_path)
        if (repo_root / candidate).is_file():
            return str(candidate)
        return None

    # Go: package paths — resolve to directory
    if file_ext == ".go":
        candidate = Path(module_path)
        if (repo_root / candidate).is_dir():
            return str(candidate)
        return None

    # Ruby: require paths
    if file_ext == ".rb":
        for ext in ("", ".rb"):
            candidate = Path(module_path + ext)
            if (repo_root / candidate).is_file():
                return str(candidate)
        return None

    # Rust: crate::module → src/module.rs
    if file_ext == ".rs":
        # Convert crate::foo::bar → src/foo/bar.rs or src/foo/bar/mod.rs
        parts = module_path.replace("::", "/").replace("crate", "src")
        for suffix in (".rs", "/mod.rs"):
            candidate = Path(parts + suffix)
            if (repo_root / candidate).is_file():
                return str(candidate)
        return None

    return None


# ============================================================
# Tier 3: Path-based heuristic fallbacks
# ============================================================

def detect_path_relationships(changed_files: set[str]) -> list[tuple[str, str]]:
    """Detect file relationships using path-based heuristics.

    Used as a fallback when import extraction is not available or fails.

    Detects:
    - Test file pairing: foo.py ↔ test_foo.py / foo_test.py
    - Mirror paths: src/x/y.py ↔ tests/x/test_y.py

    Args:
        changed_files: Set of changed file paths (relative to repo root).

    Returns:
        List of (source, target) tuples representing detected relationships.
    """
    relationships: list[tuple[str, str]] = []
    file_list = sorted(changed_files)

    for file_path in file_list:
        p = Path(file_path)
        stem = p.stem
        ext = p.suffix

        # Skip files without extensions
        if not ext:
            continue

        # Test file pairing: test_foo.py ↔ foo.py
        if stem.startswith("test_"):
            # test_config.py → look for config.py in the changed set
            source_stem = stem[5:]  # strip "test_"
            _find_source_for_test(
                file_path, p, source_stem, ext, changed_files, relationships
            )
        elif stem.endswith("_test"):
            # config_test.py → look for config.py
            source_stem = stem[:-5]  # strip "_test"
            _find_source_for_test(
                file_path, p, source_stem, ext, changed_files, relationships
            )

    return relationships


def _find_source_for_test(
    test_path: str,
    test_p: Path,
    source_stem: str,
    ext: str,
    changed_files: set[str],
    relationships: list[tuple[str, str]],
) -> None:
    """Find a source file that matches a test file pattern.

    Checks:
    1. Same directory: tests/test_foo.py ↔ tests/foo.py (unlikely but possible)
    2. Mirror path: tests/x/test_y.py ↔ src/x/y.py
    3. Parallel dir: tests/master_rl/test_config.py ↔ src/master_rl/config.py
    """
    parent = test_p.parent
    source_name = source_stem + ext

    # 1. Same directory
    same_dir = str(parent / source_name)
    if same_dir in changed_files and same_dir != test_path:
        relationships.append((test_path, same_dir))
        return

    # 2. Mirror path: swap tests/ → src/ (or test/ → src/, etc.)
    parent_str = str(parent)
    for test_dir, src_dirs in [
        ("tests", ["src", "lib", "app"]),
        ("test", ["src", "lib", "app"]),
    ]:
        if parent_str.startswith(test_dir + "/") or parent_str == test_dir:
            rest = parent_str[len(test_dir):]
            for src_dir in src_dirs:
                mirror = src_dir + rest
                candidate = str(Path(mirror) / source_name)
                if candidate in changed_files:
                    relationships.append((test_path, candidate))
                    return

    # 3. Any file with matching stem in the changed set
    for candidate in changed_files:
        if candidate == test_path:
            continue
        cp = Path(candidate)
        if cp.stem == source_stem and cp.suffix == ext:
            relationships.append((test_path, candidate))
            return


# ============================================================
# Transitive closure
# ============================================================

def compute_transitive_closure(
    direct_edges: dict[str, set[str]],
) -> dict[str, dict[str, Optional[str]]]:
    """Compute transitive closure of a dependency graph.

    For each node, finds all transitively reachable nodes via BFS
    and records the intermediate node for transitive edges.

    Args:
        direct_edges: Adjacency list mapping source → set of targets.

    Returns:
        Dict mapping source → dict of {target: via_node_or_None}.
        Direct edges have via=None, transitive edges have via=intermediate_node.
    """
    closure: dict[str, dict[str, Optional[str]]] = {}

    all_nodes = set(direct_edges.keys())
    for targets in direct_edges.values():
        all_nodes.update(targets)

    for start in all_nodes:
        reachable: dict[str, Optional[str]] = {}
        visited: set[str] = {start}
        # BFS queue: (node, parent_that_led_here)
        queue: deque[tuple[str, Optional[str]]] = deque()

        # Seed with direct edges
        for direct_target in direct_edges.get(start, set()):
            if direct_target != start:
                queue.append((direct_target, None))

        while queue:
            node, via = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            reachable[node] = via
            # Follow edges from this node (these become transitive)
            for next_node in direct_edges.get(node, set()):
                if next_node not in visited:
                    # For transitive: via is the first hop (direct target)
                    transitive_via = node if via is None else via
                    queue.append((next_node, transitive_via))

        if reachable:
            closure[start] = reachable

    return closure


# ============================================================
# Main entry point: detect all file relationships
# ============================================================

def detect_file_relationships(
    file_diffs: list,
    repo_root: Path,
) -> list[FileRelationship]:
    """Detect import/dependency relationships between changed files.

    Uses a tiered approach:
    - Tier 1: Python ast-based import extraction (100% accurate)
    - Tier 2: Regex-based import extraction for other languages
    - Tier 3: Path-based heuristic fallbacks

    Then computes transitive closure to surface indirect dependencies.

    Args:
        file_diffs: List of FileDiff objects from the parsed diff.
        repo_root: Absolute path to the repository root.

    Returns:
        List of FileRelationship objects, sorted by source path.
    """
    # Build the set of changed file paths
    changed_files: set[str] = set()
    for fd in file_diffs:
        if not fd.is_binary:
            changed_files.add(fd.file_path)

    if len(changed_files) < 2:
        return []

    # Phase 1: Extract imports and build direct edges
    direct_edges: dict[str, set[str]] = {}
    files_with_imports: set[str] = set()  # Track which files had imports detected

    for file_path in sorted(changed_files):
        ext = Path(file_path).suffix
        source_code = _read_file_safe(repo_root / file_path)

        if source_code is None:
            continue

        # Extract imports using appropriate tier
        if ext == ".py":
            # Tier 1: Python AST
            raw_imports = extract_python_imports(source_code)
        else:
            # Tier 2: Regex
            raw_imports = extract_imports_regex(source_code, ext)

        # Resolve imports to file paths and check against changed set
        resolved_targets: set[str] = set()
        for module_path in raw_imports:
            resolved = resolve_module_to_file(module_path, repo_root, ext)
            if resolved and resolved in changed_files and resolved != file_path:
                resolved_targets.add(resolved)

        if resolved_targets:
            direct_edges[file_path] = resolved_targets
            files_with_imports.add(file_path)

    # Phase 2: Path heuristic fallback for files without import-based relationships
    files_with_any_relationship = set()
    for src, targets in direct_edges.items():
        files_with_any_relationship.add(src)
        files_with_any_relationship.update(targets)

    orphan_files = changed_files - files_with_any_relationship
    if orphan_files:
        heuristic_pairs = detect_path_relationships(changed_files)
        for source, target in heuristic_pairs:
            if source in orphan_files or target in orphan_files:
                direct_edges.setdefault(source, set()).add(target)

    # Phase 3: Compute transitive closure
    closure = compute_transitive_closure(direct_edges)

    # Phase 4: Build FileRelationship list
    relationships: list[FileRelationship] = []
    seen: set[tuple[str, str]] = set()

    for source, targets in sorted(closure.items()):
        for target, via in sorted(targets.items()):
            pair = (source, target)
            if pair not in seen:
                seen.add(pair)
                if via is None:
                    relationships.append(
                        FileRelationship(source=source, target=target, kind="direct")
                    )
                else:
                    relationships.append(
                        FileRelationship(
                            source=source, target=target, kind="transitive", via=via
                        )
                    )

    return relationships


# ============================================================
# Formatting for LLM prompt
# ============================================================

def format_relationships_for_llm(relationships: list[FileRelationship]) -> str:
    """Format file relationships as a text block for the LLM prompt.

    Args:
        relationships: List of FileRelationship objects.

    Returns:
        Formatted string for inclusion in the compose prompt,
        or empty string if no relationships detected.
    """
    if not relationships:
        return ""

    lines = ["[FILE RELATIONSHIPS]", "Detected import dependencies between changed files:"]

    for rel in relationships:
        if rel.kind == "direct":
            lines.append(f"  - {rel.source} imports {rel.target}")
        else:
            lines.append(
                f"  - {rel.source} depends on {rel.target} (transitive, via {rel.via})"
            )

    return "\n".join(lines)


# ============================================================
# Internal helpers
# ============================================================

def _read_file_safe(file_path: Path) -> Optional[str]:
    """Read a file's contents, returning None on any error.

    Args:
        file_path: Absolute path to the file.

    Returns:
        File contents as string, or None if the file can't be read.
    """
    try:
        return file_path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, PermissionError, OSError):
        return None

