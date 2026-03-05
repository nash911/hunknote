"""Tests for compose ReAct sub-agents and base loop."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from hunknote.compose.agents.analyzer import DependencyAnalyzerAgent
from hunknote.compose.agents.base import BaseSubAgent
from hunknote.compose.agents.grouper import GrouperAgent
from hunknote.compose.agents.messenger import MessengerAgent
from hunknote.compose.agents.orderer import OrdererAgent
from hunknote.compose.agents.tools import (
    extract_symbol_info,
    programmatic_checkpoint_validation,
    repo_regex_search,
)
from hunknote.compose.agents.validator import CheckpointValidatorAgent
from hunknote.compose.models import CommitGroup, FileDiff, HunkRef


def _mock_response(content, tool_calls=None):
    message = SimpleNamespace(
        content=json.dumps(content) if isinstance(content, dict) else content,
        tool_calls=tool_calls,
    )
    message.model_dump = lambda: {
        "role": "assistant",
        "content": message.content,
        "tool_calls": [
            {
                "id": tc.id,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
                "type": "function",
            }
            for tc in (tool_calls or [])
        ],
    }
    usage = SimpleNamespace(prompt_tokens=20, completion_tokens=10, reasoning_tokens=0)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def _tool_call(name: str, arguments: dict, tc_id: str = "call_1"):
    return SimpleNamespace(
        id=tc_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _sample_inventory():
    return {
        "H1": HunkRef(
            id="H1",
            file_path="src/models.py",
            header="@@ -1,0 +1,4 @@",
            old_start=1,
            old_len=0,
            new_start=1,
            new_len=4,
            lines=["+class User:", "+    pass"],
        ),
        "H2": HunkRef(
            id="H2",
            file_path="src/api.py",
            header="@@ -1,0 +1,4 @@",
            old_start=1,
            old_len=0,
            new_start=1,
            new_len=4,
            lines=["+from src.models import User", "+def get_user():", "+    return User()"],
        ),
    }


def _sample_file_diffs(inv):
    return [
        FileDiff(file_path="src/models.py", diff_header_lines=["diff"], hunks=[inv["H1"]]),
        FileDiff(file_path="src/api.py", diff_header_lines=["diff"], hunks=[inv["H2"]]),
    ]


class _DummyAgent(BaseSubAgent):
    def __init__(self):
        super().__init__(
            name="Dummy",
            model="gemini/gemini-2.5-flash",
            system_prompt="dummy",
            max_iterations=3,
            max_tokens=2048,
        )
        self.register_tool(
            name="echo",
            func=lambda value: json.dumps({"value": value}),
            description="Echo value.",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        )


@patch("hunknote.compose.agents.base.litellm_completion")
def test_base_react_loop_tool_then_final(mock_completion):
    agent = _DummyAgent()
    mock_completion.side_effect = [
        _mock_response("", tool_calls=[_tool_call("echo", {"value": "x"})]),
        _mock_response({"ok": True}),
    ]

    result = agent._react_loop("start")

    assert result.success is True
    assert result.output["ok"] is True
    assert len(result.trace) == 2
    assert result.trace[0]["tool"] == "echo"
    assert result.trace[1]["action"] == "llm_response"


@patch("hunknote.compose.agents.base.litellm_completion")
def test_analyzer_returns_parsed_output(mock_completion):
    inv = _sample_inventory()
    fds = _sample_file_diffs(inv)
    sym = extract_symbol_info(inv)

    mock_completion.return_value = _mock_response({
        "edges": [{"source": "H2", "target": "H1", "reason": "imports", "strength": "must_be_ordered"}],
        "reasoning_summary": "ok",
    })

    agent = DependencyAnalyzerAgent(
        model="gemini/gemini-2.5-flash",
        inventory=inv,
        file_diffs=fds,
        symbol_info=sym,
    )
    out = agent.run()
    assert len(out["edges"]) == 1
    assert out["edges"][0]["source"] == "H2"


@patch("hunknote.compose.agents.base.litellm_completion")
def test_grouper_collects_unassigned(mock_completion):
    inv = _sample_inventory()
    fds = _sample_file_diffs(inv)

    mock_completion.return_value = _mock_response({
        "groups": [{"id": "C1", "hunk_ids": ["H1"], "intent": "models"}],
    })

    agent = GrouperAgent(
        model="gemini/gemini-2.5-flash",
        inventory=inv,
        file_diffs=fds,
    )
    groups = agent.run(dependency_graph={"edges": []}, max_commits=4)

    assert len(groups) == 2
    assert set(groups[1].hunk_ids) == {"H2"}


@patch("hunknote.compose.agents.base.litellm_completion")
def test_orderer_reorders_groups(mock_completion):
    groups = [
        CommitGroup(hunk_ids=["H1"], files=["src/models.py"]),
        CommitGroup(hunk_ids=["H2"], files=["src/api.py"]),
    ]
    mock_completion.return_value = _mock_response({"ordered_group_ids": ["C2", "C1"]})

    agent = OrdererAgent(model="gemini/gemini-2.5-flash")
    ordered = agent.run(groups, dependency_graph={"edges": []})

    assert ordered[0].hunk_ids == ["H2"]


@patch("hunknote.compose.agents.base.litellm_completion")
def test_validator_normalizes_missing_from(mock_completion):
    inv = _sample_inventory()
    fds = _sample_file_diffs(inv)
    sym = extract_symbol_info(inv)
    groups = [
        CommitGroup(hunk_ids=["H2"], files=["src/api.py"]),
        CommitGroup(hunk_ids=["H1"], files=["src/models.py"]),
    ]

    mock_completion.return_value = _mock_response({
        "valid": False,
        "issue_type": "ordering",
        "checkpoints": [
            {
                "checkpoint": 1,
                "commit_id": "C1",
                "valid": False,
                "violations": [{"hunk": "H2", "issue": "imports User", "missing_from": "later commit", "fix": "ordering"}],
            },
        ],
        "fix_reasoning": "reorder",
    })

    agent = CheckpointValidatorAgent(
        model="gemini/gemini-2.5-flash",
        inventory=inv,
        file_diffs=fds,
        symbol_info=sym,
    )
    out = agent.run(groups, dependency_graph={"edges": []})

    violation = out["checkpoints"][0]["violations"][0]
    assert violation["missing_from"].startswith("C")


@patch("hunknote.compose.agents.base.litellm_completion")
def test_validator_keeps_programmatic_invalid_even_if_llm_says_valid(mock_completion):
    inventory = {
        "H1": HunkRef(
            id="H1",
            file_path="hunknote/compose/__init__.py",
            header="@@ -1,0 +1,2 @@",
            old_start=1,
            old_len=0,
            new_start=1,
            new_len=2,
            lines=["+from hunknote.compose.react_agent import run_react_compose_planner"],
        ),
        "H2": HunkRef(
            id="H2",
            file_path="hunknote/compose/react_agent.py",
            header="@@ -1,0 +1,2 @@",
            old_start=1,
            old_len=0,
            new_start=1,
            new_len=2,
            lines=["+def run_react_compose_planner():", "+    return None"],
        ),
    }
    file_diffs = [
        FileDiff(file_path="hunknote/compose/__init__.py", diff_header_lines=["diff"], hunks=[inventory["H1"]]),
        FileDiff(file_path="hunknote/compose/react_agent.py", diff_header_lines=["diff"], hunks=[inventory["H2"]], is_new_file=True),
    ]
    groups = [
        CommitGroup(hunk_ids=["H1"], files=["hunknote/compose/__init__.py"]),
        CommitGroup(hunk_ids=["H2"], files=["hunknote/compose/react_agent.py"]),
    ]
    sym = extract_symbol_info(inventory)

    mock_completion.return_value = _mock_response({
        "valid": True,
        "issue_type": None,
        "checkpoints": [
            {"checkpoint": 1, "commit_id": "C1", "valid": True},
            {"checkpoint": 2, "commit_id": "C2", "valid": True},
        ],
        "fix_reasoning": "",
    })

    agent = CheckpointValidatorAgent(
        model="gemini/gemini-2.5-flash",
        inventory=inventory,
        file_diffs=file_diffs,
        symbol_info=sym,
    )
    out = agent.run(groups, dependency_graph={"edges": []})

    assert out["valid"] is False


@patch("hunknote.compose.agents.base.litellm_completion")
def test_messenger_fallback(mock_completion):
    mock_completion.return_value = _mock_response("not-json")

    groups = [CommitGroup(hunk_ids=["H1"], files=["src/a.py"], reason="test")]
    plan = MessengerAgent(model="gemini/gemini-2.5-flash").run(
        ordered_groups=groups,
        inventory={},
        style="default",
        branch="main",
        recent_commits=[],
    )

    assert len(plan.commits) == 1
    assert plan.commits[0].hunks == ["H1"]


def test_extract_symbol_info_parses_parenthesized_from_import():
    inventory = {
        "H1": HunkRef(
            id="H1",
            file_path="hunknote/compose/__init__.py",
            header="@@ -1,0 +1,3 @@",
            old_start=1,
            old_len=0,
            new_start=1,
            new_len=3,
            lines=[
                "+from hunknote.compose.react_agent import (",
                "+    run_react_compose_planner,",
                "+)",
            ],
        ),
        "H2": HunkRef(
            id="H2",
            file_path="hunknote/compose/react_agent.py",
            header="@@ -1,0 +1,3 @@",
            old_start=1,
            old_len=0,
            new_start=1,
            new_len=3,
            lines=["+def run_react_compose_planner():", "+    return None"],
        ),
    }

    sym = extract_symbol_info(inventory)
    assert "hunknote.compose.react_agent" in sym["H1"].imports


def test_programmatic_validator_detects_module_provider_ordering_violation():
    inventory = {
        "H1": HunkRef(
            id="H1",
            file_path="hunknote/compose/__init__.py",
            header="@@ -1,0 +1,2 @@",
            old_start=1,
            old_len=0,
            new_start=1,
            new_len=2,
            lines=["+from hunknote.compose.react_agent import run_react_compose_planner"],
        ),
        "H2": HunkRef(
            id="H2",
            file_path="hunknote/compose/react_agent.py",
            header="@@ -1,0 +1,2 @@",
            old_start=1,
            old_len=0,
            new_start=1,
            new_len=2,
            lines=["+def run_react_compose_planner():", "+    return None"],
        ),
    }
    file_diffs = [
        FileDiff(file_path="hunknote/compose/__init__.py", diff_header_lines=["diff"], hunks=[inventory["H1"]]),
        FileDiff(file_path="hunknote/compose/react_agent.py", diff_header_lines=["diff"], hunks=[inventory["H2"]], is_new_file=True),
    ]
    symbol_info = extract_symbol_info(inventory)
    ordered_groups = [
        CommitGroup(hunk_ids=["H1"], files=["hunknote/compose/__init__.py"]),
        CommitGroup(hunk_ids=["H2"], files=["hunknote/compose/react_agent.py"]),
    ]

    out = programmatic_checkpoint_validation(ordered_groups, inventory, file_diffs, symbol_info)

    assert out["valid"] is False
    assert out["issue_type"] == "ordering"
    assert out["checkpoints"][0]["valid"] is False


def test_repo_regex_search_reports_matches(mocker, tmp_path):
    mocker.patch(
        "hunknote.compose.agents.tools.subprocess.run",
        return_value=SimpleNamespace(
            returncode=0,
            stdout="a.py:1:from hunknote.compose.react_agent import run_react_compose_planner\n",
            stderr="",
        ),
    )
    payload = json.loads(repo_regex_search(
        pattern=r"run_react_compose_planner",
        repo_root=str(tmp_path),
        path_glob="*.py",
        max_results=10,
    ))
    assert payload["ok"] is True
    assert payload["match_count"] >= 1
