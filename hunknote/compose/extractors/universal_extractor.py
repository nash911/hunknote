"""Universal fallback symbol extractor — Tier 3.

Applies language-agnostic heuristics to extract symbols from any language.
Uses common definition keywords (def, fn, func, function, class, struct, etc.)
and import patterns (import, require, use, include, from, #include).
"""

import re

from hunknote.compose.extractors.base import SymbolExtractor, is_module_scope


class UniversalFallbackExtractor(SymbolExtractor):
    """Universal fallback extractor for unknown/unsupported languages.

    Uses language-agnostic keyword patterns to extract the most important
    symbols: function/class definitions and imports.
    """

    # Definition patterns (language-agnostic)
    _DEF_PATTERNS = [
        # function/method: def/fn/func/function/fun name
        re.compile(
            r"^\s*(?:export\s+)?(?:pub(?:\s*\([^)]*\))?\s+)?(?:async\s+)?"
            r"(?:def|fn|func|function|fun)\s+(\w+)",
            re.MULTILINE,
        ),
        # class/struct/type/interface/enum/trait/module/protocol
        re.compile(
            r"^\s*(?:export\s+)?(?:pub(?:\s*\([^)]*\))?\s+)?(?:abstract\s+)?"
            r"(?:class|struct|type|interface|enum|trait|module|protocol|record)\s+(\w+)",
            re.MULTILINE,
        ),
    ]

    # Import patterns (language-agnostic)
    _IMPORT_PATTERNS = [
        re.compile(r"""^\s*import\s+['"]?([^'";\s]+)""", re.MULTILINE),
        re.compile(r"""^\s*from\s+([\w.]+)\s+import""", re.MULTILINE),
        re.compile(r"""^\s*require\s*\(?\s*['"]([^'"]+)['"]""", re.MULTILINE),
        re.compile(r"""^\s*(?:use|include)\s+([\w.:\/]+)""", re.MULTILINE),
        re.compile(r"""^\s*#include\s+[<"]([^>"]+)[>"]""", re.MULTILINE),
    ]

    # Top-level assignment (const/var/let at column 0)
    _ASSIGN_PATTERN = re.compile(
        r"^\s*(?:export\s+)?(?:const|var|let|val)\s+(\w+)\s*[:=]",
        re.MULTILINE,
    )

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        for pattern in self._DEF_PATTERNS:
            for m in pattern.finditer(code):
                if is_module_scope(code.splitlines()[code[:m.start()].count("\n")] if "\n" in code[:m.start()] else code):
                    definitions.add(m.group(1))
        # Top-level assignments
        for m in self._ASSIGN_PATTERN.finditer(code):
            line = code.splitlines()[code[:m.start()].count("\n")] if "\n" in code[:m.start()] else code
            if is_module_scope(line):
                definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        # Minimal: only extract function calls
        references: set[str] = set()
        for m in re.finditer(r"(\w+)\s*\(", code):
            name = m.group(1)
            # Skip common keywords across all languages
            if name not in {"if", "for", "while", "switch", "case", "return",
                            "def", "fn", "func", "function", "fun",
                            "class", "struct", "type", "interface", "enum",
                            "import", "require", "use", "include", "from",
                            "const", "var", "let", "val", "new",
                            "true", "false", "null", "nil", "None",
                            "print", "println", "printf", "console", "echo"}:
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
        # Match "export function/class/const/let/var name"
        for m in re.finditer(
            r"^\s*export\s+(?:default\s+)?(?:function|class|const|let|var|type|interface|enum)\s+(\w+)",
            code, re.MULTILINE,
        ):
            exports.add(m.group(1))
        # Match "pub fn/struct/enum/trait name" (Rust-style)
        for m in re.finditer(
            r"^\s*pub(?:\s*\([^)]*\))?\s+(?:fn|struct|enum|trait|type|const|static|mod)\s+(\w+)",
            code, re.MULTILINE,
        ):
            exports.add(m.group(1))
        return exports

