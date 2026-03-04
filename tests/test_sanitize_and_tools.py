"""Tests for message sanitization and file-existence tools.

Covers:
- BaseSubAgent._sanitize_message_dump (Gemini thought signature stripping)
- check_file_in_repo (file existence + export extraction)
- Language-specific export extractors
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from hunknote.compose.agents.base import BaseSubAgent
from hunknote.compose.agents.tools import (
    _detect_language,
    _extract_c_cpp,
    _extract_csharp,
    _extract_generic,
    _extract_go,
    _extract_java,
    _extract_python,
    _extract_ruby,
    _extract_rust,
    _extract_typescript,
    check_file_in_repo,
)


# ============================================================
# Message sanitization tests
# ============================================================

class TestSanitizeMessageDump:
    """Tests for _sanitize_message_dump."""

    def test_strips_provider_specific_fields(self):
        """Remove provider_specific_fields from the message."""
        dumped = {
            "role": "assistant",
            "content": None,
            "provider_specific_fields": {
                "thought_signature": "x" * 500,
            },
            "tool_calls": [],
        }
        result = BaseSubAgent._sanitize_message_dump(dumped)
        assert "provider_specific_fields" not in result
        assert result["role"] == "assistant"

    def test_strips_from_tool_calls(self):
        """Remove provider_specific_fields from each tool call."""
        dumped = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "index": 0,
                    "provider_specific_fields": {
                        "thought_signature": "HUGE_BASE64_BLOB" * 50,
                    },
                    "function": {
                        "name": "get_hunk_diff",
                        "arguments": '{"hunk_ids": ["H1"]}',
                    },
                },
            ],
        }
        result = BaseSubAgent._sanitize_message_dump(dumped)
        tc = result["tool_calls"][0]
        assert "provider_specific_fields" not in tc

    def test_truncates_long_tool_call_ids(self):
        """Truncate tool call IDs longer than 64 chars."""
        long_id = "call_abc__thought__" + "x" * 500
        dumped = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": long_id,
                    "index": 0,
                    "function": {
                        "name": "test_tool",
                        "arguments": "{}",
                    },
                },
            ],
        }
        result = BaseSubAgent._sanitize_message_dump(dumped)
        assert len(result["tool_calls"][0]["id"]) == 64

    def test_preserves_short_ids(self):
        """Don't truncate tool call IDs that are already short."""
        short_id = "call_abc123"
        dumped = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": short_id,
                    "index": 0,
                    "function": {
                        "name": "test_tool",
                        "arguments": "{}",
                    },
                },
            ],
        }
        result = BaseSubAgent._sanitize_message_dump(dumped)
        assert result["tool_calls"][0]["id"] == short_id

    def test_preserves_content(self):
        """Preserve message content."""
        dumped = {
            "role": "assistant",
            "content": "Hello world",
        }
        result = BaseSubAgent._sanitize_message_dump(dumped)
        assert result["content"] == "Hello world"

    def test_strips_images_and_thinking_blocks(self):
        """Remove images and thinking_blocks if present."""
        dumped = {
            "role": "assistant",
            "content": "text",
            "images": ["base64data"],
            "thinking_blocks": [{"type": "thinking", "text": "..."}],
        }
        result = BaseSubAgent._sanitize_message_dump(dumped)
        assert "images" not in result
        assert "thinking_blocks" not in result

    def test_no_tool_calls(self):
        """Works fine when there are no tool calls."""
        dumped = {
            "role": "assistant",
            "content": '{"key": "value"}',
        }
        result = BaseSubAgent._sanitize_message_dump(dumped)
        assert result["content"] == '{"key": "value"}'

    def test_multiple_tool_calls(self):
        """Handles multiple tool calls."""
        dumped = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "a" * 100,
                    "provider_specific_fields": {"sig": "big"},
                    "function": {"name": "t1", "arguments": "{}"},
                },
                {
                    "id": "b" * 100,
                    "provider_specific_fields": {"sig": "big"},
                    "function": {"name": "t2", "arguments": "{}"},
                },
            ],
        }
        result = BaseSubAgent._sanitize_message_dump(dumped)
        assert len(result["tool_calls"]) == 2
        for tc in result["tool_calls"]:
            assert len(tc["id"]) == 64
            assert "provider_specific_fields" not in tc

    def test_does_not_mutate_input(self):
        """Original dict should not be mutated."""
        original = {
            "role": "assistant",
            "content": None,
            "provider_specific_fields": {"key": "value"},
            "tool_calls": [
                {
                    "id": "x" * 100,
                    "provider_specific_fields": {"sig": "abc"},
                    "function": {"name": "t", "arguments": "{}"},
                },
            ],
        }
        BaseSubAgent._sanitize_message_dump(original)
        # Original should still have provider_specific_fields
        assert "provider_specific_fields" in original
        assert len(original["tool_calls"][0]["id"]) == 100

    def test_realistic_gemini_dump(self):
        """Simulate a realistic Gemini 2.5 Flash model dump."""
        dumped = {
            "content": None,
            "role": "assistant",
            "tool_calls": [
                {
                    "index": 0,
                    "provider_specific_fields": {
                        "thought_signature": (
                            "Ct0CAb4+9vs9ckhNGZju5cmAkwjG5O5hm1d+T7fevCD8c0wAg+"
                            "9QqzD3MwinTbPypib/sl+lOaytX7jRshycljWB8SaCoZD1l8aq"
                            "t4V6/EmEG/Ab+8KoSTnQrJSLPTtyOYPCiFRez/GhkZL/TfysP"
                            "MhiVnTDK43EYbQztwJD5B+B5NNWAQoMve" * 2
                        ),
                    },
                    "id": (
                        "call_99e1f819f1e440cab091fa2dea56__thought__Ct0CAb4+9vs9"
                        "ckhNGZju5cmAkwjG5O5hm1d+T7fevCD8c0wAg+9QqzD3MwinTbPy"
                        "pib/sl+lOaytX7jRshycljWB8SaCoZD1l8aqt4V6/EmEG/Ab+8Ko"
                        "STnQrJSLPTtyOYPCiFRez/GhkZL/TfysPMhiVnTDK43EYbQztwJ"
                        "D5B+B5NNWAQoMve" * 2
                    ),
                    "function": {
                        "arguments": '{"hunk_ids": ["H1_abc", "H2_def"]}',
                        "name": "get_hunk_diff",
                    },
                    "type": "function",
                },
            ],
            "function_call": None,
        }
        result = BaseSubAgent._sanitize_message_dump(dumped)

        # Should be dramatically smaller
        original_size = len(json.dumps(dumped))
        cleaned_size = len(json.dumps(result))
        assert cleaned_size < original_size / 2

        # Tool call should still be functional
        tc = result["tool_calls"][0]
        assert tc["function"]["name"] == "get_hunk_diff"
        assert len(tc["id"]) == 64
        assert "provider_specific_fields" not in tc


