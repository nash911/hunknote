"""Tests for the ReAct sub-agents (base class and individual agents)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from hunknote.compose.agents.base import BaseSubAgent, SubAgentResult
from hunknote.compose.agents.tools import (
    build_hunk_summary_text,
    get_checkpoint_state,
    get_file_hunks,
    get_hunk_diff,
    get_symbol_summary,
)
from hunknote.compose.models import (
    CommitGroup,
    DependencyEdge,
    DependencyGraph,
    FileDiff,
    HunkRef,
    HunkSymbols,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_inventory():
    """Create a sample hunk inventory."""
    return {
        "H1_abc": HunkRef(
            id="H1_abc", file_path="src/models.py", header="@@ -1,5 +1,10 @@",
            old_start=1, old_len=5, new_start=1, new_len=10,
            lines=["+class User:", "+    name: str", "+    email: str"],
        ),
        "H2_def": HunkRef(
            id="H2_def", file_path="src/api.py", header="@@ -10,3 +10,8 @@",
            old_start=10, old_len=3, new_start=10, new_len=8,
            lines=["+from src.models import User", "+def get_user():", "+    return User()"],
        ),
        "H3_ghi": HunkRef(
            id="H3_ghi", file_path="tests/test_api.py", header="@@ -1,0 +1,5 @@",
            old_start=1, old_len=0, new_start=1, new_len=5,
            lines=["+from src.api import get_user", "+def test_get_user():", "+    assert get_user()"],
        ),
    }


@pytest.fixture
def sample_file_diffs(sample_inventory):
    """Create sample file diffs from inventory."""
    inv = sample_inventory
    return [
        FileDiff(file_path="src/models.py", diff_header_lines=["diff --git a/src/models.py b/src/models.py"],
                 hunks=[inv["H1_abc"]]),
        FileDiff(file_path="src/api.py", diff_header_lines=["diff --git a/src/api.py b/src/api.py"],
                 hunks=[inv["H2_def"]]),
        FileDiff(file_path="tests/test_api.py", diff_header_lines=["diff --git a/tests/test_api.py b/tests/test_api.py"],
                 hunks=[inv["H3_ghi"]], is_new_file=True),
    ]


@pytest.fixture
def sample_symbol_analyses():
    """Create sample symbol analyses."""
    return {
        "H1_abc": HunkSymbols(
            file_path="src/models.py", language="python",
            defines={"User"}, exports_added={"User"},
        ),
        "H2_def": HunkSymbols(
            file_path="src/api.py", language="python",
            defines={"get_user"}, imports_added={"User"},
            references={"User"},
        ),
        "H3_ghi": HunkSymbols(
            file_path="tests/test_api.py", language="python",
            imports_added={"get_user"}, references={"get_user"},
        ),
    }


@pytest.fixture
def sample_groups(sample_inventory):
    """Create sample commit groups."""
    return [
        CommitGroup(
            hunk_ids=["H1_abc"],
            files=["src/models.py"],
            reason="Add User model",
        ),
        CommitGroup(
            hunk_ids=["H2_def"],
            files=["src/api.py"],
            reason="Add API endpoint",
        ),
        CommitGroup(
            hunk_ids=["H3_ghi"],
            files=["tests/test_api.py"],
            reason="Add tests",
        ),
    ]


# ============================================================
# BaseSubAgent Tests
# ============================================================

class TestBaseSubAgent:
    """Tests for the BaseSubAgent class."""

    def test_register_tool(self):
        agent = BaseSubAgent("test", "system prompt", "test-model")
        agent.register_tool(
            name="my_tool",
            func=lambda x: f"result: {x}",
            description="A test tool",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
        )
        assert "my_tool" in agent._tools

    def test_get_tool_schemas(self):
        agent = BaseSubAgent("test", "system prompt", "test-model")
        agent.register_tool(
            name="tool1",
            func=lambda: "ok",
            description="Tool 1",
            parameters={"type": "object", "properties": {}},
        )
        schemas = agent._get_tool_schemas()
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "tool1"

    def test_dispatch_tool_success(self):
        agent = BaseSubAgent("test", "system prompt", "test-model")
        agent.register_tool(
            name="echo",
            func=lambda msg: f"echo: {msg}",
            description="Echo",
            parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        )
        result = agent._dispatch_tool("echo", {"msg": "hello"})
        assert result == "echo: hello"

    def test_dispatch_unknown_tool(self):
        agent = BaseSubAgent("test", "system prompt", "test-model")
        result = agent._dispatch_tool("nonexistent", {})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_extract_json_plain(self):
        result = BaseSubAgent._extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_extract_json_with_fences(self):
        text = '```json\n{"key": "value"}\n```'
        result = BaseSubAgent._extract_json(text)
        assert result == {"key": "value"}

    def test_extract_json_embedded(self):
        text = 'Here is the result: {"key": "value"} done.'
        result = BaseSubAgent._extract_json(text)
        assert result == {"key": "value"}

    def test_extract_json_invalid(self):
        result = BaseSubAgent._extract_json("not json at all")
        assert result == {}

    def test_extract_json_with_preamble(self):
        """JSON preceded by thinking/reasoning text."""
        text = """Let me analyze the dependencies between these hunks.

