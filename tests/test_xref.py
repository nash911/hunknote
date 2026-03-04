"""Tests for the language-specific import cross-reference builder (xref.py).

Tests cover:
- Per-language import candidate extraction
- Multi-language cross-reference generation
- File-path-to-module conversion
"""

import pytest

from hunknote.compose.agents.xref import (
    _file_path_to_modules,
    _handle_c_cpp,
    _handle_csharp,
    _handle_fallback,
    _handle_go,
    _handle_java,
    _handle_python,
    _handle_ruby,
    _handle_rust,
    _handle_swift,
    _handle_typescript,
    build_import_xref,
)
from hunknote.compose.models import FileDiff, HunkRef, HunkSymbols


# ============================================================
# Python handler tests
# ============================================================

class TestPythonHandler:
    """Tests for _handle_python."""

    def test_fully_qualified_import(self):
        result = _handle_python("hunknote.compose.agents.base.BaseSubAgent")
        assert "BaseSubAgent" in result
        assert "base" in result

    def test_module_only_import(self):
        result = _handle_python("hunknote.compose.agents.base")
        assert "base" in result
        assert "agents" in result

    def test_single_token_import(self):
        result = _handle_python("os")
        assert "os" in result

    def test_two_part_import(self):
        result = _handle_python("os.path")
        assert "path" in result
        assert "os" in result

    def test_stdlib_import(self):
        result = _handle_python("json")
        assert "json" in result

    def test_deep_import(self):
        result = _handle_python("a.b.c.d.e.MyClass")
        assert "MyClass" in result
        assert "e" in result


# ============================================================
# TypeScript/JavaScript handler tests
# ============================================================

class TestTypeScriptHandler:
    """Tests for _handle_typescript."""

    def test_package_import(self):
        result = _handle_typescript("react")
        assert "react" in result

    def test_scoped_package(self):
        result = _handle_typescript("@/utils/helpers")
        assert "helpers" in result
        assert "utils" in result

    def test_relative_import(self):
        result = _handle_typescript("./models/User")
        assert "User" in result
        assert "models" in result

    def test_parent_import(self):
        result = _handle_typescript("../components/Button")
        assert "Button" in result
        assert "components" in result

    def test_deep_path(self):
        result = _handle_typescript("lodash/debounce")
        assert "debounce" in result

    def test_index_file(self):
        result = _handle_typescript("./utils")
        assert "utils" in result

    def test_scoped_npm_package(self):
        result = _handle_typescript("@angular/core")
        assert "core" in result


# ============================================================
# Go handler tests
# ============================================================

class TestGoHandler:
    """Tests for _handle_go."""

    def test_stdlib_package(self):
        result = _handle_go("fmt")
        assert "fmt" in result

    def test_multi_part(self):
        result = _handle_go("net/http")
        assert "http" in result
        assert "net" in result

    def test_github_import(self):
        result = _handle_go("github.com/user/repo/pkg/handler")
        assert "handler" in result
        assert "pkg" in result

    def test_internal_package(self):
        result = _handle_go("myapp/internal/db")
        assert "db" in result


# ============================================================
# Rust handler tests
# ============================================================

class TestRustHandler:
    """Tests for _handle_rust."""

    def test_crate_path(self):
        result = _handle_rust("crate::models::User")
        assert "User" in result
        assert "models" in result

    def test_std_path(self):
        result = _handle_rust("std::collections::HashMap")
        assert "HashMap" in result
        assert "collections" in result

    def test_super_path(self):
        result = _handle_rust("super::utils")
        assert "utils" in result

    def test_self_path(self):
        result = _handle_rust("self::config")
        assert "config" in result

    def test_dot_separated(self):
        """Fallback for dot-separated notation."""
        result = _handle_rust("serde.Serialize")
        assert "Serialize" in result


# ============================================================
# Ruby handler tests
# ============================================================

class TestRubyHandler:
    """Tests for _handle_ruby."""

    def test_simple_require(self):
        result = _handle_ruby("json")
        assert "json" in result

    def test_path_require(self):
        result = _handle_ruby("models/user")
        assert "user" in result
        assert "models" in result

    def test_deep_require(self):
        result = _handle_ruby("active_support/core_ext/string")
        assert "string" in result
        assert "core_ext" in result