# ============================================================
# Language detection tests
# ============================================================

class TestDetectLanguage:
    """Tests for _detect_language."""

    def test_python(self):
        assert _detect_language("foo.py") == "python"
        assert _detect_language("foo.pyi") == "python"

    def test_typescript(self):
        assert _detect_language("foo.ts") == "typescript"
        assert _detect_language("foo.tsx") == "typescript"

    def test_javascript(self):
        assert _detect_language("foo.js") == "javascript"
        assert _detect_language("foo.jsx") == "javascript"
        assert _detect_language("foo.mjs") == "javascript"

    def test_go(self):
        assert _detect_language("foo.go") == "go"

    def test_rust(self):
        assert _detect_language("foo.rs") == "rust"

    def test_ruby(self):
        assert _detect_language("foo.rb") == "ruby"

    def test_java(self):
        assert _detect_language("foo.java") == "java"

    def test_kotlin(self):
        assert _detect_language("foo.kt") == "kotlin"

    def test_c(self):
        assert _detect_language("foo.c") == "c"
        assert _detect_language("foo.h") == "c"

    def test_cpp(self):
        assert _detect_language("foo.cpp") == "cpp"
        assert _detect_language("foo.hpp") == "cpp"

    def test_csharp(self):
        assert _detect_language("foo.cs") == "csharp"

    def test_swift(self):
        assert _detect_language("foo.swift") == "swift"

    def test_unknown(self):
        assert _detect_language("foo.xyz") == "unknown"
        assert _detect_language("Makefile") == "unknown"


