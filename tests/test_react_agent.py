"""Tests for compose ReAct orchestrator."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from hunknote.compose.models import FileDiff, HunkRef
from hunknote.compose.react_agent import OrchestratorAgent, run_react_compose_planner


def _tool_call(name: str, arguments: dict | None = None, tc_id: str = "call_1"):
    return SimpleNamespace(
        id=tc_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments or {})),
    )


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
    usage = SimpleNamespace(prompt_tokens=30, completion_tokens=15, reasoning_tokens=0)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def _inventory_and_files():
    inv = {
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
            header="@@ -1,0 +1,5 @@",
            old_start=1,
            old_len=0,
            new_start=1,
            new_len=5,
            lines=["+from src.models import User", "+def get_user():", "+    return User()"],
        ),
    }
    files = [
        FileDiff(file_path="src/models.py", diff_header_lines=["diff"], hunks=[inv["H1"]]),
        FileDiff(file_path="src/api.py", diff_header_lines=["diff"], hunks=[inv["H2"]]),
    ]
    return inv, files


@patch("hunknote.compose.react_agent.setup_litellm_api_keys")
@patch("hunknote.compose.agents.base.litellm_completion")
@patch("hunknote.compose.react_agent.litellm_completion")
def test_orchestrator_true_react_flow(mock_orch_completion, mock_sub_completion, _mock_keys):
    inv, files = _inventory_and_files()

    # Orchestrator messages: ask for tools across the lifecycle, then complete.
    mock_orch_completion.side_effect = [
        _mock_response("", tool_calls=[_tool_call("call_dependency_analyzer")]),
        _mock_response("", tool_calls=[_tool_call("call_grouper")]),
        _mock_response("", tool_calls=[_tool_call("call_orderer")]),
        _mock_response("", tool_calls=[_tool_call("call_checkpoint_validator")]),
        _mock_response("", tool_calls=[_tool_call("call_messenger")]),
        _mock_response({"status": "complete", "summary": "done"}),
    ]

    # Sub-agent calls in order: analyzer, grouper, orderer, validator, messenger
    mock_sub_completion.side_effect = [
        _mock_response({
            "edges": [{"source": "H2", "target": "H1", "reason": "imports", "strength": "must_be_ordered"}],
            "reasoning_summary": "chain",
        }),
        _mock_response({
            "groups": [
                {"id": "C1", "hunk_ids": ["H1"], "intent": "models"},
                {"id": "C2", "hunk_ids": ["H2"], "intent": "api"},
            ],
        }),
        _mock_response({"ordered_group_ids": ["C1", "C2"]}),
        _mock_response({
            "valid": True,
            "checkpoints": [
                {"checkpoint": 1, "commit_id": "C1", "valid": True},
                {"checkpoint": 2, "commit_id": "C2", "valid": True},
            ],
            "reasoning_summary": "valid",
        }),
        _mock_response({
            "version": "1",
            "warnings": [],
            "commits": [
                {"id": "C1", "type": "feat", "scope": "models", "title": "Add User model", "bullets": ["Add User"], "hunks": ["H1"]},
                {"id": "C2", "type": "feat", "scope": "api", "title": "Add API", "bullets": ["Add get_user"], "hunks": ["H2"]},
            ],
        }),
    ]

    agent = OrchestratorAgent(
        provider_name="google",
        model_name="gemini-2.5-flash",
        inventory=inv,
        file_diffs=files,
        style="default",
        max_commits=4,
        branch="main",
        recent_commits=[],
    )
    result = agent.run()

    assert len(result.plan.commits) == 2
    assert result.plan.commits[0].id == "C1"
    assert result.input_tokens > 0


@patch("hunknote.compose.react_agent.setup_litellm_api_keys")
@patch("hunknote.compose.agents.base.litellm_completion")
@patch("hunknote.compose.react_agent.litellm_completion")
def test_orchestrator_fallback_when_no_tool_progress(mock_orch_completion, mock_sub_completion, _mock_keys):
    inv, files = _inventory_and_files()

    # Orchestrator never calls tools -> should fallback.
    mock_orch_completion.side_effect = [_mock_response({"status": "incomplete"}) for _ in range(14)]
    # Fallback messenger call
    mock_sub_completion.return_value = _mock_response({
        "version": "1",
        "warnings": [],
        "commits": [
            {"id": "C1", "type": "chore", "scope": "", "title": "Fallback", "bullets": ["x"], "hunks": ["H1", "H2"]},
        ],
    })

    res = run_react_compose_planner(
        provider_name="google",
        model_name="gemini-2.5-flash",
        inventory=inv,
        file_diffs=files,
        style="default",
        max_commits=4,
        branch="main",
        recent_commits=[],
    )

    assert len(res.plan.commits) == 1
    assert set(res.plan.commits[0].hunks) == {"H1", "H2"}
