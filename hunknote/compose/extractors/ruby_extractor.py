"""Ruby symbol extractor — Tier 2 (regex-based).

Handles: def, class, module, require, include.
"""

import re

from hunknote.compose.extractors.base import SymbolExtractor


class RubyExtractor(SymbolExtractor):
    """Regex-based symbol extractor for Ruby."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        for m in re.finditer(r"^\s*def\s+(?:self\.)?(\w+[?!]?)", code, re.MULTILINE):
            definitions.add(m.group(1))
        for m in re.finditer(r"^\s*class\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        for m in re.finditer(r"^\s*module\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # Constants
        for m in re.finditer(r"^\s*([A-Z]\w*)\s*=", code, re.MULTILINE):
            definitions.add(m.group(1))
        # attr_accessor / attr_reader / attr_writer
        for m in re.finditer(r"^\s*attr_(?:accessor|reader|writer)\s+(.+)$", code, re.MULTILINE):
            for sym in re.findall(r":(\w+)", m.group(1)):
                definitions.add(sym)
        return definitions

    def extract_references(self, code: str) -> set[str]:
        references: set[str] = set()
        for m in re.finditer(r"(\w+)\s*[.(]", code):
            name = m.group(1)
            if name not in {"if", "unless", "while", "until", "for", "do",
                            "case", "when", "begin", "rescue", "ensure", "end",
                            "return", "def", "class", "module", "include",
                            "require", "require_relative", "puts", "print",
                            "raise", "new", "self", "super", "nil", "true", "false"}:
                references.add(name)
        return references

    def extract_imports(self, code: str) -> set[str]:
        imports: set[str] = set()
        for m in re.finditer(r"""^\s*require\s+['"]([^'"]+)['"]""", code, re.MULTILINE):
            imports.add(m.group(1))
        for m in re.finditer(r"""^\s*require_relative\s+['"]([^'"]+)['"]""", code, re.MULTILINE):
            imports.add(m.group(1))
        for m in re.finditer(r"""^\s*load\s+['"]([^'"]+)['"]""", code, re.MULTILINE):
            imports.add(m.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        # Ruby: public methods/classes are exports by convention
        exports: set[str] = set()
        for m in re.finditer(r"^\s*(?:class|module)\s+(\w+)", code, re.MULTILINE):
            exports.add(m.group(1))
        return exports