# ============================================================
# Export extraction tests
# ============================================================

class TestExtractPython:
    """Tests for _extract_python."""

    def test_function_def(self):
        code = "def my_function():\n    pass\n"
        exports = _extract_python(code)
        assert "my_function" in exports

    def test_class_def(self):
        code = "class MyClass:\n    pass\n"
        exports = _extract_python(code)
        assert "MyClass" in exports

    def test_async_function(self):
        code = "async def fetch_data():\n    pass\n"
        exports = _extract_python(code)
        assert "fetch_data" in exports

    def test_constant_assignment(self):
        code = "MAX_SIZE = 100\nDEFAULT_NAME = 'test'\n"
        exports = _extract_python(code)
        assert "MAX_SIZE" in exports
        assert "DEFAULT_NAME" in exports

    def test_all_list(self):
        code = "__all__ = ['Foo', 'Bar', 'baz']\n"
        exports = _extract_python(code)
        assert "Foo" in exports
        assert "Bar" in exports
        assert "baz" in exports

    def test_mixed(self):
        code = (
            "class User:\n    pass\n\n"
            "def get_user():\n    pass\n\n"
            "API_VERSION = '1.0'\n"
        )
        exports = _extract_python(code)
        assert "User" in exports
        assert "get_user" in exports
        assert "API_VERSION" in exports


class TestExtractTypeScript:
    """Tests for _extract_typescript."""

    def test_export_function(self):
        code = "export function handleRequest() {}\n"
        exports = _extract_typescript(code)
        assert "handleRequest" in exports

    def test_export_class(self):
        code = "export class UserService {}\n"
        exports = _extract_typescript(code)
        assert "UserService" in exports

    def test_export_const(self):
        code = "export const MAX_SIZE = 100;\n"
        exports = _extract_typescript(code)
        assert "MAX_SIZE" in exports

    def test_export_interface(self):
        code = "export interface UserDTO {}\n"
        exports = _extract_typescript(code)
        assert "UserDTO" in exports

    def test_export_type(self):
        code = "export type UserId = string;\n"
        exports = _extract_typescript(code)
        assert "UserId" in exports

    def test_export_enum(self):
        code = "export enum Status { Active, Inactive }\n"
        exports = _extract_typescript(code)
        assert "Status" in exports

    def test_export_default(self):
        code = "export default class App {}\n"
        exports = _extract_typescript(code)
        assert "App" in exports

    def test_named_exports(self):
        code = "export { foo, bar as baz };\n"
        exports = _extract_typescript(code)
        assert "foo" in exports
        assert "bar" in exports


class TestExtractGo:
    """Tests for _extract_go."""

    def test_exported_function(self):
        code = "func HandleRequest(w http.ResponseWriter, r *http.Request) {}\n"
        exports = _extract_go(code)
        assert "HandleRequest" in exports

    def test_exported_type(self):
        code = "type UserService struct {\n    db *sql.DB\n}\n"
        exports = _extract_go(code)
        assert "UserService" in exports

    def test_unexported_not_included(self):
        code = "func helper() {}\nvar count int\n"
        exports = _extract_go(code)
        assert "helper" not in exports
        assert "count" not in exports


class TestExtractRust:
    """Tests for _extract_rust."""

    def test_pub_fn(self):
        code = "pub fn handle_request() {}\n"
        exports = _extract_rust(code)
        assert "handle_request" in exports

    def test_pub_struct(self):
        code = "pub struct User {\n    name: String,\n}\n"
        exports = _extract_rust(code)
        assert "User" in exports

    def test_pub_enum(self):
        code = "pub enum Status {\n    Active,\n    Inactive,\n}\n"
        exports = _extract_rust(code)
        assert "Status" in exports

    def test_private_not_included(self):
        code = "fn helper() {}\nstruct Internal {}\n"
        exports = _extract_rust(code)
        assert "helper" not in exports
        assert "Internal" not in exports


