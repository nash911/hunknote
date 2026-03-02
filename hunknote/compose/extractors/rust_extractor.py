"""Rust symbol extractor — Tier 2 (regex-based).

Handles: fn, struct, enum, trait, impl, type, const, mod, use, pub.
"""

import re

from hunknote.compose.extractors.base import SymbolExtractor


class RustExtractor(SymbolExtractor):
    """Regex-based symbol extractor for Rust."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # fn name / pub fn name / pub(crate) fn name / async fn name
        for m in re.finditer(
            r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(\w+)",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        # struct, enum, trait, type alias
        for m in re.finditer(
            r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?(?:struct|enum|trait|union)\s+(\w+)",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        # type Name = ...
        for m in re.finditer(
            r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?type\s+(\w+)\s*=",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        # const / static
        for m in re.finditer(
            r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?(?:const|static)\s+(\w+)",
            code, re.MULTILINE,
        ):
            definitions.add(m.group(1))
        # mod name
        for m in re.finditer(r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?mod\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # impl Name
        for m in re.finditer(r"^\s*impl(?:<[^>]*>)?\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        references: set[str] = set()
        # Function/method calls
        for m in re.finditer(r"(\w+)\s*[\(<]", code):
            name = m.group(1)
            if name not in {"if", "else", "for", "while", "loop", "match",
                            "let", "mut", "fn", "pub", "use", "mod", "impl",
                            "struct", "enum", "trait", "type", "const", "static",
                            "return", "break", "continue", "as", "in",
                            "Some", "None", "Ok", "Err", "true", "false",
                            "self", "Self", "super", "crate", "where",
                            "unsafe", "async", "await", "move", "ref", "dyn",
                            "Vec", "Box", "Arc", "Rc", "String", "HashMap",
                            "HashSet", "Option", "Result", "println", "print",
                            "format", "panic", "unreachable", "todo", "dbg"}:
                references.add(name)
        return references

    def extract_imports(self, code: str) -> set[str]:
        imports: set[str] = set()
        # use crate::path::to::module
        for m in re.finditer(r"^\s*use\s+([\w:]+)", code, re.MULTILINE):
            imports.add(m.group(1))
        # mod name; (external module import)
        for m in re.finditer(r"^\s*mod\s+(\w+)\s*;", code, re.MULTILINE):
            imports.add(m.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        exports: set[str] = set()
        # pub fn/struct/enum/trait/type/const/static
        for m in re.finditer(
            r"^\s*pub(?:\s*\([^)]*\))?\s+(?:async\s+)?(?:unsafe\s+)?"
            r"(?:fn|struct|enum|trait|union|type|const|static|mod)\s+(\w+)",
            code, re.MULTILINE,
        ):
            exports.add(m.group(1))
        return exports

