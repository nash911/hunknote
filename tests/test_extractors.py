"""Tests for the symbol extractor registry and language-specific extractors."""

import pytest

from hunknote.compose.extractors import get_extractor, EXTRACTORS
from hunknote.compose.extractors.base import SymbolExtractor, is_module_scope, SymbolSet
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
    ProtobufExtractor, GraphQLExtractor, YAMLExtractor,
    JSONExtractor, TOMLExtractor, SQLExtractor,
    DockerfileExtractor, MakefileExtractor,
)


# ============================================================
# Registry Tests
# ============================================================

class TestExtractorRegistry:
    """Tests for the extractor registry and get_extractor function."""

    def test_python_extension(self):
        ext = get_extractor("src/main.py")
        assert isinstance(ext, PythonExtractor)

    def test_js_extension(self):
        ext = get_extractor("app/index.js")
        assert isinstance(ext, JavaScriptExtractor)

    def test_ts_extension(self):
        ext = get_extractor("src/utils.ts")
        assert isinstance(ext, TypeScriptExtractor)

    def test_tsx_extension(self):
        ext = get_extractor("components/App.tsx")
        assert isinstance(ext, TypeScriptExtractor)

    def test_go_extension(self):
        ext = get_extractor("cmd/server/main.go")
        assert isinstance(ext, GoExtractor)

    def test_rust_extension(self):
        ext = get_extractor("src/lib.rs")
        assert isinstance(ext, RustExtractor)

    def test_java_extension(self):
        ext = get_extractor("com/example/App.java")
        assert isinstance(ext, JavaExtractor)

    def test_kotlin_extension(self):
        ext = get_extractor("app/Main.kt")
        assert isinstance(ext, KotlinExtractor)

    def test_ruby_extension(self):
        ext = get_extractor("lib/app.rb")
        assert isinstance(ext, RubyExtractor)

    def test_c_extension(self):
        ext = get_extractor("src/main.c")
        assert isinstance(ext, CExtractor)

    def test_cpp_extension(self):
        ext = get_extractor("src/app.cpp")
        assert isinstance(ext, CppExtractor)

    def test_header_extension(self):
        ext = get_extractor("include/app.h")
        assert isinstance(ext, CExtractor)

    def test_csharp_extension(self):
        ext = get_extractor("Models/User.cs")
        assert isinstance(ext, CSharpExtractor)

    def test_swift_extension(self):
        ext = get_extractor("Sources/App.swift")
        assert isinstance(ext, SwiftExtractor)

    def test_php_extension(self):
        ext = get_extractor("src/Controller.php")
        assert isinstance(ext, PHPExtractor)

    def test_dockerfile_basename(self):
        ext = get_extractor("Dockerfile")
        assert isinstance(ext, DockerfileExtractor)

    def test_makefile_basename(self):
        ext = get_extractor("Makefile")
        assert isinstance(ext, MakefileExtractor)

    def test_unknown_extension_falls_back(self):
        ext = get_extractor("file.xyz")
        assert isinstance(ext, UniversalFallbackExtractor)

    def test_yaml_extension(self):
        ext = get_extractor("config.yaml")
        assert isinstance(ext, YAMLExtractor)

    def test_json_extension(self):
        ext = get_extractor("package.json")
        assert isinstance(ext, JSONExtractor)

    def test_proto_extension(self):
        ext = get_extractor("api/user.proto")
        assert isinstance(ext, ProtobufExtractor)

    def test_sql_extension(self):
        ext = get_extractor("migrations/001.sql")
        assert isinstance(ext, SQLExtractor)

    def test_all_extractors_implement_interface(self):
        """All registered extractors must implement SymbolExtractor."""
        for ext_key, extractor in EXTRACTORS.items():
            assert isinstance(extractor, SymbolExtractor), f"{ext_key}: {type(extractor)}"


# ============================================================
# Scope Filtering Tests
# ============================================================

class TestScopeFiltering:
    """Tests for is_module_scope() — ensures local variables are excluded."""

    def test_column_zero_is_module_scope(self):
        assert is_module_scope("def my_function():")

    def test_indented_code_not_module_scope(self):
        assert not is_module_scope("        idx = i + 1")

    def test_class_method_definition_is_module_scope(self):
        assert is_module_scope("    def method(self):", "python")

    def test_deeply_indented_not_module_scope(self):
        assert not is_module_scope("            result = compute()")

    def test_class_definition_at_zero(self):
        assert is_module_scope("class MyClass:")

    def test_const_at_zero(self):
        assert is_module_scope("const MAX_RETRIES = 3")

    def test_local_variable_excluded(self):
        assert not is_module_scope("        err = None")

    def test_empty_line(self):
        # Empty line defaults to module scope (col 0)
        assert is_module_scope("")