class TestExtractRuby:
    """Tests for _extract_ruby."""

    def test_class(self):
        code = "class UserService\n  def initialize\n  end\nend\n"
        exports = _extract_ruby(code)
        assert "UserService" in exports

    def test_module(self):
        code = "module MyApp\nend\n"
        exports = _extract_ruby(code)
        assert "MyApp" in exports

    def test_method(self):
        code = "  def process_request\n  end\n"
        exports = _extract_ruby(code)
        assert "process_request" in exports

    def test_class_method(self):
        code = "  def self.create\n  end\n"
        exports = _extract_ruby(code)
        assert "create" in exports


class TestExtractJava:
    """Tests for _extract_java."""

    def test_public_class(self):
        code = "public class UserService {\n}\n"
        exports = _extract_java(code)
        assert "UserService" in exports

    def test_interface(self):
        code = "public interface UserRepository {\n}\n"
        exports = _extract_java(code)
        assert "UserRepository" in exports

    def test_enum(self):
        code = "public enum Status {\n    ACTIVE, INACTIVE\n}\n"
        exports = _extract_java(code)
        assert "Status" in exports

    def test_kotlin_data_class(self):
        code = "data class User(val name: String)\n"
        exports = _extract_java(code)
        assert "User" in exports

    def test_kotlin_fun(self):
        code = "fun handleRequest(): Response {\n}\n"
        exports = _extract_java(code)
        assert "handleRequest" in exports


class TestExtractCCpp:
    """Tests for _extract_c_cpp."""

    def test_struct(self):
        code = "struct MyStruct {\n    int x;\n};\n"
        exports = _extract_c_cpp(code)
        assert "MyStruct" in exports

    def test_class(self):
        code = "class MyClass {\npublic:\n    void run();\n};\n"
        exports = _extract_c_cpp(code)
        assert "MyClass" in exports

    def test_function(self):
        code = "int main(int argc, char *argv[]) {\n}\n"
        exports = _extract_c_cpp(code)
        assert "main" in exports

    def test_define_macro(self):
        code = "#define MAX_BUFFER_SIZE 1024\n"
        exports = _extract_c_cpp(code)
        assert "MAX_BUFFER_SIZE" in exports

    def test_enum(self):
        code = "enum Color {\n    RED, GREEN, BLUE\n};\n"
        exports = _extract_c_cpp(code)
        assert "Color" in exports

    def test_excludes_keywords(self):
        code = "if (x) {\n}\nfor (int i = 0; i < 10; i++) {\n}\n"
        exports = _extract_c_cpp(code)
        assert "if" not in exports
        assert "for" not in exports


class TestExtractCSharp:
    """Tests for _extract_csharp."""

    def test_public_class(self):
        code = "public class UserService {\n}\n"
        exports = _extract_csharp(code)
        assert "UserService" in exports

    def test_interface(self):
        code = "public interface IUserRepository {\n}\n"
        exports = _extract_csharp(code)
        assert "IUserRepository" in exports

    def test_record(self):
        code = "public record UserDto(string Name, int Age);\n"
        exports = _extract_csharp(code)
        assert "UserDto" in exports

    def test_partial_class(self):
        code = "public partial class GameEngine {\n}\n"
        exports = _extract_csharp(code)
        assert "GameEngine" in exports


class TestExtractGeneric:
    """Tests for _extract_generic (fallback)."""

    def test_function(self):
        code = "function doSomething() {}\n"
        exports = _extract_generic(code)
        assert "doSomething" in exports

    def test_class(self):
        code = "class MyClass {}\n"
        exports = _extract_generic(code)
        assert "MyClass" in exports

    def test_export_prefixed(self):
        code = "export const MY_CONST = 42;\n"
        exports = _extract_generic(code)
        assert "MY_CONST" in exports

    def test_empty_content(self):
        exports = _extract_generic("")
        assert exports == []


# ============================================================
# check_file_in_repo tests (with mocked git)
# ============================================================

