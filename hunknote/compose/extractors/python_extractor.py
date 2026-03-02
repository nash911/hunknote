"""Python symbol extractor — Tier 1 (AST-based, highest accuracy).

Uses ast.parse() to extract symbols from Python code fragments.
Handles def, class, import, from...import, importlib.import_module(), __import__().
"""

import ast
import re
from typing import Set

from hunknote.compose.extractors.base import SymbolExtractor, is_module_scope


class PythonExtractor(SymbolExtractor):
    """AST-based symbol extractor for Python code."""

    def extract_definitions(self, code: str) -> set[str]:
        """Extract function, class, and module-level variable definitions."""
        definitions: set[str] = set()

        try:
            tree = ast.parse(code)
        except SyntaxError:
            # Fall back to regex for fragments that don't parse
            return self._extract_definitions_regex(code)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Only module-scope and class-scope functions
                definitions.add(node.name)
            elif isinstance(node, ast.ClassDef):
                definitions.add(node.name)
            elif isinstance(node, ast.Assign):
                # Module-level assignments (col_offset == 0)
                if getattr(node, "col_offset", -1) == 0:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            definitions.add(target.id)
            elif isinstance(node, ast.AnnAssign):
                if getattr(node, "col_offset", -1) == 0 and isinstance(node.target, ast.Name):
                    definitions.add(node.target.id)

        return definitions

    def _extract_definitions_regex(self, code: str) -> set[str]:
        """Regex fallback for code fragments that don't parse as valid AST."""
        definitions: set[str] = set()
        for line in code.splitlines():
            if not line.strip():
                continue
            if is_module_scope(line, "python"):
                # def / async def
                m = re.match(r"^\s*(?:async\s+)?def\s+(\w+)", line)
                if m:
                    definitions.add(m.group(1))
                    continue
                # class
                m = re.match(r"^\s*class\s+(\w+)", line)
                if m:
                    definitions.add(m.group(1))
                    continue
                # Module-level assignment: NAME = ...
                m = re.match(r"^(\w+)\s*[=:]", line)
                if m and not m.group(1).startswith("_") or m and m.group(1) == m.group(1).upper():
                    # Include constants (ALL_CAPS) and public names
                    definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        """Extract function/class references (calls and type annotations)."""
        references: set[str] = set()

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._extract_references_regex(code)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Function/class calls
                if isinstance(node.func, ast.Name):
                    references.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    references.add(node.func.attr)
            elif isinstance(node, ast.Name):
                # Name references (could be variables or functions)
                # We include all names; filtering happens at graph level
                pass  # Too noisy — only include explicit calls
            elif isinstance(node, ast.Attribute):
                # method/attribute access: obj.method
                references.add(node.attr)

        return references

    def _extract_references_regex(self, code: str) -> set[str]:
        """Regex fallback for function call references."""
        references: set[str] = set()
        # Match function calls: name(
        for m in re.finditer(r"(\w+)\s*\(", code):
            name = m.group(1)
            # Skip keywords and builtins
            if name not in {"if", "for", "while", "with", "elif", "return",
                            "print", "len", "range", "str", "int", "list",
                            "dict", "set", "tuple", "type", "super", "self",
                            "isinstance", "hasattr", "getattr", "setattr",
                            "True", "False", "None"}:
                references.add(name)
        return references

    def extract_imports(self, code: str) -> set[str]:
        """Extract all import statements using AST."""
        imports: set[str] = set()

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._extract_imports_regex(code)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
                    # Also add individual imported names for precise tracking
                    if node.names:
                        for alias in node.names:
                            if alias.name != "*":
                                imports.add(f"{node.module}.{alias.name}")
            elif isinstance(node, ast.Call):
                # importlib.import_module("module")
                if (isinstance(node.func, ast.Attribute)
                        and node.func.attr == "import_module"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    imports.add(node.args[0].value)
                # __import__("module")
                elif (isinstance(node.func, ast.Name)
                      and node.func.id == "__import__"
                      and node.args
                      and isinstance(node.args[0], ast.Constant)
                      and isinstance(node.args[0].value, str)):
                    imports.add(node.args[0].value)

        return imports

    def _extract_imports_regex(self, code: str) -> set[str]:
        """Regex fallback for import extraction."""
        imports: set[str] = set()
        for line in code.splitlines():
            stripped = line.strip()
            # from X import Y
            m = re.match(r"from\s+([\w.]+)\s+import", stripped)
            if m:
                imports.add(m.group(1))
                continue
            # import X
            m = re.match(r"import\s+([\w.]+)", stripped)
            if m:
                imports.add(m.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        """Extract __all__ exports from Python modules."""
        exports: set[str] = set()
        # Match __all__ = [...]
        m = re.search(r"__all__\s*=\s*\[(.*?)\]", code, re.DOTALL)
        if m:
            for name_match in re.finditer(r"""['"](\w+)['"]""", m.group(1)):
                exports.add(name_match.group(1))
        return exports