# ============================================================
# Java/Kotlin handler tests
# ============================================================

class TestJavaHandler:
    """Tests for _handle_java."""

    def test_simple_import(self):
        result = _handle_java("java.util.List")
        assert "List" in result
        assert "util" in result

    def test_custom_import(self):
        result = _handle_java("com.example.models.User")
        assert "User" in result
        assert "models" in result

    def test_kotlin_import(self):
        result = _handle_java("kotlinx.coroutines.flow.Flow")
        assert "Flow" in result
        assert "flow" in result


# ============================================================
# C/C++ handler tests
# ============================================================

class TestCCppHandler:
    """Tests for _handle_c_cpp."""

    def test_std_header(self):
        result = _handle_c_cpp("stdio.h")
        assert "stdio" in result

    def test_path_header(self):
        result = _handle_c_cpp("mylib/utils.h")
        assert "utils" in result
        assert "mylib" in result

    def test_no_extension(self):
        result = _handle_c_cpp("vector")
        assert "vector" in result

    def test_angle_brackets(self):
        result = _handle_c_cpp("<iostream>")
        assert "iostream" in result

    def test_boost_header(self):
        result = _handle_c_cpp("boost/algorithm/string.hpp")
        assert "string" in result
        assert "algorithm" in result


# ============================================================
# C# handler tests
# ============================================================

class TestCSharpHandler:
    """Tests for _handle_csharp."""

    def test_system_namespace(self):
        result = _handle_csharp("System.Collections.Generic")
        assert "Generic" in result
        assert "Collections" in result

    def test_custom_namespace(self):
        result = _handle_csharp("MyApp.Models.User")
        assert "User" in result


# ============================================================
# Swift handler tests
# ============================================================

class TestSwiftHandler:
    """Tests for _handle_swift."""

    def test_single_import(self):
        result = _handle_swift("Foundation")
        assert "Foundation" in result

    def test_submodule(self):
        result = _handle_swift("MyModule.SubModule")
        assert "SubModule" in result
        assert "MyModule" in result


# ============================================================
# Fallback handler tests
# ============================================================

class TestFallbackHandler:
    """Tests for _handle_fallback."""

    def test_dot_separated(self):
        result = _handle_fallback("a.b.c")
        assert "c" in result
        assert "b" in result

    def test_slash_separated(self):
        result = _handle_fallback("a/b/c")
        assert "c" in result
        assert "b" in result

    def test_double_colon(self):
        result = _handle_fallback("a::b::c")
        assert "c" in result
        assert "b" in result

    def test_single_token(self):
        result = _handle_fallback("something")
        assert "something" in result

    def test_empty_string(self):
        result = _handle_fallback("")
        assert result == []


# ============================================================
# File path to modules tests
# ============================================================

class TestFilePathToModules:
    """Tests for _file_path_to_modules."""

    def test_python_file(self):
        mods = _file_path_to_modules("src/models.py")
        assert "src.models" in mods
        assert "src/models" in mods

    def test_python_init(self):
        mods = _file_path_to_modules("src/utils/__init__.py")
        assert "src/utils" in mods
        assert "src.utils" in mods

    def test_typescript_file(self):
        mods = _file_path_to_modules("src/utils/helpers.ts")
        assert "src/utils/helpers" in mods
        assert "src.utils.helpers" in mods

    def test_typescript_index(self):
        mods = _file_path_to_modules("src/utils/index.ts")
        assert "src/utils" in mods

    def test_go_file(self):
        mods = _file_path_to_modules("pkg/handler.go")
        assert "pkg/handler" in mods

    def test_rust_lib(self):
        mods = _file_path_to_modules("src/lib.rs")
        assert "src" in mods

    def test_c_header(self):
        mods = _file_path_to_modules("include/mylib/utils.h")
        assert "include/mylib/utils" in mods
        assert "include.mylib.utils" in mods

    def test_java_file(self):
        mods = _file_path_to_modules("com/example/models/User.java")
        assert "com.example.models.User" in mods
        assert "com/example/models/User" in mods


