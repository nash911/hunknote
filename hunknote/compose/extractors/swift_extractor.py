"""Swift symbol extractor — Tier 2 (regex-based).

Handles: func, class, struct, enum, protocol, import.
"""

import re

from hunknote.compose.extractors.base import SymbolExtractor


class SwiftExtractor(SymbolExtractor):
    """Regex-based symbol extractor for Swift."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # func name
        for m in re.finditer(
            r"^\s*(?:(?:public|private|internal|fileprivate|open|static|class|"
            r"override|mutating|nonmutating)\s+)*"
            r"func\s+(\w+)",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        # class/struct/enum/protocol/actor
        for m in re.finditer(
            r"^\s*(?:(?:public|private|internal|fileprivate|open|final)\s+)*"
            r"(?:class|struct|enum|protocol|actor)\s+(\w+)",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        # typealias
        for m in re.finditer(r"^\s*(?:public\s+)?typealias\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # let/var at top level
        for m in re.finditer(r"^(?:public\s+|private\s+|internal\s+)?(?:let|var)\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        references: set[str] = set()
        for m in re.finditer(r"(\w+)\s*\(", code):
            name = m.group(1)
            if name not in {"if", "for", "while", "switch", "guard", "return",
                            "func", "class", "struct", "enum", "protocol",
                            "import", "let", "var", "self", "Self", "super",
                            "print", "debugPrint", "fatalError", "precondition",
                            "Int", "String", "Double", "Float", "Bool", "Array",
                            "Dictionary", "Set", "Optional", "nil", "true", "false"}:
                references.add(name)
        return references

    def extract_imports(self, code: str) -> set[str]:
        imports: set[str] = set()
        for m in re.finditer(r"^\s*import\s+(\w+)", code, re.MULTILINE):
            imports.add(m.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        exports: set[str] = set()
        for m in re.finditer(
            r"^\s*(?:public|open)\s+(?:(?:static|class|final|override)\s+)*"
            r"(?:func|class|struct|enum|protocol|actor|let|var)\s+(\w+)",
            code, re.MULTILINE,
        ):
            exports.add(m.group(1))
        return exports

