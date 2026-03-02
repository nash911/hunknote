"""PHP symbol extractor — Tier 2 (regex-based).

Handles: function, class, interface, trait, use, namespace.
"""

import re

from hunknote.compose.extractors.base import SymbolExtractor


class PHPExtractor(SymbolExtractor):
    """Regex-based symbol extractor for PHP."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # function name
        for m in re.finditer(r"^\s*(?:public|private|protected|static|\s)*function\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # class/interface/trait/enum
        for m in re.finditer(
            r"^\s*(?:abstract\s+)?(?:final\s+)?(?:class|interface|trait|enum)\s+(\w+)",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        # const NAME
        for m in re.finditer(r"^\s*(?:public|private|protected)?\s*const\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        references: set[str] = set()
        for m in re.finditer(r"(\w+)\s*\(", code):
            name = m.group(1)
            if name not in {"if", "for", "while", "foreach", "switch", "catch",
                            "return", "function", "class", "new", "echo", "print",
                            "isset", "unset", "empty", "array", "list",
                            "count", "strlen", "strpos", "substr", "explode",
                            "implode", "in_array", "array_map", "array_filter",
                            "var_dump", "print_r", "die", "exit"}:
                references.add(name)
        return references

    def extract_imports(self, code: str) -> set[str]:
        imports: set[str] = set()
        # use Namespace\Class
        for m in re.finditer(r"^\s*use\s+([\w\\]+)", code, re.MULTILINE):
            imports.add(m.group(1))
        # require/include
        for m in re.finditer(r"""^\s*(?:require|include)(?:_once)?\s+['"]([^'"]+)['"]""", code, re.MULTILINE):
            imports.add(m.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        exports: set[str] = set()
        for m in re.finditer(r"^\s*(?:public\s+)?(?:class|interface|trait)\s+(\w+)", code, re.MULTILINE):
            exports.add(m.group(1))
        return exports

