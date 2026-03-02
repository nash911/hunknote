"""C / C++ symbol extractor — Tier 2 (regex-based).

Handles: #include, function signatures, struct, typedef, class, namespace.
"""

import re

from hunknote.compose.extractors.base import SymbolExtractor


class CExtractor(SymbolExtractor):
    """Regex-based symbol extractor for C."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # Function definitions: type name(
        for m in re.finditer(
            r"^\s*(?:static\s+)?(?:inline\s+)?(?:extern\s+)?(?:const\s+)?"
            r"(?:\w+(?:\s*\*)*)\s+(\w+)\s*\(",
            code, re.MULTILINE,
        ):
            name = m.group(1)
            if name not in {"if", "for", "while", "switch", "return", "sizeof",
                            "typedef", "struct", "enum", "union", "extern",
                            "static", "inline", "const", "void", "int", "char",
                            "float", "double", "long", "short", "unsigned"}:
                definitions.add(name)
        # struct/enum/union name
        for m in re.finditer(r"^\s*(?:typedef\s+)?(?:struct|enum|union)\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # typedef ... name;
        for m in re.finditer(r"^\s*typedef\s+.*\s+(\w+)\s*;", code, re.MULTILINE):
            definitions.add(m.group(1))
        # #define NAME
        for m in re.finditer(r"^\s*#define\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        references: set[str] = set()
        for m in re.finditer(r"(\w+)\s*\(", code):
            name = m.group(1)
            if name not in {"if", "for", "while", "switch", "return", "sizeof",
                            "printf", "fprintf", "sprintf", "scanf", "malloc",
                            "calloc", "realloc", "free", "memcpy", "memset",
                            "strlen", "strcmp", "strcpy", "strcat", "atoi",
                            "exit", "abort", "assert"}:
                references.add(name)
        return references

    def extract_imports(self, code: str) -> set[str]:
        imports: set[str] = set()
        for m in re.finditer(r'^\s*#include\s+[<"]([^>"]+)[>"]', code, re.MULTILINE):
            imports.add(m.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        # C: non-static functions in headers are exports
        exports: set[str] = set()
        for m in re.finditer(
            r"^\s*(?!static\s)(?:extern\s+)?(?:const\s+)?(?:\w+(?:\s*\*)*)\s+(\w+)\s*\(",
            code, re.MULTILINE,
        ):
            name = m.group(1)
            if name not in {"if", "for", "while", "switch", "return", "sizeof",
                            "typedef", "struct", "enum", "union"}:
                exports.add(name)
        return exports


class CppExtractor(CExtractor):
    """Regex-based symbol extractor for C++ (extends C)."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions = super().extract_definitions(code)
        # class name
        for m in re.finditer(r"^\s*class\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # namespace name
        for m in re.finditer(r"^\s*namespace\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # template<...> class/struct name
        for m in re.finditer(r"^\s*template\s*<[^>]*>\s*(?:class|struct)\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

