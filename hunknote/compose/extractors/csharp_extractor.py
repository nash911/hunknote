"""C# symbol extractor — Tier 2 (regex-based).

Handles: class, interface, struct, enum, using, method signatures.
"""

import re

from hunknote.compose.extractors.base import SymbolExtractor


class CSharpExtractor(SymbolExtractor):
    """Regex-based symbol extractor for C#."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # class/interface/struct/enum/record
        for m in re.finditer(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|"
            r"sealed|partial|readonly)\s+)*"
            r"(?:class|interface|struct|enum|record)\s+(\w+)",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        # Method definitions
        for m in re.finditer(
            r"^\s*(?:(?:public|private|protected|internal|static|virtual|"
            r"override|abstract|async|new)\s+)*"
            r"(?:\w+(?:<[^>]*>)?(?:\[\])?)\s+(\w+)\s*\(",
            code, re.MULTILINE,
        ):
            name = m.group(1)
            if name not in {"if", "for", "while", "switch", "catch", "return",
                            "new", "throw", "class", "interface", "struct"}:
                definitions.add(name)
        # Properties
        for m in re.finditer(
            r"^\s*(?:(?:public|private|protected|internal|static|virtual|"
            r"override|abstract)\s+)*"
            r"(?:\w+(?:<[^>]*>)?)\s+(\w+)\s*\{",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        references: set[str] = set()
        for m in re.finditer(r"(\w+)\s*[.(]", code):
            name = m.group(1)
            if name not in {"if", "for", "while", "switch", "catch", "return",
                            "new", "throw", "var", "class", "using", "namespace",
                            "Console", "String", "Math", "Convert",
                            "int", "string", "bool", "double", "float", "void",
                            "object", "null", "true", "false", "this", "base"}:
                references.add(name)
        return references

    def extract_imports(self, code: str) -> set[str]:
        imports: set[str] = set()
        for m in re.finditer(r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;", code, re.MULTILINE):
            imports.add(m.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        exports: set[str] = set()
        for m in re.finditer(
            r"^\s*public\s+(?:(?:static|abstract|sealed|partial|virtual|override)\s+)*"
            r"(?:class|interface|struct|enum|record)\s+(\w+)",
            code, re.MULTILINE,
        ):
            exports.add(m.group(1))
        return exports

