"""Go symbol extractor — Tier 2 (regex-based).

Handles: func, type, var, const, import.
"""

import re

from hunknote.compose.extractors.base import SymbolExtractor


class GoExtractor(SymbolExtractor):
    """Regex-based symbol extractor for Go."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # func Name(  or  func (r *Receiver) Name(
        for m in re.finditer(r"^\s*func\s+(?:\([^)]*\)\s+)?(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # type Name struct/interface/...
        for m in re.finditer(r"^\s*type\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # var Name / const Name
        for m in re.finditer(r"^\s*(?:var|const)\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        references: set[str] = set()
        # Function calls: Name(
        for m in re.finditer(r"(\w+)\s*\(", code):
            name = m.group(1)
            if name not in {"if", "for", "switch", "case", "select", "go",
                            "return", "func", "type", "var", "const", "range",
                            "make", "new", "append", "len", "cap", "close",
                            "delete", "copy", "panic", "recover", "print",
                            "println", "complex", "real", "imag"}:
                references.add(name)
        return references

    def extract_imports(self, code: str) -> set[str]:
        imports: set[str] = set()
        # Single import: import "path"
        for m in re.finditer(r'''import\s+"([\w./\-]+)"''', code):
            imports.add(m.group(1))
        # Multi-import block: import ( "path1" \n "path2" )
        for block in re.finditer(r"import\s*\((.*?)\)", code, re.DOTALL):
            for path in re.finditer(r'''"([\w./\-]+)"''', block.group(1)):
                imports.add(path.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        # In Go, exported symbols start with an uppercase letter
        exports: set[str] = set()
        for m in re.finditer(r"^\s*(?:func|type|var|const)\s+(?:\([^)]*\)\s+)?([A-Z]\w*)", code, re.MULTILINE):
            exports.add(m.group(1))
        return exports

