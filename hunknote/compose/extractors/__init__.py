"""Symbol extractor registry for Hunknote Compose Agent.

Provides a pluggable registry of language-specific symbol extractors,
all conforming to the SymbolExtractor interface.

Tiers:
- Tier 1 (AST-based): Python — highest accuracy
- Tier 2 (Regex-based): JS/TS, Go, Rust, Java, Kotlin, Ruby, C/C++, C#, Swift, PHP
- Tier 3 (Universal fallback): Any language with recognisable keywords
- Tier 4 (LLM fallback): Handled at agent level, not in this registry
"""

from hunknote.compose.extractors.base import SymbolExtractor, SymbolSet
from hunknote.compose.extractors.python_extractor import PythonExtractor
from hunknote.compose.extractors.js_ts_extractor import JavaScriptExtractor, TypeScriptExtractor
from hunknote.compose.extractors.go_extractor import GoExtractor
from hunknote.compose.extractors.rust_extractor import RustExtractor
from hunknote.compose.extractors.java_kotlin_extractor import JavaExtractor, KotlinExtractor
from hunknote.compose.extractors.ruby_extractor import RubyExtractor
from hunknote.compose.extractors.c_cpp_extractor import CExtractor, CppExtractor
from hunknote.compose.extractors.csharp_extractor import CSharpExtractor
from hunknote.compose.extractors.swift_extractor import SwiftExtractor
from hunknote.compose.extractors.php_extractor import PHPExtractor
from hunknote.compose.extractors.universal_extractor import UniversalFallbackExtractor
from hunknote.compose.extractors.noncode_extractor import (
    ProtobufExtractor,
    GraphQLExtractor,
    YAMLExtractor,
    JSONExtractor,
    TOMLExtractor,
    SQLExtractor,
    DockerfileExtractor,
    CIConfigExtractor,
    MakefileExtractor,
)


# Registry: file extension → extractor instance
EXTRACTORS: dict[str, SymbolExtractor] = {
    # Tier 1: AST-based
    ".py": PythonExtractor(),
    # Tier 2: Regex-based
    ".js": JavaScriptExtractor(),
    ".jsx": JavaScriptExtractor(),
    ".ts": TypeScriptExtractor(),
    ".tsx": TypeScriptExtractor(),
    ".go": GoExtractor(),
    ".rs": RustExtractor(),
    ".java": JavaExtractor(),
    ".kt": KotlinExtractor(),
    ".rb": RubyExtractor(),
    ".c": CExtractor(),
    ".cpp": CppExtractor(),
    ".cc": CppExtractor(),
    ".h": CExtractor(),
    ".hpp": CppExtractor(),
    ".cs": CSharpExtractor(),
    ".swift": SwiftExtractor(),
    ".php": PHPExtractor(),
    # Non-code
    ".proto": ProtobufExtractor(),
    ".graphql": GraphQLExtractor(),
    ".gql": GraphQLExtractor(),
    ".yaml": YAMLExtractor(),
    ".yml": YAMLExtractor(),
    ".json": JSONExtractor(),
    ".toml": TOMLExtractor(),
    ".sql": SQLExtractor(),
    "Dockerfile": DockerfileExtractor(),
    "Makefile": MakefileExtractor(),
    "CMakeLists.txt": MakefileExtractor(),
}

# Universal fallback for unknown extensions
_FALLBACK = UniversalFallbackExtractor()


def get_extractor(file_path: str) -> SymbolExtractor:
    """Get the appropriate extractor for a file path.

    Checks basename first (for Dockerfile, Makefile), then extension.
    Falls back to UniversalFallbackExtractor for unknown types.

    Args:
        file_path: Path to the file (can be relative or absolute).

    Returns:
        The matching SymbolExtractor instance.
    """
    import os
    basename = os.path.basename(file_path)

    # Check basename first (Dockerfile, Makefile, CMakeLists.txt)
    if basename in EXTRACTORS:
        return EXTRACTORS[basename]

    # Check extension
    _, ext = os.path.splitext(file_path)
    if ext in EXTRACTORS:
        return EXTRACTORS[ext]

    return _FALLBACK


__all__ = [
    "SymbolExtractor",
    "SymbolSet",
    "EXTRACTORS",
    "get_extractor",
    "PythonExtractor",
    "JavaScriptExtractor",
    "TypeScriptExtractor",
    "GoExtractor",
    "RustExtractor",
    "JavaExtractor",
    "KotlinExtractor",
    "RubyExtractor",
    "CExtractor",
    "CppExtractor",
    "CSharpExtractor",
    "SwiftExtractor",
    "PHPExtractor",
    "UniversalFallbackExtractor",
]

