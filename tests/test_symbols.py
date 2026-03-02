"""Tests for the symbol extraction module."""

import pytest

from hunknote.compose.models import FileDiff, HunkRef, HunkSymbols, LargeHunkAnnotation
from hunknote.compose.symbols import (
    extract_symbols_from_hunk,
    extract_all_symbols,
    annotate_large_hunks,
    _detect_language,
)


# ============================================================
# Helper: Create a HunkRef with diff lines
# ============================================================

def _make_hunk(
    hunk_id: str,
    file_path: str,
    added: list[str] | None = None,
    removed: list[str] | None = None,
    context: list[str] | None = None,
) -> HunkRef:
    """Create a HunkRef with specified added/removed/context lines."""
    lines = []
    if context:
        for line in context:
            lines.append(f" {line}")
    if removed:
        for line in removed:
            lines.append(f"-{line}")
    if added:
        for line in added:
            lines.append(f"+{line}")
    return HunkRef(
        id=hunk_id,
        file_path=file_path,
        header="@@ -1,5 +1,5 @@",
        old_start=1, old_len=5, new_start=1, new_len=5,
        lines=lines,
    )


# ============================================================
# Language Detection Tests
# ============================================================

class TestDetectLanguage:
    """Tests for language detection from file path."""

    def test_python(self):
        assert _detect_language("src/main.py") == "python"

    def test_javascript(self):
        assert _detect_language("app/index.js") == "javascript"

    def test_typescript(self):
        assert _detect_language("src/utils.ts") == "typescript"

    def test_go(self):
        assert _detect_language("cmd/main.go") == "go"

    def test_rust(self):
        assert _detect_language("src/lib.rs") == "rust"

    def test_unknown(self):
        assert _detect_language("file.xyz") == "unknown"


# ============================================================
# Symbol Extraction from Hunk Tests
# ============================================================

class TestExtractSymbolsFromHunk:
    """Tests for extract_symbols_from_hunk."""

    def test_python_function_addition(self):
        hunk = _make_hunk(
            "H1", "utils.py",
            added=["def rate_limit(key):", "    return _check(key)"],
        )
        symbols = extract_symbols_from_hunk(hunk)
        assert "rate_limit" in symbols.defines
        assert symbols.file_path == "utils.py"
        assert symbols.language == "python"

    def test_python_function_removal(self):
        hunk = _make_hunk(
            "H1", "utils.py",
            removed=["def old_function():", "    pass"],
        )
        symbols = extract_symbols_from_hunk(hunk)
        assert "old_function" in symbols.removes

    def test_python_function_modification(self):
        hunk = _make_hunk(
            "H1", "utils.py",
            added=["def my_func(x, y):", "    return x + y"],
            removed=["def my_func(x):", "    return x"],
        )
        symbols = extract_symbols_from_hunk(hunk)
        assert "my_func" in symbols.modifies

    def test_python_import_added(self):
        hunk = _make_hunk(
            "H1", "api.py",
            added=["from utils import rate_limit"],
        )
        symbols = extract_symbols_from_hunk(hunk)
        assert any("utils" in imp for imp in symbols.imports_added)

    def test_python_import_removed(self):
        hunk = _make_hunk(
            "H1", "api.py",
            removed=["from utils import old_func"],
            added=["from utils import new_func"],
        )
        symbols = extract_symbols_from_hunk(hunk)
        assert len(symbols.imports_added) > 0
        assert len(symbols.imports_removed) > 0

    def test_js_function_definition(self):
        hunk = _make_hunk(
            "H1", "app.js",
            added=["function handleRequest(req) {", "  return res.json();", "}"],
        )
        symbols = extract_symbols_from_hunk(hunk)
        assert "handleRequest" in symbols.defines
        assert symbols.language == "javascript"

    def test_go_function_definition(self):
        hunk = _make_hunk(
            "H1", "server.go",
            added=["func HandleHealth(w http.ResponseWriter, r *http.Request) {"],
        )
        symbols = extract_symbols_from_hunk(hunk)
        assert "HandleHealth" in symbols.defines
        assert symbols.language == "go"

    def test_unknown_language_uses_fallback(self):
        hunk = _make_hunk(
            "H1", "script.xyz",
            added=["function doSomething() {"],
        )
        symbols = extract_symbols_from_hunk(hunk)
        assert "doSomething" in symbols.defines
        assert symbols.language == "unknown"


# ============================================================
# Extract All Symbols Tests
# ============================================================

class TestExtractAllSymbols:
    """Tests for extract_all_symbols."""

    def test_multiple_hunks(self):
        inventory = {
            "H1": _make_hunk("H1", "a.py", added=["def func_a():", "    pass"]),
            "H2": _make_hunk("H2", "b.py", added=["def func_b():", "    pass"]),
        }
        analyses = extract_all_symbols(inventory)
        assert "H1" in analyses
        assert "H2" in analyses
        assert "func_a" in analyses["H1"].defines
        assert "func_b" in analyses["H2"].defines

    def test_empty_inventory(self):
        analyses = extract_all_symbols({})
        assert len(analyses) == 0


# ============================================================
# Large Hunk Annotation Tests
# ============================================================

class TestAnnotateLargeHunks:
    """Tests for annotate_large_hunks."""

    def test_small_hunk_not_annotated(self):
        hunk = _make_hunk("H1", "a.py", added=["x = 1"])
        inventory = {"H1": hunk}
        file_diffs = [FileDiff(file_path="a.py", diff_header_lines=[], hunks=[hunk])]
        analyses = extract_all_symbols(inventory)
        annotations = annotate_large_hunks(inventory, file_diffs, analyses)
        assert len(annotations) == 0

    def test_new_file_annotated(self):
        """A new file should always be annotated."""
        added_lines = [f"line {i}" for i in range(10)]
        hunk = _make_hunk("H1", "new.py", added=added_lines)
        inventory = {"H1": hunk}
        file_diffs = [FileDiff(
            file_path="new.py", diff_header_lines=[], hunks=[hunk],
            is_new_file=True,
        )]
        analyses = extract_all_symbols(inventory)
        annotations = annotate_large_hunks(inventory, file_diffs, analyses)
        assert "H1" in annotations
        assert annotations["H1"].is_new_file

    def test_large_hunk_annotated(self):
        """A hunk with >50 added lines should be annotated as large."""
        added_lines = [f"def func_{i}():" for i in range(30)] + ["    pass"] * 30
        hunk = _make_hunk("H1", "big.py", added=added_lines)
        inventory = {"H1": hunk}
        file_diffs = [FileDiff(file_path="big.py", diff_header_lines=[], hunks=[hunk])]
        analyses = extract_all_symbols(inventory)
        annotations = annotate_large_hunks(inventory, file_diffs, analyses)
        assert "H1" in annotations
        assert annotations["H1"].is_large_hunk
        assert annotations["H1"].line_count > 50

    def test_large_hunk_definition_count(self):
        """A large hunk should report how many definitions it contains."""
        added_lines = [
            "class MyClass:", "    pass",
            "def func_a():", "    pass",
            "def func_b():", "    pass",
            "MAX_SIZE = 100",
        ] + ["# padding"] * 50
        hunk = _make_hunk("H1", "big.py", added=added_lines)
        inventory = {"H1": hunk}
        file_diffs = [FileDiff(file_path="big.py", diff_header_lines=[], hunks=[hunk])]
        analyses = extract_all_symbols(inventory)
        annotations = annotate_large_hunks(inventory, file_diffs, analyses)
        assert "H1" in annotations
        assert annotations["H1"].definitions_count >= 3

