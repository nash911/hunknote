"""Java / Kotlin symbol extractor — Tier 2 (regex-based).

Handles: class, interface, enum, record, method signatures, import.
"""

import re

from hunknote.compose.extractors.base import SymbolExtractor


class JavaExtractor(SymbolExtractor):
    """Regex-based symbol extractor for Java."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # class/interface/enum/record
        for m in re.finditer(
            r"^\s*(?:public|private|protected|static|abstract|final|\s)*"
            r"(?:class|interface|enum|record)\s+(\w+)",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        # Method definitions (public/private/protected return_type name()
        for m in re.finditer(
            r"^\s*(?:public|private|protected|static|final|abstract|synchronized|\s)*"
            r"(?:\w+(?:<[^>]*>)?)\s+(\w+)\s*\(",
            code, re.MULTILINE,
        ):
            name = m.group(1)
            if name not in {"if", "for", "while", "switch", "catch", "return",
                            "new", "throw", "super", "this"}:
                definitions.add(name)
        # Constants: static final TYPE NAME = ...
        for m in re.finditer(
            r"^\s*(?:public|private|protected)?\s*static\s+final\s+\w+\s+(\w+)\s*=",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        references: set[str] = set()
        for m in re.finditer(r"(\w+)\s*\(", code):
            name = m.group(1)
            if name not in {"if", "for", "while", "switch", "catch", "return",
                            "new", "throw", "class", "interface", "import",
                            "System", "String", "Integer", "Boolean", "Object",
                            "List", "Map", "Set", "ArrayList", "HashMap",
                            "Collections", "Arrays", "Math"}:
                references.add(name)
        return references

    def extract_imports(self, code: str) -> set[str]:
        imports: set[str] = set()
        for m in re.finditer(r"^\s*import\s+(?:static\s+)?([\w.]+)", code, re.MULTILINE):
            imports.add(m.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        exports: set[str] = set()
        # Public classes, interfaces, enums
        for m in re.finditer(
            r"^\s*public\s+(?:static\s+)?(?:abstract\s+)?(?:final\s+)?"
            r"(?:class|interface|enum|record)\s+(\w+)",
            code, re.MULTILINE,
        ):
            exports.add(m.group(1))
        return exports


class KotlinExtractor(SymbolExtractor):
    """Regex-based symbol extractor for Kotlin."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # fun name / suspend fun name
        for m in re.finditer(
            r"^\s*(?:(?:public|private|protected|internal|override|open|abstract|suspend)\s+)*"
            r"fun\s+(\w+)",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        # class/interface/enum/object/data class
        for m in re.finditer(
            r"^\s*(?:(?:public|private|protected|internal|open|abstract|sealed|data|inner)\s+)*"
            r"(?:class|interface|enum|object)\s+(\w+)",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        # val/var at top level
        for m in re.finditer(r"^\s*(?:val|var|const\s+val)\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # typealias
        for m in re.finditer(r"^\s*typealias\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        references: set[str] = set()
        for m in re.finditer(r"(\w+)\s*\(", code):
            name = m.group(1)
            if name not in {"if", "for", "while", "when", "catch", "return",
                            "fun", "class", "val", "var", "object", "import",
                            "println", "print", "listOf", "mapOf", "setOf",
                            "arrayOf", "mutableListOf", "mutableMapOf"}:
                references.add(name)
        return references

    def extract_imports(self, code: str) -> set[str]:
        imports: set[str] = set()
        for m in re.finditer(r"^\s*import\s+([\w.]+)", code, re.MULTILINE):
            imports.add(m.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        # Kotlin: public by default
        exports: set[str] = set()
        for m in re.finditer(
            r"^\s*(?:(?:public|open|abstract|sealed|data)\s+)*"
            r"(?:fun|class|interface|enum|object|val|var)\s+(\w+)",
            code, re.MULTILINE,
        ):
            exports.add(m.group(1))
        return exports

