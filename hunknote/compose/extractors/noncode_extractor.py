"""Non-code file symbol extractors.

Extractors for protobuf, GraphQL, YAML, JSON, TOML, SQL, Dockerfile,
CI configs, and Makefiles.
"""

import re

from hunknote.compose.extractors.base import SymbolExtractor


class ProtobufExtractor(SymbolExtractor):
    """Extractor for Protocol Buffer (.proto) files."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        for m in re.finditer(r"^\s*(?:message|enum|service)\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # RPC methods
        for m in re.finditer(r"^\s*rpc\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # Field names
        for m in re.finditer(r"^\s*(?:optional|required|repeated)?\s*\w+\s+(\w+)\s*=\s*\d+", code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        return set()

    def extract_imports(self, code: str) -> set[str]:
        imports: set[str] = set()
        for m in re.finditer(r"""^\s*import\s+['"]([^'"]+)['"]""", code, re.MULTILINE):
            imports.add(m.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        return set()


class GraphQLExtractor(SymbolExtractor):
    """Extractor for GraphQL schema files."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        for m in re.finditer(r"^\s*(?:type|input|enum|interface|union|scalar)\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # Query/Mutation/Subscription field names
        for m in re.finditer(r"^\s+(\w+)\s*[\(:]", code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        return set()

    def extract_imports(self, code: str) -> set[str]:
        return set()

    def extract_exports(self, code: str) -> set[str]:
        return set()


class YAMLExtractor(SymbolExtractor):
    """Extractor for YAML configuration files."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # Top-level keys (no indentation)
        for m in re.finditer(r"^(\w[\w.-]*)\s*:", code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        return set()

    def extract_imports(self, code: str) -> set[str]:
        return set()

    def extract_exports(self, code: str) -> set[str]:
        return set()


class JSONExtractor(SymbolExtractor):
    """Extractor for JSON configuration files."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # Top-level keys (minimal indentation)
        for m in re.finditer(r'^\s{0,2}"(\w+)"\s*:', code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        return set()

    def extract_imports(self, code: str) -> set[str]:
        return set()

    def extract_exports(self, code: str) -> set[str]:
        return set()


class TOMLExtractor(SymbolExtractor):
    """Extractor for TOML configuration files."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # Section headers: [section] or [section.subsection]
        for m in re.finditer(r"^\[([^\]]+)\]", code, re.MULTILINE):
            definitions.add(m.group(1))
        # Top-level keys
        for m in re.finditer(r"^(\w[\w-]*)\s*=", code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        return set()

    def extract_imports(self, code: str) -> set[str]:
        return set()

    def extract_exports(self, code: str) -> set[str]:
        return set()


class SQLExtractor(SymbolExtractor):
    """Extractor for SQL migration/schema files."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # CREATE TABLE/INDEX/VIEW name
        for m in re.finditer(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|INDEX|VIEW|FUNCTION|PROCEDURE|TRIGGER)\s+"
            r"(?:IF\s+NOT\s+EXISTS\s+)?(?:\w+\.)?(\w+)",
            code, re.IGNORECASE | re.MULTILINE,
        ):
            definitions.add(m.group(1))
        # ALTER TABLE name
        for m in re.finditer(r"ALTER\s+TABLE\s+(?:\w+\.)?(\w+)", code, re.IGNORECASE):
            definitions.add(m.group(1))
        # ADD COLUMN name
        for m in re.finditer(r"ADD\s+(?:COLUMN\s+)?(\w+)\s+\w+", code, re.IGNORECASE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        return set()

    def extract_imports(self, code: str) -> set[str]:
        return set()

    def extract_exports(self, code: str) -> set[str]:
        return set()


class DockerfileExtractor(SymbolExtractor):
    """Extractor for Dockerfiles."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # FROM ... AS stage_name
        for m in re.finditer(r"^\s*FROM\s+\S+\s+AS\s+(\w+)", code, re.MULTILINE | re.IGNORECASE):
            definitions.add(m.group(1))
        # EXPOSE port
        for m in re.finditer(r"^\s*EXPOSE\s+(\d+)", code, re.MULTILINE):
            definitions.add(f"port_{m.group(1)}")
        # ENV key
        for m in re.finditer(r"^\s*ENV\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        # ARG key
        for m in re.finditer(r"^\s*ARG\s+(\w+)", code, re.MULTILINE):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        return set()

    def extract_imports(self, code: str) -> set[str]:
        return set()

    def extract_exports(self, code: str) -> set[str]:
        return set()


class CIConfigExtractor(SymbolExtractor):
    """Extractor for CI configuration files (GitHub Actions, GitLab CI, etc.)."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # Job/step names (YAML keys under specific patterns)
        for m in re.finditer(r"^\s{2,4}(\w[\w-]+)\s*:", code, re.MULTILINE):
            definitions.add(m.group(1))
        # name: "value"
        for m in re.finditer(r"""^\s*(?:name|job_name|step)\s*:\s*['"]?([^'"\n]+)""", code, re.MULTILINE):
            definitions.add(m.group(1).strip())
        return definitions

    def extract_references(self, code: str) -> set[str]:
        return set()

    def extract_imports(self, code: str) -> set[str]:
        return set()

    def extract_exports(self, code: str) -> set[str]:
        return set()


class MakefileExtractor(SymbolExtractor):
    """Extractor for Makefiles and CMakeLists.txt."""

    def extract_definitions(self, code: str) -> set[str]:
        definitions: set[str] = set()
        # Makefile targets: name:
        for m in re.finditer(r"^(\w[\w.-]+)\s*:", code, re.MULTILINE):
            definitions.add(m.group(1))
        # Variable assignments: NAME = / NAME :=
        for m in re.finditer(r"^(\w+)\s*[:?+]?=", code, re.MULTILINE):
            definitions.add(m.group(1))
        # CMake: add_library/add_executable/function/macro
        for m in re.finditer(r"(?:add_library|add_executable|function|macro)\s*\(\s*(\w+)", code):
            definitions.add(m.group(1))
        return definitions

    def extract_references(self, code: str) -> set[str]:
        return set()

    def extract_imports(self, code: str) -> set[str]:
        imports: set[str] = set()
        # CMake: include()
        for m in re.finditer(r"include\s*\(\s*(\w+)", code):
            imports.add(m.group(1))
        # CMake: find_package()
        for m in re.finditer(r"find_package\s*\(\s*(\w+)", code):
            imports.add(m.group(1))
        return imports

    def extract_exports(self, code: str) -> set[str]:
        return set()