# ============================================================
# Python Extractor Tests (Tier 1 — AST)
# ============================================================

class TestPythonExtractor:
    """Tests for PythonExtractor (AST-based, Tier 1)."""

    def setup_method(self):
        self.ext = PythonExtractor()

    def test_extract_function_definition(self):
        code = "def rate_limit(key):\n    pass"
        defs = self.ext.extract_definitions(code)
        assert "rate_limit" in defs

    def test_extract_async_function(self):
        code = "async def fetch_data():\n    pass"
        defs = self.ext.extract_definitions(code)
        assert "fetch_data" in defs

    def test_extract_class_definition(self):
        code = "class UserService:\n    pass"
        defs = self.ext.extract_definitions(code)
        assert "UserService" in defs

    def test_extract_module_level_constant(self):
        code = "MAX_RETRIES = 3"
        defs = self.ext.extract_definitions(code)
        assert "MAX_RETRIES" in defs

    def test_extract_import(self):
        code = "import os"
        imports = self.ext.extract_imports(code)
        assert "os" in imports

    def test_extract_from_import(self):
        code = "from pathlib import Path"
        imports = self.ext.extract_imports(code)
        assert "pathlib" in imports

    def test_extract_dotted_import(self):
        code = "from hunknote.compose.models import HunkRef"
        imports = self.ext.extract_imports(code)
        assert "hunknote.compose.models" in imports

    def test_extract_importlib(self):
        code = 'importlib.import_module("my_module")'
        imports = self.ext.extract_imports(code)
        assert "my_module" in imports

    def test_extract_dunder_import(self):
        code = '__import__("dynamic_module")'
        imports = self.ext.extract_imports(code)
        assert "dynamic_module" in imports

    def test_extract_exports_all(self):
        code = '__all__ = ["HunkRef", "FileDiff", "ComposePlan"]'
        exports = self.ext.extract_exports(code)
        assert "HunkRef" in exports
        assert "FileDiff" in exports
        assert "ComposePlan" in exports

    def test_extract_function_calls(self):
        code = "result = compute_hash(data)"
        refs = self.ext.extract_references(code)
        assert "compute_hash" in refs

    def test_no_local_variable_definitions(self):
        """Local variables inside function bodies should NOT be extracted."""
        code = "def outer():\n    idx = 0\n    result = compute()"
        defs = self.ext.extract_definitions(code)
        assert "idx" not in defs
        assert "result" not in defs
        assert "outer" in defs

    def test_syntax_error_fallback(self):
        """Invalid Python should fall back to regex."""
        code = "def my_func(\n  # broken"
        defs = self.ext.extract_definitions(code)
        assert "my_func" in defs

    def test_annotated_assignment(self):
        code = "MAX_SIZE: int = 100"
        defs = self.ext.extract_definitions(code)
        assert "MAX_SIZE" in defs


# ============================================================
# JavaScript / TypeScript Extractor Tests (Tier 2)
# ============================================================

class TestJavaScriptExtractor:
    """Tests for JavaScriptExtractor."""

    def setup_method(self):
        self.ext = JavaScriptExtractor()

    def test_function_definition(self):
        code = "function handleRequest(req, res) {}"
        defs = self.ext.extract_definitions(code)
        assert "handleRequest" in defs

    def test_const_definition(self):
        code = "const MAX_RETRIES = 5;"
        defs = self.ext.extract_definitions(code)
        assert "MAX_RETRIES" in defs

    def test_class_definition(self):
        code = "class UserController {}"
        defs = self.ext.extract_definitions(code)
        assert "UserController" in defs

    def test_export_function(self):
        code = "export function formatDate(d) {}"
        exports = self.ext.extract_exports(code)
        assert "formatDate" in exports

    def test_import_from(self):
        code = "import { useState } from 'react';"
        imports = self.ext.extract_imports(code)
        assert "react" in imports

    def test_require(self):
        code = "const fs = require('fs');"
        imports = self.ext.extract_imports(code)
        assert "fs" in imports

    def test_references(self):
        code = "const result = calculateTotal(items);"
        refs = self.ext.extract_references(code)
        assert "calculateTotal" in refs


