"""Programmatic tools available to ReAct sub-agents.

These tools provide structured data that the LLM uses as hints for
reasoning.  They wrap existing functions from the compose pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from typing import Any

from hunknote.compose.models import (
    CommitGroup,
    FileDiff,
    HunkRef,
    HunkSymbols,
)

logger = logging.getLogger(__name__)


# ============================================================
# Tools for the Dependency Analyzer
# ============================================================

def get_hunk_diff(
    hunk_ids: list[str],
    inventory: dict[str, HunkRef],
) -> str:
    """Return the raw diff lines for the given hunks.

    Args:
        hunk_ids: List of hunk IDs to retrieve.
        inventory: Hunk inventory.

    Returns:
        JSON string with hunk diffs.
    """
    results: list[dict[str, Any]] = []
    for hid in hunk_ids:
        hunk = inventory.get(hid)
        if hunk:
            changed = [ln for ln in hunk.lines
                       if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
            results.append({
                "hunk_id": hid,
                "file_path": hunk.file_path,
                "header": hunk.header,
                "lines": changed[:50],
                "total_changed_lines": len(changed),
                "truncated": len(changed) > 50,
            })
        else:
            results.append({"hunk_id": hid, "error": "not found"})
    return json.dumps(results, indent=2)


def get_file_hunks(
    file_path: str,
    file_diffs: list[FileDiff],
) -> str:
    """Return all hunk IDs belonging to a specific file.

    Args:
        file_path: Path of the file.
        file_diffs: All file diffs.

    Returns:
        JSON string with hunk info.
    """
    for fd in file_diffs:
        if fd.file_path == file_path:
            hunks = [{"id": h.id, "header": h.header} for h in fd.hunks]
            return json.dumps({"file_path": file_path, "hunks": hunks})
    return json.dumps({"file_path": file_path, "error": "file not found"})


def get_symbol_summary(
    hunk_ids: list[str],
    symbol_analyses: dict[str, HunkSymbols],
) -> str:
    """Return symbol info (defines, references, imports) for given hunks.

    Args:
        hunk_ids: Hunk IDs to query.
        symbol_analyses: Pre-computed symbol data.

    Returns:
        JSON string with symbol summaries.
    """
    results: list[dict] = []
    for hid in hunk_ids:
        sym = symbol_analyses.get(hid)
        if sym:
            results.append({
                "hunk_id": hid,
                "file_path": sym.file_path,
                "language": sym.language,
                "defines": sorted(sym.defines)[:20],
                "references": sorted(sym.references)[:20],
                "imports_added": sorted(sym.imports_added),
                "exports_added": sorted(sym.exports_added),
            })
        else:
            results.append({"hunk_id": hid, "symbols": "not extracted"})
    return json.dumps(results, indent=2)


# ============================================================
# Tools for the Checkpoint Validator
# ============================================================

def get_checkpoint_state(
    checkpoint: int,
    ordered_groups: list[CommitGroup],
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff] | None = None,
) -> str:
    """Get the state at a specific checkpoint (after N commits).

    Args:
        checkpoint: 1-based checkpoint index.
        ordered_groups: Ordered commit groups.
        inventory: Hunk inventory.
        file_diffs: Optional file diffs for new-file detection.

    Returns:
        JSON string with committed/remaining hunks.
    """
    committed_hunks: list[str] = []
    committed_files: set[str] = set()
    for g in ordered_groups[:checkpoint]:
        committed_hunks.extend(g.hunk_ids)
        committed_files.update(g.files)

    remaining_hunks = [hid for hid in inventory if hid not in set(committed_hunks)]

    # Identify which files are NEW (only exist because of hunks in this diff)
    # vs EXISTING (already in the repo, only being modified)
    new_files: set[str] = set()
    existing_files: set[str] = set()
    if file_diffs:
        for fd in file_diffs:
            if fd.is_new_file:
                new_files.add(fd.file_path)
            else:
                existing_files.add(fd.file_path)

    # All files in the repo that are NOT in the diff are existing unchanged files
    # and are ALWAYS available at every checkpoint
    all_diff_files = new_files | existing_files

    return json.dumps({
        "checkpoint": checkpoint,
        "committed_hunks": committed_hunks,
        "committed_files": sorted(committed_files),
        "remaining_hunks": remaining_hunks,
        "total_committed": len(committed_hunks),
        "total_remaining": len(remaining_hunks),
        "new_files_in_diff": sorted(new_files),
        "existing_files_modified_in_diff": sorted(existing_files),
        "note": (
            "Unchanged existing files in the repository are ALWAYS available. "
            "Imports from them are ALWAYS valid."
        ),
    })


def get_imports_at_checkpoint(
    checkpoint: int,
    ordered_groups: list[CommitGroup],
    symbol_analyses: dict[str, HunkSymbols],
) -> str:
    """List all imports added by committed hunks at a checkpoint.

    Args:
        checkpoint: 1-based checkpoint index.
        ordered_groups: Ordered commit groups.
        symbol_analyses: Symbol data.

    Returns:
        JSON with imports at checkpoint.
    """
    committed_hunks: list[str] = []
    for g in ordered_groups[:checkpoint]:
        committed_hunks.extend(g.hunk_ids)

    imports: list[dict] = []
    for hid in committed_hunks:
        sym = symbol_analyses.get(hid)
        if sym and sym.imports_added:
            imports.append({
                "hunk_id": hid,
                "file": sym.file_path,
                "imports": sorted(sym.imports_added),
            })

    return json.dumps({"checkpoint": checkpoint, "imports": imports})


def get_definitions_at_checkpoint(
    checkpoint: int,
    ordered_groups: list[CommitGroup],
    symbol_analyses: dict[str, HunkSymbols],
) -> str:
    """List all symbols defined by committed hunks at a checkpoint.

    Args:
        checkpoint: 1-based checkpoint index.
        ordered_groups: Ordered commit groups.
        symbol_analyses: Symbol data.

    Returns:
        JSON with definitions at checkpoint.
    """
    committed_hunks: list[str] = []
    for g in ordered_groups[:checkpoint]:
        committed_hunks.extend(g.hunk_ids)

    definitions: list[dict] = []
    for hid in committed_hunks:
        sym = symbol_analyses.get(hid)
        if sym and sym.defines:
            definitions.append({
                "hunk_id": hid,
                "file": sym.file_path,
                "defines": sorted(sym.defines),
            })

    return json.dumps({"checkpoint": checkpoint, "definitions": definitions})


def run_programmatic_validation(
    checkpoint: int,
    ordered_groups: list[CommitGroup],
    graph: dict[str, set[str]],
    symbol_analyses: dict[str, HunkSymbols],
    all_hunk_ids: set[str],
) -> str:
    """Run the existing programmatic checkpoint validator.

    This provides hints to the LLM-based validator.

    Args:
        checkpoint: 1-based checkpoint index.
        ordered_groups: Ordered commit groups.
        graph: Programmatic dependency graph.
        symbol_analyses: Symbol data.
        all_hunk_ids: All hunk IDs.

    Returns:
        JSON with programmatic validation results.
    """
    from hunknote.compose.checkpoint import validate_commit_checkpoint

    committed_hunks: set[str] = set()
    for g in ordered_groups[:checkpoint]:
        committed_hunks.update(g.hunk_ids)

    remaining_hunks = all_hunk_ids - committed_hunks

    result = validate_commit_checkpoint(
        committed_hunks=committed_hunks,
        remaining_hunks=remaining_hunks,
        graph=graph,
        symbol_analyses=symbol_analyses,
    )

    violations = []
    for v in result.violations:
        violations.append({
            "hunk": v.hunk,
            "in_commit": v.in_commit,
            "issue": v.issue,
            "defined_in": v.defined_in,
        })

    return json.dumps({
        "checkpoint": checkpoint,
        "valid": result.valid,
        "violations": violations,
    })


# ============================================================
# Tools for the Orchestrator
# ============================================================

def get_file_structure(file_diffs: list[FileDiff]) -> str:
    """Return an overview of files and their hunk counts.

    Args:
        file_diffs: All file diffs.

    Returns:
        JSON with file structure.
    """
    files = []
    for fd in file_diffs:
        files.append({
            "file_path": fd.file_path,
            "is_new_file": fd.is_new_file,
            "is_deleted_file": fd.is_deleted_file,
            "is_renamed": fd.is_renamed,
            "num_hunks": len(fd.hunks),
            "hunk_ids": [h.id for h in fd.hunks],
        })
    return json.dumps(files, indent=2)


def build_hunk_summary_text(
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
    symbol_analyses: dict[str, HunkSymbols] | None = None,
) -> str:
    """Build a concise text summary of all hunks for LLM context.

    Args:
        inventory: Hunk inventory.
        file_diffs: File diffs.
        symbol_analyses: Optional symbol data.

    Returns:
        Multi-line text summary.
    """
    lines: list[str] = []
    for fd in file_diffs:
        if fd.is_binary:
            continue
        file_tag = ""
        if fd.is_new_file:
            file_tag = " (new file)"
        elif fd.is_deleted_file:
            file_tag = " (deleted)"
        elif fd.is_renamed:
            file_tag = f" (renamed from {fd.old_path})"

        lines.append(f"\nFile: {fd.file_path}{file_tag}")

        for hunk in fd.hunks:
            changed = [ln for ln in hunk.lines
                       if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
            adds = sum(1 for ln in changed if ln.startswith("+"))
            dels = sum(1 for ln in changed if ln.startswith("-"))

            sym_info = ""
            if symbol_analyses and hunk.id in symbol_analyses:
                sym = symbol_analyses[hunk.id]
                parts = []
                if sym.defines:
                    parts.append(f"defines: {', '.join(sorted(sym.defines)[:5])}")
                if sym.imports_added:
                    parts.append(f"imports: {', '.join(sorted(sym.imports_added)[:5])}")
                if sym.exports_added:
                    parts.append(f"exports: {', '.join(sorted(sym.exports_added)[:5])}")
                if parts:
                    sym_info = f"  [{'; '.join(parts)}]"

            lines.append(f"  {hunk.id}: {hunk.header}  (+{adds}/-{dels}){sym_info}")

            # Show first few changed lines as context
            for ln in changed[:8]:
                lines.append(f"    {ln}")
            if len(changed) > 8:
                lines.append(f"    ... ({len(changed) - 8} more lines)")

    return "\n".join(lines)


# ============================================================
# File existence and symbol checking (for Validator)
# ============================================================

def check_file_in_repo(
    file_path: str,
    repo_root: str | None = None,
) -> str:
    """Check if a file exists in the repository and extract its exports.

    Uses ``git ls-files`` to verify the file is tracked, then reads the
    committed content (``git show HEAD:<path>``) to extract top-level
    symbol definitions.  Works across all languages by using
    language-specific regex patterns.

    Args:
        file_path: Path to check (relative to repo root).
        repo_root: Repository root directory.  If None, attempts to
            detect it via ``git rev-parse --show-toplevel``.

    Returns:
        JSON string with ``exists``, ``tracked``, ``exports``, and
        ``language`` fields.
    """
    if repo_root is None:
        repo_root = _detect_repo_root()
    if not repo_root:
        return json.dumps({
            "file_path": file_path,
            "exists": False,
            "error": "Could not detect repository root",
        })

    # Normalise path
    norm_path = file_path.replace("\\", "/")

    # Check if file is tracked
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", norm_path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        tracked = result.returncode == 0
    except Exception:
        tracked = False

    if not tracked:
        # Also check if file exists on disk (untracked)
        full_path = os.path.join(repo_root, norm_path)
        exists = os.path.isfile(full_path)
        return json.dumps({
            "file_path": file_path,
            "exists": exists,
            "tracked": False,
            "exports": [],
            "note": (
                "File exists on disk but is not git-tracked."
                if exists else
                "File does not exist in the repository."
            ),
        })

    # Read committed content via git show
    content = ""
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{norm_path}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            content = result.stdout
    except Exception:
        pass

    # If git show failed, try reading from disk
    if not content:
        full_path = os.path.join(repo_root, norm_path)
        try:
            with open(full_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            pass

    # Detect language and extract exports
    language = _detect_language(norm_path)
    exports = _extract_exports(content, language)

    return json.dumps({
        "file_path": file_path,
        "exists": True,
        "tracked": True,
        "language": language,
        "exports": exports[:50],  # Limit to 50 symbols
        "total_exports": len(exports),
        "note": (
            "This file already exists in the repository. "
            "Imports from it are always valid at every checkpoint."
        ),
    })


def _detect_repo_root() -> str | None:
    """Detect the git repository root."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _detect_language(file_path: str) -> str:
    """Detect programming language from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    return {
        ".py": "python", ".pyi": "python",
        ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".java": "java",
        ".kt": "kotlin", ".kts": "kotlin",
        ".scala": "scala",
        ".c": "c", ".h": "c",
        ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp",
        ".hh": "cpp", ".hpp": "cpp", ".hxx": "cpp",
        ".cs": "csharp",
        ".swift": "swift",
        ".lua": "lua",
        ".ex": "elixir", ".exs": "elixir",
        ".hs": "haskell",
        ".ml": "ocaml", ".mli": "ocaml",
    }.get(ext, "unknown")


def _extract_exports(content: str, language: str) -> list[str]:
    """Extract top-level exported symbol names from file content.

    Uses language-specific regex patterns to find function, class,
    constant, and type definitions.  Not exhaustive — just enough
    to let the validator confirm that a symbol exists.

    Args:
        content: File content.
        language: Detected language.

    Returns:
        Sorted list of symbol names.
    """
    if not content:
        return []

    handler = _EXPORT_EXTRACTORS.get(language, _extract_generic)
    try:
        return handler(content)
    except Exception:
        return _extract_generic(content)


def _extract_python(content: str) -> list[str]:
    """Extract Python top-level definitions."""
    symbols: set[str] = set()
    for m in re.finditer(
        r"^(?:def|class|async\s+def)\s+(\w+)",
        content,
        re.MULTILINE,
    ):
        symbols.add(m.group(1))
    # Top-level assignments
    for m in re.finditer(r"^([A-Z_][A-Z0-9_]*)\s*=", content, re.MULTILINE):
        symbols.add(m.group(1))
    # __all__ entries
    all_match = re.search(r"__all__\s*=\s*\[([^\]]+)\]", content, re.DOTALL)
    if all_match:
        for name in re.findall(r"['\"](\w+)['\"]", all_match.group(1)):
            symbols.add(name)
    return sorted(symbols)


def _extract_typescript(content: str) -> list[str]:
    """Extract TypeScript/JavaScript exports."""
    symbols: set[str] = set()
    # export function/class/const/let/var/type/interface/enum
    for m in re.finditer(
        r"export\s+(?:default\s+)?(?:function|class|const|let|var|type|interface|enum|abstract\s+class)\s+(\w+)",
        content,
    ):
        symbols.add(m.group(1))
    # export { Name1, Name2 }
    for m in re.finditer(r"export\s*\{([^}]+)\}", content):
        for name in re.findall(r"(\w+)(?:\s+as\s+\w+)?", m.group(1)):
            symbols.add(name)
    # module.exports.name or module.exports = { ... }
    for m in re.finditer(r"module\.exports\.(\w+)", content):
        symbols.add(m.group(1))
    return sorted(symbols)


def _extract_go(content: str) -> list[str]:
    """Extract Go exported symbols (capitalised names)."""
    symbols: set[str] = set()
    for m in re.finditer(
        r"^(?:func|type|var|const)\s+(\w+)",
        content,
        re.MULTILINE,
    ):
        name = m.group(1)
        if name[0].isupper():  # Go exports start with uppercase
            symbols.add(name)
    return sorted(symbols)


def _extract_rust(content: str) -> list[str]:
    """Extract Rust public symbols."""
    symbols: set[str] = set()
    for m in re.finditer(
        r"pub\s+(?:fn|struct|enum|trait|type|const|static|mod)\s+(\w+)",
        content,
    ):
        symbols.add(m.group(1))
    return sorted(symbols)


def _extract_ruby(content: str) -> list[str]:
    """Extract Ruby class/module/method definitions."""
    symbols: set[str] = set()
    for m in re.finditer(r"^(?:class|module)\s+(\w+)", content, re.MULTILINE):
        symbols.add(m.group(1))
    for m in re.finditer(r"^\s*def\s+(?:self\.)?(\w+)", content, re.MULTILINE):
        symbols.add(m.group(1))
    return sorted(symbols)


def _extract_java(content: str) -> list[str]:
    """Extract Java/Kotlin/Scala class/interface/function definitions."""
    symbols: set[str] = set()
    for m in re.finditer(
        r"(?:public|protected|internal|open|data|sealed|abstract)?\s*"
        r"(?:class|interface|enum|object|fun|val|var)\s+(\w+)",
        content,
    ):
        symbols.add(m.group(1))
    return sorted(symbols)


def _extract_c_cpp(content: str) -> list[str]:
    """Extract C/C++ function declarations, struct/class/enum definitions."""
    symbols: set[str] = set()
    # struct/class/enum/union/typedef
    for m in re.finditer(
        r"(?:struct|class|enum|union|typedef)\s+(\w+)",
        content,
    ):
        symbols.add(m.group(1))
    # Function declarations (type name(...))
    for m in re.finditer(
        r"^\w[\w\s\*]*\s+(\w+)\s*\(",
        content,
        re.MULTILINE,
    ):
        name = m.group(1)
        if name not in ("if", "while", "for", "switch", "return", "sizeof"):
            symbols.add(name)
    # #define macros
    for m in re.finditer(r"#define\s+(\w+)", content):
        symbols.add(m.group(1))
    return sorted(symbols)


def _extract_csharp(content: str) -> list[str]:
    """Extract C# class/interface/struct/enum definitions."""
    symbols: set[str] = set()
    for m in re.finditer(
        r"(?:public|internal|protected|private|static|abstract|sealed)?\s*"
        r"(?:partial\s+)?(?:class|interface|struct|enum|record)\s+(\w+)",
        content,
    ):
        symbols.add(m.group(1))
    return sorted(symbols)


def _extract_generic(content: str) -> list[str]:
    """Generic fallback: look for common definition patterns."""
    symbols: set[str] = set()
    # function/def/class/struct/enum/const/type/interface
    for m in re.finditer(
        r"(?:function|def|class|struct|enum|const|type|interface|module|trait|object)\s+(\w+)",
        content,
    ):
        symbols.add(m.group(1))
    # export/pub prefixed
    for m in re.finditer(r"(?:export|pub|public)\s+\w+\s+(\w+)", content):
        symbols.add(m.group(1))
    return sorted(symbols)


_EXPORT_EXTRACTORS = {
    "python": _extract_python,
    "typescript": _extract_typescript,
    "javascript": _extract_typescript,
    "go": _extract_go,
    "rust": _extract_rust,
    "ruby": _extract_ruby,
    "java": _extract_java,
    "kotlin": _extract_java,
    "scala": _extract_java,
    "c": _extract_c_cpp,
    "cpp": _extract_c_cpp,
    "csharp": _extract_csharp,
}