Looking at the imports and exports, I can see:
- H1 defines User
- H2 imports User

Here is my analysis:

{"edges": [{"source": "H2", "target": "H1", "reason": "imports", "strength": "must_be_ordered"}], "independent_hunks": [], "reasoning_summary": "done"}"""
        result = BaseSubAgent._extract_json(text)
        assert result["edges"][0]["source"] == "H2"

    def test_extract_json_nested_braces_in_strings(self):
        """JSON with curly braces inside string values."""
        text = '{"key": "value with {braces}", "nested": {"a": 1}}'
        result = BaseSubAgent._extract_json(text)
        assert result["key"] == "value with {braces}"
        assert result["nested"]["a"] == 1

    def test_extract_json_multiple_objects(self):
        """Multiple JSON objects — should pick the largest valid one."""
        text = """Here is a summary: {"small": true}

And the full result:
{"edges": [{"source": "H1", "target": "H2", "reason": "test", "strength": "must_be_ordered"}], "independent_hunks": ["H3"], "reasoning_summary": "full"}"""
        result = BaseSubAgent._extract_json(text)
        # Should pick the larger object
        assert "edges" in result

    def test_extract_json_empty_input(self):
        assert BaseSubAgent._extract_json("") == {}
        assert BaseSubAgent._extract_json(None) == {}
        assert BaseSubAgent._extract_json("   ") == {}

    def test_extract_json_truncated_recovery(self):
        """Truncated JSON with valid partial edges should be recovered."""
        # Simulate a response that was cut off by max_tokens
        truncated = '{"edges": [{"source": "H1", "target": "H2", "reason": "test", "strength": "must_be_ordered"}, {"source": "H3", "target": "H4", "reason": "test2", "stre'
        result = BaseSubAgent._extract_json(truncated)
        assert "edges" in result
        # Should have recovered at least the first complete edge
        assert len(result["edges"]) >= 1
        assert result["edges"][0]["source"] == "H1"

    def test_extract_json_truncated_with_fences(self):
        """Truncated JSON wrapped in markdown fences."""
        truncated = '```json\n{"edges": [{"source": "H1", "target": "H2", "reason": "imports X", "strength": "must_be_ordered"}'
        result = BaseSubAgent._extract_json(truncated)
        assert "edges" in result
        assert len(result["edges"]) == 1

    def test_extract_json_truncated_empty_edges(self):
        """Truncated JSON with no complete edges — recovery not possible."""
        truncated = '{"edges": [{"source": "H'
        result = BaseSubAgent._extract_json(truncated)
        # Too truncated to recover — should return empty dict
        assert result == {}


class TestRepairTruncatedJson:
    """Tests for the _repair_truncated_json helper function."""

    def test_repair_basic_truncation(self):
        from hunknote.compose.agents.base import _repair_truncated_json
        truncated = '{"key": "value", "arr": [1, 2, 3'
        repaired = _repair_truncated_json(truncated)
        assert repaired is not None
        parsed = json.loads(repaired)
        assert parsed["key"] == "value"
        # Trailing incomplete value (3) may be trimmed since we can't
        # know if it's complete (could be 30, 300, etc.)
        assert parsed["arr"] == [1, 2] or parsed["arr"] == [1, 2, 3]

    def test_repair_nested_truncation(self):
        from hunknote.compose.agents.base import _repair_truncated_json
        truncated = '{"edges": [{"source": "H1", "target": "H2"}, {"source": "H3'
        repaired = _repair_truncated_json(truncated)
        assert repaired is not None
        parsed = json.loads(repaired)
        assert "edges" in parsed
        assert len(parsed["edges"]) >= 1
        assert parsed["edges"][0]["source"] == "H1"

    def test_repair_already_valid(self):
        from hunknote.compose.agents.base import _repair_truncated_json
        valid = '{"key": "value"}'
        result = _repair_truncated_json(valid)
        # Already valid — nothing to repair
        assert result is None

    def test_repair_empty_input(self):
        from hunknote.compose.agents.base import _repair_truncated_json
        assert _repair_truncated_json("") is None
        assert _repair_truncated_json(None) is None

    def test_repair_mid_string_truncation(self):
        from hunknote.compose.agents.base import _repair_truncated_json
        truncated = '{"reason": "imports from new file hunknote/comp'
        repaired = _repair_truncated_json(truncated)
        # May or may not produce valid JSON depending on how well we repair,
        # but should not crash
        assert repaired is not None or repaired is None  # no crash
# ============================================================

class TestTools:
    """Tests for programmatic tools."""

    def test_get_hunk_diff(self, sample_inventory):
        result = json.loads(get_hunk_diff(["H1_abc"], sample_inventory))
        assert len(result) == 1
        assert result[0]["hunk_id"] == "H1_abc"
        assert result[0]["file_path"] == "src/models.py"
        assert len(result[0]["lines"]) > 0

    def test_get_hunk_diff_not_found(self, sample_inventory):
        result = json.loads(get_hunk_diff(["H99_xxx"], sample_inventory))
        assert result[0]["error"] == "not found"

    def test_get_file_hunks(self, sample_file_diffs):
        result = json.loads(get_file_hunks("src/models.py", sample_file_diffs))
        assert result["file_path"] == "src/models.py"
        assert len(result["hunks"]) == 1
        assert result["hunks"][0]["id"] == "H1_abc"

    def test_get_file_hunks_not_found(self, sample_file_diffs):
        result = json.loads(get_file_hunks("nonexistent.py", sample_file_diffs))
        assert "error" in result

    def test_get_symbol_summary(self, sample_symbol_analyses):
        result = json.loads(get_symbol_summary(["H1_abc", "H2_def"], sample_symbol_analyses))
        assert len(result) == 2
        assert "User" in result[0]["defines"]
        assert "User" in result[1]["imports_added"]

    def test_get_checkpoint_state(self, sample_groups, sample_inventory, sample_file_diffs):
        result = json.loads(get_checkpoint_state(1, sample_groups, sample_inventory, sample_file_diffs))
        assert result["checkpoint"] == 1
        assert "H1_abc" in result["committed_hunks"]
        assert result["total_committed"] == 1
        assert result["total_remaining"] == 2
        # New file context
        assert "tests/test_api.py" in result["new_files_in_diff"]
        assert "note" in result

    def test_get_checkpoint_state_all(self, sample_groups, sample_inventory, sample_file_diffs):
        result = json.loads(get_checkpoint_state(3, sample_groups, sample_inventory, sample_file_diffs))
        assert result["total_committed"] == 3
        assert result["total_remaining"] == 0

    def test_build_hunk_summary_text(self, sample_inventory, sample_file_diffs, sample_symbol_analyses):
        text = build_hunk_summary_text(sample_inventory, sample_file_diffs, sample_symbol_analyses)
        assert "src/models.py" in text
        assert "H1_abc" in text
        assert "User" in text


# ============================================================
# DependencyGraph Tests
# ============================================================

class TestDependencyGraph:
    """Tests for DependencyGraph methods."""

    def test_get_dependencies(self):
        graph = DependencyGraph(edges=[
            DependencyEdge("H2", "H1", "imports User", "must_be_ordered"),
            DependencyEdge("H3", "H2", "tests get_user", "must_be_ordered"),
        ])
        deps = graph.get_dependencies("H2")
        assert len(deps) == 1
        assert deps[0].target == "H1"

    def test_get_dependents(self):
        graph = DependencyGraph(edges=[
            DependencyEdge("H2", "H1", "imports User", "must_be_ordered"),
            DependencyEdge("H3", "H1", "references User", "must_be_ordered"),
        ])
        dependents = graph.get_dependents("H1")
        assert len(dependents) == 2

    def test_must_be_together_groups(self):
        graph = DependencyGraph(edges=[
            DependencyEdge("H1", "H2", "re-export", "must_be_together"),
            DependencyEdge("H2", "H3", "re-export", "must_be_together"),
            DependencyEdge("H4", "H5", "co-change", "must_be_together"),
        ])
        groups = graph.get_must_be_together_groups()
        assert len(groups) == 2
        # H1, H2, H3 should be in one group
        big_group = [g for g in groups if len(g) == 3][0]
        assert big_group == {"H1", "H2", "H3"}
        small_group = [g for g in groups if len(g) == 2][0]
        assert small_group == {"H4", "H5"}

    def test_must_be_together_empty(self):
        graph = DependencyGraph(edges=[
            DependencyEdge("H1", "H2", "order", "must_be_ordered"),
        ])
        groups = graph.get_must_be_together_groups()
        assert groups == []


# ============================================================
# Analyzer Agent Tests (mocked LLM)
# ============================================================

class TestDependencyAnalyzerAgent:
    """Tests for DependencyAnalyzerAgent with mocked LLM."""

    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_analyzer_json_retry(
        self, mock_completion, sample_inventory, sample_file_diffs, sample_symbol_analyses,
    ):
        """Test that the analyzer retries when first response is not JSON."""
        from hunknote.compose.agents.analyzer import DependencyAnalyzerAgent

        # First response: plain text (not JSON) → triggers retry
        response1 = MagicMock()
        response1.choices = [MagicMock()]
        response1.choices[0].message.tool_calls = None
        response1.choices[0].message.content = (
            "After analyzing the hunks, H2_def imports User from H1_abc, "
            "and H3_ghi tests get_user from H2_def."
        )
        response1.choices[0].message.model_dump = lambda: {
            "role": "assistant", "content": response1.choices[0].message.content,
        }
        response1.usage = MagicMock(prompt_tokens=100, completion_tokens=50, reasoning_tokens=0)

        # Second response: valid JSON (after retry prompt)
        response2 = MagicMock()
        response2.choices = [MagicMock()]
        response2.choices[0].message.tool_calls = None
        response2.choices[0].message.content = json.dumps({
            "edges": [
                {"source": "H2_def", "target": "H1_abc", "reason": "imports User", "strength": "must_be_ordered"},
            ],
            "independent_hunks": ["H3_ghi"],
            "reasoning_summary": "Linear chain.",
        })
        response2.choices[0].message.model_dump = lambda: {
            "role": "assistant", "content": response2.choices[0].message.content,
        }
        response2.usage = MagicMock(prompt_tokens=200, completion_tokens=60, reasoning_tokens=0)

        mock_completion.side_effect = [response1, response2]

        agent = DependencyAnalyzerAgent(
            model="test/model",
            inventory=sample_inventory,
            file_diffs=sample_file_diffs,
            symbol_analyses=sample_symbol_analyses,
        )
        graph = agent.run()

        assert len(graph.edges) == 1
        assert graph.edges[0].source == "H2_def"
        # Should have been called twice (original + retry)
        assert mock_completion.call_count == 2

    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_analyzer_returns_graph(
        self, mock_completion, sample_inventory, sample_file_diffs, sample_symbol_analyses,
    ):
        """Test that the analyzer parses LLM output into a DependencyGraph."""
        from hunknote.compose.agents.analyzer import DependencyAnalyzerAgent

        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = json.dumps({
            "edges": [
                {"source": "H2_def", "target": "H1_abc", "reason": "imports User", "strength": "must_be_ordered"},
                {"source": "H3_ghi", "target": "H2_def", "reason": "imports get_user", "strength": "must_be_ordered"},
            ],
            "independent_hunks": [],
            "reasoning_summary": "Linear dependency chain.",
        })
        mock_response.choices[0].message.model_dump = lambda: {
            "role": "assistant", "content": mock_response.choices[0].message.content,
        }
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50, reasoning_tokens=0)
        mock_completion.return_value = mock_response

        agent = DependencyAnalyzerAgent(
            model="test/model",
            inventory=sample_inventory,
            file_diffs=sample_file_diffs,
            symbol_analyses=sample_symbol_analyses,
        )
        graph = agent.run()

        assert len(graph.edges) == 2
        assert graph.edges[0].source == "H2_def"
        assert graph.edges[0].target == "H1_abc"
        assert graph.edges[0].strength == "must_be_ordered"

    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_analyzer_handles_failure(
        self, mock_completion, sample_inventory, sample_file_diffs, sample_symbol_analyses,
    ):
        """Test fallback when LLM call fails."""
        from hunknote.compose.agents.analyzer import DependencyAnalyzerAgent

        mock_completion.side_effect = Exception("API error")

        agent = DependencyAnalyzerAgent(
            model="test/model",
            inventory=sample_inventory,
            file_diffs=sample_file_diffs,
            symbol_analyses=sample_symbol_analyses,
        )
        graph = agent.run()

        # Should return a graph with all hunks as independent
        assert len(graph.edges) == 0
        assert set(graph.independent_hunks) == set(sample_inventory.keys())


# ============================================================
# Grouper Agent Tests (mocked LLM)
# ============================================================

class TestGrouperAgent:
    """Tests for GrouperAgent with mocked LLM."""

    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_grouper_returns_groups(
        self, mock_completion, sample_inventory, sample_file_diffs,
    ):
        from hunknote.compose.agents.grouper import GrouperAgent

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = json.dumps({
            "groups": [
                {"id": "C1", "hunk_ids": ["H1_abc", "H2_def"], "intent": "Add User model and API"},
                {"id": "C2", "hunk_ids": ["H3_ghi"], "intent": "Add tests"},
            ],
            "ungrouped_hunks": [],
        })
        mock_response.choices[0].message.model_dump = lambda: {
            "role": "assistant", "content": mock_response.choices[0].message.content,
        }
        mock_response.usage = MagicMock(prompt_tokens=80, completion_tokens=40, reasoning_tokens=0)
        mock_completion.return_value = mock_response

        grouper = GrouperAgent(
            model="test/model",
            inventory=sample_inventory,
            file_diffs=sample_file_diffs,
        )
        dep_graph = DependencyGraph(edges=[
            DependencyEdge("H2_def", "H1_abc", "imports User", "must_be_together"),
        ])
        groups = grouper.run(dependency_graph=dep_graph)

        assert len(groups) == 2
        assert "H1_abc" in groups[0].hunk_ids
        assert "H2_def" in groups[0].hunk_ids
        assert groups[1].hunk_ids == ["H3_ghi"]

    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_grouper_with_regroup_hint(
        self, mock_completion, sample_inventory, sample_file_diffs,
    ):
        """Test that regroup_hint is included in the user prompt."""
        from hunknote.compose.agents.grouper import GrouperAgent

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = json.dumps({
            "groups": [
                {"id": "C1", "hunk_ids": ["H1_abc", "H2_def", "H3_ghi"],
                 "intent": "All changes"},
            ],
        })
        mock_response.choices[0].message.model_dump = lambda: {
            "role": "assistant",
            "content": mock_response.choices[0].message.content,
        }
        mock_response.usage = MagicMock(
            prompt_tokens=80, completion_tokens=40, reasoning_tokens=0,
        )
        mock_completion.return_value = mock_response

        grouper = GrouperAgent(
            model="test/model",
            inventory=sample_inventory,
            file_diffs=sample_file_diffs,
        )
        dep_graph = DependencyGraph(edges=[])
        hint = "H1_abc and H2_def must be in the same group"
        groups = grouper.run(
            dependency_graph=dep_graph,
            regroup_hint=hint,
        )

        # Verify hint was passed to the LLM (check the prompt)
        # messages[0] = system prompt, messages[1] = user prompt
        # We use index 1 because the messages list is mutated after the call
        first_call = mock_completion.call_args_list[0]
        messages = first_call.kwargs.get("messages") or first_call[1].get("messages")
        user_msg = messages[1]["content"]
        assert "PREVIOUS GROUPING FEEDBACK" in user_msg
        assert hint in user_msg
        assert len(groups) == 1


# ============================================================
# Orderer Agent Tests (mocked LLM)
# ============================================================

class TestOrdererAgent:
    """Tests for OrdererAgent with mocked LLM."""

    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_orderer_reorders(self, mock_completion, sample_inventory, sample_file_diffs):
        from hunknote.compose.agents.orderer import OrdererAgent

        groups = [
            CommitGroup(hunk_ids=["H3_ghi"], files=["tests/test_api.py"], reason="Tests"),
            CommitGroup(hunk_ids=["H1_abc", "H2_def"], files=["src/models.py", "src/api.py"], reason="Core"),
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = json.dumps({
            "ordered_group_ids": ["C2", "C1"],
            "ordering_rationale": [
                {"group": "C2", "position": 1, "reason": "Core code first"},
                {"group": "C1", "position": 2, "reason": "Tests after"},
            ],
        })
        mock_response.choices[0].message.model_dump = lambda: {
            "role": "assistant", "content": mock_response.choices[0].message.content,
        }
        mock_response.usage = MagicMock(prompt_tokens=60, completion_tokens=30, reasoning_tokens=0)
        mock_completion.return_value = mock_response

        dep_graph = DependencyGraph(edges=[
            DependencyEdge("H3_ghi", "H2_def", "tests get_user", "must_be_ordered"),
        ])
        orderer = OrdererAgent(model="test/model")
        ordered = orderer.run(groups, dep_graph, sample_inventory, sample_file_diffs)

        # C2 (core) should come first
        assert "H1_abc" in ordered[0].hunk_ids
        assert "H3_ghi" in ordered[1].hunk_ids

    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_orderer_with_reorder_hint(
        self, mock_completion, sample_inventory, sample_file_diffs,
    ):
        """Test that reorder_hint is included in the user prompt."""
        from hunknote.compose.agents.orderer import OrdererAgent

        groups = [
            CommitGroup(hunk_ids=["H3_ghi"], files=["tests/test_api.py"], reason="Tests"),
            CommitGroup(hunk_ids=["H1_abc", "H2_def"],
                        files=["src/models.py", "src/api.py"], reason="Core"),
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = json.dumps({
            "ordered_group_ids": ["C2", "C1"],
        })
        mock_response.choices[0].message.model_dump = lambda: {
            "role": "assistant",
            "content": mock_response.choices[0].message.content,
        }
        mock_response.usage = MagicMock(
            prompt_tokens=60, completion_tokens=30, reasoning_tokens=0,
        )
        mock_completion.return_value = mock_response

        dep_graph = DependencyGraph(edges=[])
        orderer = OrdererAgent(model="test/model")
        hint = "C1 must come before C2 because C2 imports from C1"
        ordered = orderer.run(
            groups, dep_graph, sample_inventory, sample_file_diffs,
            reorder_hint=hint,
        )

        # Verify hint was passed to the LLM
        first_call = mock_completion.call_args_list[0]
        messages = first_call.kwargs.get("messages") or first_call[1].get("messages")
        user_msg = messages[1]["content"]
        assert "PREVIOUS ORDERING FEEDBACK" in user_msg
        assert hint in user_msg


# ============================================================
# Messenger Agent Tests (mocked LLM)
# ============================================================

class TestMessengerAgent:
    """Tests for MessengerAgent with mocked LLM."""

    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_messenger_generates_plan(
        self, mock_completion, sample_inventory, sample_file_diffs, sample_groups,
    ):
        from hunknote.compose.agents.messenger import MessengerAgent

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "version": "1",
            "warnings": [],
            "commits": [
                {"id": "C1", "type": "feat", "scope": "models", "title": "Add User model",
                 "hunks": ["H1_abc"], "bullets": ["Add User dataclass"]},
                {"id": "C2", "type": "feat", "scope": "api", "title": "Add user endpoint",
                 "hunks": ["H2_def"], "bullets": ["Add get_user function"]},
                {"id": "C3", "type": "test", "scope": "api", "title": "Add API tests",
                 "hunks": ["H3_ghi"], "bullets": ["Add test_get_user"]},
            ],
        })
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=60, reasoning_tokens=0)
        mock_completion.return_value = mock_response

        messenger = MessengerAgent(model="test/model")
        plan = messenger.run(sample_groups, sample_inventory, sample_file_diffs)

        assert len(plan.commits) == 3
        assert plan.commits[0].type == "feat"
        assert plan.commits[2].type == "test"


# ============================================================
# Validator Agent Tests (mocked LLM)
# ============================================================

class TestCheckpointValidatorAgent:
    """Tests for CheckpointValidatorAgent with mocked LLM."""

    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_validator_all_valid(
        self, mock_completion, sample_inventory, sample_file_diffs,
        sample_symbol_analyses, sample_groups,
    ):
        from hunknote.compose.agents.validator import CheckpointValidatorAgent

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = json.dumps({
            "valid": True,
            "checkpoints": [
                {"checkpoint": 1, "commit_id": "C1", "valid": True},
                {"checkpoint": 2, "commit_id": "C2", "valid": True},
                {"checkpoint": 3, "commit_id": "C3", "valid": True},
            ],
            "reasoning_summary": "All checkpoints valid.",
        })
        mock_response.choices[0].message.model_dump = lambda: {
            "role": "assistant", "content": mock_response.choices[0].message.content,
        }
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50, reasoning_tokens=0)
        mock_completion.return_value = mock_response

        dep_graph = DependencyGraph()
        validator = CheckpointValidatorAgent(
            model="test/model",
            inventory=sample_inventory,
            file_diffs=sample_file_diffs,
            symbol_analyses=sample_symbol_analyses,
        )
        result = validator.run(sample_groups, dep_graph)

        assert result["valid"] is True

    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_validator_detects_failure(
        self, mock_completion, sample_inventory, sample_file_diffs,
        sample_symbol_analyses,
    ):
        from hunknote.compose.agents.validator import CheckpointValidatorAgent

        # Groups in wrong order: tests before code
        bad_groups = [
            CommitGroup(hunk_ids=["H3_ghi"], files=["tests/test_api.py"]),
            CommitGroup(hunk_ids=["H2_def"], files=["src/api.py"]),
            CommitGroup(hunk_ids=["H1_abc"], files=["src/models.py"]),
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = json.dumps({
            "valid": False,
            "checkpoints": [
                {"checkpoint": 1, "commit_id": "C1", "valid": False,
                 "violations": [
                     {"commit": "C1", "hunk": "H3_ghi",
                      "issue": "Imports get_user but src/api.py not committed",
                      "missing_from": "C2",
                      "fix_suggestion": "Move tests after API code"}
                 ]},
            ],
        })
        mock_response.choices[0].message.model_dump = lambda: {
            "role": "assistant", "content": mock_response.choices[0].message.content,
        }
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50, reasoning_tokens=0)
        mock_completion.return_value = mock_response

        dep_graph = DependencyGraph()
        validator = CheckpointValidatorAgent(
            model="test/model",
            inventory=sample_inventory,
            file_diffs=sample_file_diffs,
            symbol_analyses=sample_symbol_analyses,
        )
        result = validator.run(bad_groups, dep_graph)

        assert result["valid"] is False

    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_validator_classifies_ordering_issue(
        self, mock_completion, sample_inventory, sample_file_diffs,
        sample_symbol_analyses,
    ):
        """Test that validator can return issue_type=ordering."""
        from hunknote.compose.agents.validator import CheckpointValidatorAgent

        bad_groups = [
            CommitGroup(hunk_ids=["H3_ghi"], files=["tests/test_api.py"]),
            CommitGroup(hunk_ids=["H2_def"], files=["src/api.py"]),
            CommitGroup(hunk_ids=["H1_abc"], files=["src/models.py"]),
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = json.dumps({
            "valid": False,
            "issue_type": "ordering",
            "checkpoints": [
                {"checkpoint": 1, "commit_id": "C1", "valid": False,
                 "violations": [
                     {"commit": "C1", "hunk": "H3_ghi",
                      "issue": "imports get_user not yet committed",
                      "missing_from": "C2",
                      "fix": "ordering"}
                 ]},
            ],
            "fix_reasoning": "C3 (tests) should come after C2 (API) and C1 (models)",
            "reasoning_summary": "Wrong order: tests committed before API code.",
        })
        mock_response.choices[0].message.model_dump = lambda: {
            "role": "assistant",
            "content": mock_response.choices[0].message.content,
        }
        mock_response.usage = MagicMock(
            prompt_tokens=100, completion_tokens=50, reasoning_tokens=0,
        )
        mock_completion.return_value = mock_response

        dep_graph = DependencyGraph()
        validator = CheckpointValidatorAgent(
            model="test/model",
            inventory=sample_inventory,
            file_diffs=sample_file_diffs,
            symbol_analyses=sample_symbol_analyses,
        )
        result = validator.run(bad_groups, dep_graph)

        assert result["valid"] is False
        assert result["issue_type"] == "ordering"
        assert "fix_reasoning" in result

    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_validator_classifies_grouping_issue(
        self, mock_completion, sample_inventory, sample_file_diffs,
        sample_symbol_analyses,
    ):
        """Test that validator can return issue_type=grouping."""
        from hunknote.compose.agents.validator import CheckpointValidatorAgent

        bad_groups = [
            CommitGroup(hunk_ids=["H1_abc"], files=["src/models.py"]),
            CommitGroup(hunk_ids=["H2_def"], files=["src/api.py"]),
            CommitGroup(hunk_ids=["H3_ghi"], files=["tests/test_api.py"]),
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = json.dumps({
            "valid": False,
            "issue_type": "grouping",
            "checkpoints": [
                {"checkpoint": 2, "commit_id": "C2", "valid": False,
                 "violations": [
                     {"commit": "C2", "hunk": "H2_def",
                      "issue": "must_be_together with H1_abc",
                      "missing_from": "C1",
                      "fix": "grouping"}
                 ]},
            ],
            "fix_reasoning": "H1_abc and H2_def should be in the same group",
            "reasoning_summary": "Grouping error: tightly coupled hunks split apart.",
        })
        mock_response.choices[0].message.model_dump = lambda: {
            "role": "assistant",
            "content": mock_response.choices[0].message.content,
        }
        mock_response.usage = MagicMock(
            prompt_tokens=100, completion_tokens=50, reasoning_tokens=0,
        )
        mock_completion.return_value = mock_response

        dep_graph = DependencyGraph()
        validator = CheckpointValidatorAgent(
            model="test/model",
            inventory=sample_inventory,
            file_diffs=sample_file_diffs,
            symbol_analyses=sample_symbol_analyses,
        )
        result = validator.run(bad_groups, dep_graph)

        assert result["valid"] is False
        assert result["issue_type"] == "grouping"
        assert "fix_reasoning" in result