# ============================================================
# Full cross-reference builder integration tests
# ============================================================

class TestBuildImportXref:
    """Integration tests for build_import_xref."""

    def test_python_cross_reference(self):
        """Python: dotted imports match last-segment definitions."""
        analyses = {
            "H1": HunkSymbols(
                file_path="src/models.py", language="python",
                defines={"User", "Address"},
                exports_added={"User"},
            ),
            "H2": HunkSymbols(
                file_path="src/api.py", language="python",
                imports_added={"src.models.User"},
                references={"User"},
            ),
        }
        diffs = [
            FileDiff(file_path="src/models.py", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H1", file_path="src/models.py",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])],
                     is_new_file=True),
            FileDiff(file_path="src/api.py", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H2", file_path="src/api.py",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])]),
        ]

        result = build_import_xref(analyses, diffs)
        assert "H2" in result
        assert "User" in result
        assert "H1" in result

    def test_typescript_cross_reference(self):
        """TypeScript: slash-based imports match definitions."""
        analyses = {
            "H1": HunkSymbols(
                file_path="src/models/User.ts", language="typescript",
                defines={"User", "UserType"},
            ),
            "H2": HunkSymbols(
                file_path="src/api/routes.ts", language="typescript",
                imports_added={"./models/User"},
            ),
        }
        diffs = [
            FileDiff(file_path="src/models/User.ts", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H1", file_path="src/models/User.ts",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])],
                     is_new_file=True),
            FileDiff(file_path="src/api/routes.ts", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H2", file_path="src/api/routes.ts",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])]),
        ]

        result = build_import_xref(analyses, diffs)
        assert "H2" in result
        assert "User" in result

    def test_go_cross_reference(self):
        """Go: package imports match definitions."""
        analyses = {
            "H1": HunkSymbols(
                file_path="pkg/handler/handler.go", language="go",
                defines={"HandleRequest", "NewHandler"},
            ),
            "H2": HunkSymbols(
                file_path="cmd/server/main.go", language="go",
                imports_added={"myapp/pkg/handler"},
            ),
        }
        diffs = [
            FileDiff(file_path="pkg/handler/handler.go", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H1", file_path="pkg/handler/handler.go",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])],
                     is_new_file=True),
            FileDiff(file_path="cmd/server/main.go", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H2", file_path="cmd/server/main.go",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])]),
        ]

        result = build_import_xref(analyses, diffs)
        # Should match 'handler' from the import path to the 'handler' directory
        assert "H2" in result or "handler" in result

    def test_rust_cross_reference(self):
        """Rust: crate::path imports match definitions."""
        analyses = {
            "H1": HunkSymbols(
                file_path="src/models.rs", language="rust",
                defines={"User", "Config"},
            ),
            "H2": HunkSymbols(
                file_path="src/api.rs", language="rust",
                imports_added={"crate::models::User"},
            ),
        }
        diffs = [
            FileDiff(file_path="src/models.rs", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H1", file_path="src/models.rs",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])],
                     is_new_file=True),
            FileDiff(file_path="src/api.rs", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H2", file_path="src/api.rs",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])]),
        ]

        result = build_import_xref(analyses, diffs)
        assert "H2" in result
        assert "User" in result

    def test_java_cross_reference(self):
        """Java: fully qualified imports match class definitions."""
        analyses = {
            "H1": HunkSymbols(
                file_path="com/example/models/User.java", language="java",
                defines={"User"},
            ),
            "H2": HunkSymbols(
                file_path="com/example/api/UserService.java", language="java",
                imports_added={"com.example.models.User"},
            ),
        }
        diffs = [
            FileDiff(file_path="com/example/models/User.java", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H1", file_path="com/example/models/User.java",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])],
                     is_new_file=True),
            FileDiff(file_path="com/example/api/UserService.java", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H2", file_path="com/example/api/UserService.java",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])]),
        ]

        result = build_import_xref(analyses, diffs)
        assert "H2" in result
        assert "User" in result

    def test_no_dependencies(self):
        """Two independent hunks produce 'no cross-references' message."""
        analyses = {
            "H1": HunkSymbols(
                file_path="a.py", language="python", defines={"Foo"},
            ),
            "H2": HunkSymbols(
                file_path="b.py", language="python", defines={"Bar"},
            ),
        }
        diffs = [
            FileDiff(file_path="a.py", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H1", file_path="a.py", header="@@",
                                    old_start=1, old_len=1, new_start=1,
                                    new_len=1, lines=[])]),
            FileDiff(file_path="b.py", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H2", file_path="b.py", header="@@",
                                    old_start=1, old_len=1, new_start=1,
                                    new_len=1, lines=[])]),
        ]

        result = build_import_xref(analyses, diffs)
        assert "No direct cross-references" in result

    def test_new_file_module_path_matching(self):
        """Imports from a new file match via module path."""
        analyses = {
            "H1": HunkSymbols(
                file_path="hunknote/compose/agents/base.py", language="python",
                defines={"BaseSubAgent", "SubAgentResult"},
            ),
            "H2": HunkSymbols(
                file_path="hunknote/compose/agents/analyzer.py", language="python",
                imports_added={"hunknote.compose.agents.base.BaseSubAgent"},
            ),
        }
        diffs = [
            FileDiff(file_path="hunknote/compose/agents/base.py",
                     diff_header_lines=["d"],
                     hunks=[HunkRef(id="H1",
                                    file_path="hunknote/compose/agents/base.py",
                                    header="@@", old_start=1, old_len=0,
                                    new_start=1, new_len=10, lines=[])],
                     is_new_file=True),
            FileDiff(file_path="hunknote/compose/agents/analyzer.py",
                     diff_header_lines=["d"],
                     hunks=[HunkRef(id="H2",
                                    file_path="hunknote/compose/agents/analyzer.py",
                                    header="@@", old_start=1, old_len=0,
                                    new_start=1, new_len=10, lines=[])],
                     is_new_file=True),
        ]

        result = build_import_xref(analyses, diffs)
        assert "H2" in result
        assert "H1" in result
        # Should match either by symbol name or by module path
        assert "BaseSubAgent" in result or "base.py" in result

    def test_mixed_languages(self):
        """Cross-references work across files with different languages."""
        analyses = {
            "H1": HunkSymbols(
                file_path="src/models.py", language="python",
                defines={"UserModel"},
            ),
            "H2": HunkSymbols(
                file_path="tests/test_models.py", language="python",
                imports_added={"src.models.UserModel"},
            ),
            "H3": HunkSymbols(
                file_path="docs/api.md", language="markdown",
            ),
        }
        diffs = [
            FileDiff(file_path="src/models.py", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H1", file_path="src/models.py",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])],
                     is_new_file=True),
            FileDiff(file_path="tests/test_models.py", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H2", file_path="tests/test_models.py",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])]),
            FileDiff(file_path="docs/api.md", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H3", file_path="docs/api.md",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])]),
        ]

        result = build_import_xref(analyses, diffs)
        assert "H2" in result
        assert "UserModel" in result

    def test_c_cpp_cross_reference(self):
        """C/C++: include paths match header definitions."""
        analyses = {
            "H1": HunkSymbols(
                file_path="include/mylib/utils.h", language="c",
                defines={"my_function", "MyStruct"},
            ),
            "H2": HunkSymbols(
                file_path="src/main.c", language="c",
                imports_added={"mylib/utils.h"},
            ),
        }
        diffs = [
            FileDiff(file_path="include/mylib/utils.h", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H1", file_path="include/mylib/utils.h",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])],
                     is_new_file=True),
            FileDiff(file_path="src/main.c", diff_header_lines=["d"],
                     hunks=[HunkRef(id="H2", file_path="src/main.c",
                                    header="@@", old_start=1, old_len=1,
                                    new_start=1, new_len=1, lines=[])]),
        ]

        result = build_import_xref(analyses, diffs)
        # Should match 'utils' from the include path
        assert "H2" in result
        assert "utils" in result or "mylib" in result

