"""Tests for hunknote.compose.agent.react — Generic ReAct engine."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hunknote.compose.agent.react import (
    ReActConfig,
    ReActResult,
    _extract_final_output,
    _extract_tool_call,
    _try_parse_json,
    run_react_loop,
)
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.models import HunkRef
from hunknote.llm.base import RawLLMResult


# ── _try_parse_json ──


class TestTryParseJson:
    """Tests for JSON parsing with error recovery."""

    def test_valid_json(self):
        assert _try_parse_json('{"key": "value"}') == {"key": "value"}

    def test_invalid_json_returns_none(self):
        assert _try_parse_json("not json") is None

    def test_trailing_comma_cleaned(self):
        """Trailing commas are cleaned before parsing."""
        result = _try_parse_json('{"a": 1, "b": 2,}')
        assert result == {"a": 1, "b": 2}

    def test_array_returns_none(self):
        """Only dicts are accepted, not arrays."""
        assert _try_parse_json('[1, 2, 3]') is None

    def test_empty_object(self):
        assert _try_parse_json("{}") == {}


# ── _extract_tool_call ──


class TestExtractToolCall:
    """Tests for tool call parsing."""

    def test_basic_tool_call(self):
        text = 'Thought: I need to search.\nAction: ripgrep\nArgs: {"pattern": "hello"}'
        name, args = _extract_tool_call(text)
        assert name == "ripgrep"
        assert args == {"pattern": "hello"}

    def test_no_action(self):
        text = "Thought: Just thinking here."
        name, args = _extract_tool_call(text)
        assert name is None
        assert args == {}

    def test_action_without_args(self):
        text = "Thought: Check hunks.\nAction: list_hunks\n"
        name, args = _extract_tool_call(text)
        assert name == "list_hunks"
        assert args == {}

    def test_action_with_invalid_args(self):
        text = "Action: ripgrep\nArgs: not-json"
        name, args = _extract_tool_call(text)
        assert name == "ripgrep"
        assert args == {}


# ── _extract_final_output ──


class TestExtractFinalOutput:
    """Tests for final output parsing."""

    def test_output_with_json_fence(self):
        text = 'Thought: Done.\nOutput:\n```json\n{"edges": []}\n```'
        result = _extract_final_output(text)
        assert result == {"edges": []}

    def test_output_without_fence(self):
        text = 'Thought: Done.\nOutput:\n{"edges": [{"from": "H1", "to": "H2"}]}'
        result = _extract_final_output(text)
        assert result is not None
        assert "edges" in result

    def test_no_output_marker(self):
        text = "Thought: Still thinking.\nI need more data."
        result = _extract_final_output(text)
        assert result is None

    def test_raw_json_at_end(self):
        text = "Some reasoning.\n{\"edges\": []}"
        result = _extract_final_output(text)
        assert result == {"edges": []}


# ── run_react_loop ──


class TestRunReactLoop:
    """Tests for the ReAct agent loop."""

    @pytest.fixture
    def config(self):
        return ReActConfig(
            max_iterations=5,
            max_tool_calls=5,
            system_prompt="You are a test agent.",
            output_schema_description="Output JSON.",
        )

    @pytest.fixture
    def trace(self):
        return AgentTrace()

    @pytest.fixture
    def inventory(self):
        return {
            "H1_abc123": HunkRef(
                id="H1_abc123", file_path="foo.py", header="@@",
                old_start=1, old_len=1, new_start=1, new_len=1, lines=["+x"],
            ),
        }

    def test_immediate_output(self, config, trace, inventory):
        """Agent produces output on first iteration."""
        def mock_llm(system, user):
            return RawLLMResult(
                raw_response='Thought: Done.\nOutput:\n```json\n{"result": "ok"}\n```',
                model="test", input_tokens=10, output_tokens=5,
            )

        result = run_react_loop(
            config, "Analyze hunks.", mock_llm, Path("."),
            inventory, trace, "test",
        )
        assert result.output == {"result": "ok"}
        assert result.iterations == 1

    def test_tool_call_then_output(self, config, trace, inventory):
        """Agent makes a tool call then produces output."""
        call_count = [0]

        def mock_llm(system, user):
            call_count[0] += 1
            if call_count[0] == 1:
                return RawLLMResult(
                    raw_response=(
                        "Thought: Need to check hunks.\n"
                        "Action: list_hunks\n"
                        'Args: {}'
                    ),
                    model="test", input_tokens=10, output_tokens=10,
                )
            return RawLLMResult(
                raw_response='Thought: Got it.\nOutput:\n{"edges": []}',
                model="test", input_tokens=20, output_tokens=10,
            )

        result = run_react_loop(
            config, "Analyze.", mock_llm, Path("."),
            inventory, trace, "test",
        )
        assert result.output == {"edges": []}
        assert result.iterations == 2
        assert result.tool_calls_made == 1

    def test_max_iterations_exhausted(self, config, trace, inventory):
        """Loop stops at max iterations with empty output."""
        config.max_iterations = 2

        def mock_llm(system, user):
            return RawLLMResult(
                raw_response="Thought: I'm thinking...",
                model="test", input_tokens=10, output_tokens=5,
            )

        result = run_react_loop(
            config, "Analyze.", mock_llm, Path("."),
            inventory, trace, "test",
        )
        assert result.output == {}
        assert result.iterations == 2

    def test_token_accumulation(self, config, trace, inventory):
        """Tokens are accumulated across iterations."""
        call_count = [0]

        def mock_llm(system, user):
            call_count[0] += 1
            if call_count[0] <= 2:
                return RawLLMResult(
                    raw_response="Thought: Still working.\nAction: list_hunks\nArgs: {}",
                    model="test", input_tokens=100, output_tokens=50,
                )
            return RawLLMResult(
                raw_response='Output:\n{"done": true}',
                model="test", input_tokens=100, output_tokens=50,
            )

        result = run_react_loop(
            config, "Go.", mock_llm, Path("."),
            inventory, trace, "test",
        )
        assert result.total_input_tokens == 300
        assert result.total_output_tokens == 150

    def test_llm_failure_breaks_loop(self, config, trace, inventory):
        """LLM exception breaks the loop gracefully."""
        def mock_llm(system, user):
            raise RuntimeError("API error")

        result = run_react_loop(
            config, "Go.", mock_llm, Path("."),
            inventory, trace, "test",
        )
        assert result.output == {}
        assert result.iterations == 1

    def test_max_tool_calls_respected(self, config, trace, inventory):
        """Tool calls stop after reaching the limit."""
        config.max_tool_calls = 1

        call_count = [0]
        def mock_llm(system, user):
            call_count[0] += 1
            if call_count[0] <= 3:
                return RawLLMResult(
                    raw_response="Thought: Need data.\nAction: list_hunks\nArgs: {}",
                    model="test", input_tokens=10, output_tokens=10,
                )
            return RawLLMResult(
                raw_response='Output:\n{"done": true}',
                model="test", input_tokens=10, output_tokens=10,
            )

        result = run_react_loop(
            config, "Go.", mock_llm, Path("."),
            inventory, trace, "test",
        )
        # After max_tool_calls (1), further tool calls are ignored
        assert result.tool_calls_made <= config.max_tool_calls + 1
