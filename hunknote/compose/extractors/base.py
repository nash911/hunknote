"""Base class and utilities for symbol extractors.

Provides:
- SymbolExtractor: Abstract base class for language-specific extractors
- SymbolSet: Container for extracted symbols from a code fragment
- is_module_scope: Indentation-based heuristic for scope detection
- DEFINITION_KEYWORDS: Common definition keywords across languages
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SymbolSet:
    """Symbols extracted from a code fragment."""

    definitions: set[str] = field(default_factory=set)
    references: set[str] = field(default_factory=set)
    imports: set[str] = field(default_factory=set)
    exports: set[str] = field(default_factory=set)


# Keywords that typically introduce a definition in most languages
DEFINITION_KEYWORDS = frozenset({
    "def", "fn", "func", "function", "fun",
    "class", "struct", "type", "interface", "enum",
    "trait", "impl", "module", "protocol", "record",
    "const", "var", "let", "val", "static",
    "pub", "export", "public", "private", "protected",
    "async", "abstract", "virtual", "override",
})

# Regex for extracting the identifier after a definition keyword
_DEFINITION_IDENT_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?(?:async\s+)?"
    r"(?:pub(?:\s*\([^)]*\))?\s+)?"
    r"(?:static\s+)?(?:final\s+)?(?:override\s+)?"
    r"(?:def|fn|func|function|fun|class|struct|type|interface|enum|"
    r"trait|impl|module|protocol|record|const|var|let|val)\s+"
    r"(\w+)",
    re.MULTILINE,
)


def is_module_scope(line: str, language: str = "") -> bool:
    """Check if a line is at module/file scope (not inside a function body).

    Works for Python, Go, Rust, Ruby, Java, TypeScript, and most
    indentation-based or brace-based languages.

    Args:
        line: The raw line of code (with original indentation).
        language: Optional language hint for more accurate detection.

    Returns:
        True if the line appears to be at module/file scope.
    """
    stripped = line.lstrip()
    indent = len(line) - len(stripped)

    # At column 0 — almost always module scope
    if indent == 0:
        return True

    # For class-based languages, indent level 1 (inside a class body)
    # is still effectively "module scope" for method definitions
    if indent <= 4 and _is_definition_keyword(stripped, language):
        return True

    return False


def _is_definition_keyword(stripped_line: str, language: str = "") -> bool:
    """Check if a stripped line starts with a definition keyword.

    Args:
        stripped_line: Line with leading whitespace removed.
        language: Optional language hint.

    Returns:
        True if the line starts with a definition keyword.
    """
    # Check the first word
    first_word = stripped_line.split("(")[0].split("{")[0].split(":")[0].split("=")[0]
    words = first_word.split()
    if not words:
        return False

    # Check if any of the first few words is a definition keyword
    for word in words[:4]:
        if word.lower().rstrip("(") in DEFINITION_KEYWORDS:
            return True
    return False


class SymbolExtractor(ABC):
    """Abstract base class for language-specific symbol extractors.

    Each extractor analyses source code fragments (typically the +/- lines
    from a diff hunk) and extracts module-scope symbols.
    """

    @abstractmethod
    def extract_definitions(self, code: str) -> set[str]:
        """Extract symbol definitions (function, class, variable, type names).

        Only module-scope definitions should be returned. Local variables
        inside function bodies must be excluded.

        Args:
            code: Source code fragment to analyse.

        Returns:
            Set of defined symbol names.
        """

    @abstractmethod
    def extract_references(self, code: str) -> set[str]:
        """Extract symbol references (identifiers used, not defined here).

        Should focus on function/method calls and type references.
        Local variable references should be excluded.

        Args:
            code: Source code fragment to analyse.

        Returns:
            Set of referenced symbol names.
        """

    @abstractmethod
    def extract_imports(self, code: str) -> set[str]:
        """Extract import/require/include statements.

        Args:
            code: Source code fragment to analyse.

        Returns:
            Set of imported module/symbol paths.
        """

    @abstractmethod
    def extract_exports(self, code: str) -> set[str]:
        """Extract exported symbols (module.exports, export, pub, etc.).

        Args:
            code: Source code fragment to analyse.

        Returns:
            Set of exported symbol names.
        """

    def extract_all(self, code: str) -> SymbolSet:
        """Extract all symbol categories from the code fragment.

        This is the primary entry point. Calls all four extraction methods
        and returns a unified SymbolSet.

        Args:
            code: Source code fragment to analyse.

        Returns:
            SymbolSet containing all extracted symbols.
        """
        return SymbolSet(
            definitions=self.extract_definitions(code),
            references=self.extract_references(code),
            imports=self.extract_imports(code),
            exports=self.extract_exports(code),
        )

