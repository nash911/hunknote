"""JavaScript / TypeScript symbol extractor — Tier 2 (regex-based).

Handles: function, class, const, let, var, interface, type, enum,
import, export, require().
"""

import re

from hunknote.compose.extractors.base import SymbolExtractor, is_module_scope


class JavaScriptExtractor(SymbolExtractor):
    """Regex-based symbol extractor for JavaScript."""

    # Definition patterns at module scope
    _DEF_PATTERNS = [
        re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)", re.MULTILINE),
        re.compile(r"^\s*(?:export\s+)?class\s+(\w+)", re.MULTILINE),
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=", re.MULTILINE),
    ]

    _IMPORT_PATTERNS = [
        re.compile(r"""(?:import|from)\s+['"]([^'"]+)['"]"""),
        re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)"""),
    ]

    _EXPORT_PATTERNS = [
        re.compile(r"^\s*export\s+(?:default\s+)?(?:function|class|const|let|var|async)\s+(\w+)", re.MULTILINE),
        re.compile(r"^\s*export\s*\{([^}]+)\}", re.MULTILINE),
        re.compile(r"module\.exports\s*=\s*(\w+)", re.MULTILINE),
    ]

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        for pattern in self._DEF_PATTERNS:
            for m in pattern.finditer(code):
                if is_module_scope(code.splitlines()[code[:m.start()].count("\n")] if "\n" in code[:m.start()] else code[:m.end()]):
                    definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        references: set[str] = set()
        # Function calls
        for m in re.finditer(r"(\w+)\s*\(", code):
            name = m.group(1)
            if name not in {"if", "for", "while", "switch", "catch", "return",
                            "function", "class", "new", "typeof", "void",
                            "require", "import", "export", "console", "this"}:
                references.add(name)
        return references

    def extract_imports(self, code: str) -> set[str]:
        imports: set[str] = set()
        for pattern in self._IMPORT_PATTERNS:
            for m in pattern.finditer(code):
                imports.add(m.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        exports: set[str] = set()
        for pattern in self._EXPORT_PATTERNS:
            for m in pattern.finditer(code):
                if "{" in m.group(0):
                    # export { a, b, c }
                    for name in re.findall(r"(\w+)", m.group(1)):
                        exports.add(name)
                else:
                    exports.add(m.group(1))
        return exports


class TypeScriptExtractor(JavaScriptExtractor):
    """Regex-based symbol extractor for TypeScript (extends JavaScript)."""

    _DEF_PATTERNS = JavaScriptExtractor._DEF_PATTERNS + [
        re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)", re.MULTILINE),
        re.compile(r"^\s*(?:export\s+)?type\s+(\w+)\s*=", re.MULTILINE),
        re.compile(r"^\s*(?:export\s+)?enum\s+(\w+)", re.MULTILINE),
    ]