class TestCheckFileInRepo:
    """Tests for check_file_in_repo."""

    @patch("hunknote.compose.agents.tools.subprocess")
    def test_tracked_file(self, mock_subprocess):
        """File is tracked and has content."""
        # ls-files succeeds
        mock_subprocess.run.side_effect = [
            MagicMock(returncode=0, stdout="src/models.py\n"),  # ls-files
            MagicMock(returncode=0, stdout=(  # git show
                "class User:\n"
                "    name: str\n"
                "\n"
                "def get_user():\n"
                "    pass\n"
            )),
        ]

        result = json.loads(check_file_in_repo("src/models.py", "/repo"))
        assert result["exists"] is True
        assert result["tracked"] is True
        assert result["language"] == "python"
        assert "User" in result["exports"]
        assert "get_user" in result["exports"]
        assert "always valid" in result["note"]

    @patch("hunknote.compose.agents.tools.subprocess")
    def test_untracked_file(self, mock_subprocess):
        """File exists on disk but is not tracked."""
        mock_subprocess.run.return_value = MagicMock(returncode=1)

        with patch("os.path.isfile", return_value=True):
            result = json.loads(check_file_in_repo("untracked.py", "/repo"))

        assert result["exists"] is True
        assert result["tracked"] is False

    @patch("hunknote.compose.agents.tools.subprocess")
    def test_nonexistent_file(self, mock_subprocess):
        """File does not exist at all."""
        mock_subprocess.run.return_value = MagicMock(returncode=1)

        with patch("os.path.isfile", return_value=False):
            result = json.loads(check_file_in_repo("missing.py", "/repo"))

        assert result["exists"] is False
        assert result["tracked"] is False

    def test_no_repo_root(self):
        """No repo root detected."""
        result = json.loads(check_file_in_repo("file.py", None))
        # Should try _detect_repo_root
        # With no git, should return error
        assert "file_path" in result

    @patch("hunknote.compose.agents.tools.subprocess")
    def test_typescript_file(self, mock_subprocess):
        """TypeScript file has correct language and exports."""
        mock_subprocess.run.side_effect = [
            MagicMock(returncode=0),  # ls-files
            MagicMock(returncode=0, stdout=(
                "export interface UserDTO {\n"
                "  name: string;\n"
                "}\n"
                "export function createUser(): UserDTO {}\n"
                "export const MAX_USERS = 100;\n"
            )),
        ]

        result = json.loads(check_file_in_repo("src/types.ts", "/repo"))
        assert result["language"] == "typescript"
        assert "UserDTO" in result["exports"]
        assert "createUser" in result["exports"]
        assert "MAX_USERS" in result["exports"]

    @patch("hunknote.compose.agents.tools.subprocess")
    def test_go_file(self, mock_subprocess):
        """Go file exports uppercase symbols."""
        mock_subprocess.run.side_effect = [
            MagicMock(returncode=0),  # ls-files
            MagicMock(returncode=0, stdout=(
                "func HandleRequest(w http.ResponseWriter) {}\n"
                "func helper() {}\n"
                "type Server struct{}\n"
            )),
        ]

        result = json.loads(check_file_in_repo("pkg/server.go", "/repo"))
        assert result["language"] == "go"
        assert "HandleRequest" in result["exports"]
        assert "Server" in result["exports"]
        assert "helper" not in result["exports"]

    @patch("hunknote.compose.agents.tools.subprocess")
    def test_rust_file(self, mock_subprocess):
        """Rust file exports pub symbols."""
        mock_subprocess.run.side_effect = [
            MagicMock(returncode=0),  # ls-files
            MagicMock(returncode=0, stdout=(
                "pub fn validate(input: &str) -> bool {}\n"
                "fn internal_helper() {}\n"
                "pub struct Config {}\n"
            )),
        ]

        result = json.loads(check_file_in_repo("src/lib.rs", "/repo"))
        assert result["language"] == "rust"
        assert "validate" in result["exports"]
        assert "Config" in result["exports"]
        assert "internal_helper" not in result["exports"]