class TestTypeScriptExtractor:
    """Tests for TypeScriptExtractor (extends JavaScript)."""

    def setup_method(self):
        self.ext = TypeScriptExtractor()

    def test_interface_definition(self):
        code = "interface UserConfig {}"
        defs = self.ext.extract_definitions(code)
        assert "UserConfig" in defs

    def test_type_alias(self):
        code = "type ResponseData = { status: number };"
        defs = self.ext.extract_definitions(code)
        assert "ResponseData" in defs

    def test_enum_definition(self):
        code = "enum Status { Active, Inactive }"
        defs = self.ext.extract_definitions(code)
        assert "Status" in defs

    def test_export_interface(self):
        code = "export interface Config {}"
        defs = self.ext.extract_definitions(code)
        assert "Config" in defs


# ============================================================
# Go Extractor Tests (Tier 2)
# ============================================================

class TestGoExtractor:
    """Tests for GoExtractor."""

    def setup_method(self):
        self.ext = GoExtractor()

    def test_func_definition(self):
        code = "func HandleRequest(w http.ResponseWriter, r *http.Request) {"
        defs = self.ext.extract_definitions(code)
        assert "HandleRequest" in defs

    def test_method_definition(self):
        code = "func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {"
        defs = self.ext.extract_definitions(code)
        assert "handleHealth" in defs

    def test_type_definition(self):
        code = "type UserService struct {"
        defs = self.ext.extract_definitions(code)
        assert "UserService" in defs

    def test_const_definition(self):
        code = "const MaxRetries = 3"
        defs = self.ext.extract_definitions(code)
        assert "MaxRetries" in defs

    def test_import(self):
        code = 'import "fmt"'
        imports = self.ext.extract_imports(code)
        assert "fmt" in imports

    def test_multi_import(self):
        code = 'import (\n\t"fmt"\n\t"net/http"\n)'
        imports = self.ext.extract_imports(code)
        assert "fmt" in imports
        assert "net/http" in imports

    def test_exported_symbol(self):
        code = "func ProcessData() error {"
        exports = self.ext.extract_exports(code)
        assert "ProcessData" in exports

    def test_references(self):
        code = "result := ComputeHash(data)"
        refs = self.ext.extract_references(code)
        assert "ComputeHash" in refs


# ============================================================
# Rust Extractor Tests (Tier 2)
# ============================================================

class TestRustExtractor:
    """Tests for RustExtractor."""

    def setup_method(self):
        self.ext = RustExtractor()

    def test_fn_definition(self):
        code = "fn process_data(input: &str) -> Result<(), Error> {"
        defs = self.ext.extract_definitions(code)
        assert "process_data" in defs

    def test_pub_fn(self):
        code = "pub fn new() -> Self {"
        defs = self.ext.extract_definitions(code)
        assert "new" in defs

    def test_struct_definition(self):
        code = "pub struct Config {"
        defs = self.ext.extract_definitions(code)
        assert "Config" in defs

    def test_enum_definition(self):
        code = "enum Status { Active, Inactive }"
        defs = self.ext.extract_definitions(code)
        assert "Status" in defs

    def test_trait_definition(self):
        code = "pub trait Handler {"
        defs = self.ext.extract_definitions(code)
        assert "Handler" in defs

    def test_use_import(self):
        code = "use crate::auth::service;"
        imports = self.ext.extract_imports(code)
        assert "crate::auth::service" in imports

    def test_mod_import(self):
        code = "mod config;"
        imports = self.ext.extract_imports(code)
        assert "config" in imports

    def test_pub_export(self):
        code = "pub fn handle_request() {"
        exports = self.ext.extract_exports(code)
        assert "handle_request" in exports


# ============================================================
# Java Extractor Tests (Tier 2)
# ============================================================

class TestJavaExtractor:
    """Tests for JavaExtractor."""

    def setup_method(self):
        self.ext = JavaExtractor()

    def test_class_definition(self):
        code = "public class UserService {"
        defs = self.ext.extract_definitions(code)
        assert "UserService" in defs

    def test_interface_definition(self):
        code = "public interface Repository {"
        defs = self.ext.extract_definitions(code)
        assert "Repository" in defs

    def test_import(self):
        code = "import com.example.service.UserService;"
        imports = self.ext.extract_imports(code)
        assert "com.example.service.UserService" in imports

    def test_method_definition(self):
        code = "    public void processData(String input) {"
        defs = self.ext.extract_definitions(code)
        assert "processData" in defs


# ============================================================
# C/C++ Extractor Tests (Tier 2)
# ============================================================

class TestCExtractor:
    """Tests for CExtractor."""

    def setup_method(self):
        self.ext = CExtractor()

    def test_function_definition(self):
        code = "int process_data(const char* input) {"
        defs = self.ext.extract_definitions(code)
        assert "process_data" in defs

    def test_struct_definition(self):
        code = "struct Config {"
        defs = self.ext.extract_definitions(code)
        assert "Config" in defs

    def test_define(self):
        code = "#define MAX_BUFFER_SIZE 1024"
        defs = self.ext.extract_definitions(code)
        assert "MAX_BUFFER_SIZE" in defs

    def test_include(self):
        code = '#include "config.h"'
        imports = self.ext.extract_imports(code)
        assert "config.h" in imports

    def test_system_include(self):
        code = "#include <stdio.h>"
        imports = self.ext.extract_imports(code)
        assert "stdio.h" in imports


class TestCppExtractor:
    """Tests for CppExtractor (extends C)."""

    def setup_method(self):
        self.ext = CppExtractor()

    def test_class_definition(self):
        code = "class UserManager {"
        defs = self.ext.extract_definitions(code)
        assert "UserManager" in defs

    def test_namespace_definition(self):
        code = "namespace auth {"
        defs = self.ext.extract_definitions(code)
        assert "auth" in defs

    def test_inherits_c_features(self):
        code = "#include <vector>"
        imports = self.ext.extract_imports(code)
        assert "vector" in imports


# ============================================================
# Non-code Extractor Tests
# ============================================================

class TestProtobufExtractor:
    """Tests for ProtobufExtractor."""

    def setup_method(self):
        self.ext = ProtobufExtractor()

    def test_message_definition(self):
        code = "message UserRequest {"
        defs = self.ext.extract_definitions(code)
        assert "UserRequest" in defs

    def test_service_definition(self):
        code = "service UserService {"
        defs = self.ext.extract_definitions(code)
        assert "UserService" in defs

    def test_import(self):
        code = 'import "google/protobuf/timestamp.proto";'
        imports = self.ext.extract_imports(code)
        assert "google/protobuf/timestamp.proto" in imports


class TestYAMLExtractor:
    """Tests for YAMLExtractor."""

    def setup_method(self):
        self.ext = YAMLExtractor()

    def test_top_level_key(self):
        code = "services:\n  web:\n    build: ."
        defs = self.ext.extract_definitions(code)
        assert "services" in defs


class TestSQLExtractor:
    """Tests for SQLExtractor."""

    def setup_method(self):
        self.ext = SQLExtractor()

    def test_create_table(self):
        code = "CREATE TABLE users ("
        defs = self.ext.extract_definitions(code)
        assert "users" in defs

    def test_alter_table(self):
        code = "ALTER TABLE orders ADD COLUMN status VARCHAR(20);"
        defs = self.ext.extract_definitions(code)
        assert "orders" in defs


class TestDockerfileExtractor:
    """Tests for DockerfileExtractor."""

    def setup_method(self):
        self.ext = DockerfileExtractor()

    def test_from_as_stage(self):
        code = "FROM python:3.12 AS builder"
        defs = self.ext.extract_definitions(code)
        assert "builder" in defs

    def test_env_variable(self):
        code = "ENV APP_HOME /app"
        defs = self.ext.extract_definitions(code)
        assert "APP_HOME" in defs


# ============================================================
# Universal Fallback Tests (Tier 3)
# ============================================================

class TestUniversalFallbackExtractor:
    """Tests for UniversalFallbackExtractor."""

    def setup_method(self):
        self.ext = UniversalFallbackExtractor()

    def test_function_keyword(self):
        code = "function processData() {"
        defs = self.ext.extract_definitions(code)
        assert "processData" in defs

    def test_class_keyword(self):
        code = "class Handler {"
        defs = self.ext.extract_definitions(code)
        assert "Handler" in defs

    def test_def_keyword(self):
        code = "def compute():"
        defs = self.ext.extract_definitions(code)
        assert "compute" in defs

    def test_fn_keyword(self):
        code = "fn main() {"
        defs = self.ext.extract_definitions(code)
        assert "main" in defs

    def test_import_keyword(self):
        code = "import something"
        imports = self.ext.extract_imports(code)
        assert "something" in imports

    def test_require_keyword(self):
        code = "require 'some_lib'"
        imports = self.ext.extract_imports(code)
        assert "some_lib" in imports

    def test_include_keyword(self):
        code = '#include "header.h"'
        imports = self.ext.extract_imports(code)
        assert "header.h" in imports

    def test_references_function_calls(self):
        code = "result = computeHash(data)"
        refs = self.ext.extract_references(code)
        assert "computeHash" in refs

    def test_export_function(self):
        code = "export function format() {"
        exports = self.ext.extract_exports(code)
        assert "format" in exports

