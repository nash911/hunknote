"""Tests for the ReAct orchestrator agent."""

import json
from unittest.mock import MagicMock, patch

import pytest

from hunknote.compose.models import (
    AgentState,
    CommitGroup,
    ComposePlan,
    DependencyEdge,
    DependencyGraph,
    FileDiff,
    HunkRef,
    HunkSymbols,
    PlannedCommit,
)
from hunknote.compose.react_agent import OrchestratorAgent, run_react_agent


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_inventory():
    return {
        "H1_abc": HunkRef(
            id="H1_abc", file_path="src/models.py", header="@@ -1,5 +1,10 @@",
            old_start=1, old_len=5, new_start=1, new_len=10,
            lines=["+class User:", "+    name: str"],
        ),
        "H2_def": HunkRef(
            id="H2_def", file_path="src/api.py", header="@@ -10,3 +10,8 @@",
            old_start=10, old_len=3, new_start=10, new_len=8,
            lines=["+from src.models import User", "+def get_user():"],
        ),
        "H3_ghi": HunkRef(
            id="H3_ghi", file_path="tests/test_api.py", header="@@ -1,0 +1,5 @@",
            old_start=1, old_len=0, new_start=1, new_len=5,
            lines=["+from src.api import get_user", "+def test_get_user():"],
        ),
    }


@pytest.fixture
def sample_file_diffs(sample_inventory):
    inv = sample_inventory
    return [
        FileDiff(file_path="src/models.py", diff_header_lines=["diff"], hunks=[inv["H1_abc"]]),
        FileDiff(file_path="src/api.py", diff_header_lines=["diff"], hunks=[inv["H2_def"]]),
        FileDiff(file_path="tests/test_api.py", diff_header_lines=["diff"], hunks=[inv["H3_ghi"]],
                 is_new_file=True),
    ]


def _make_mock_llm_response(content: dict | str, tool_calls=None):
    """Helper to create a mock LiteLLM response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    msg = response.choices[0].message
    msg.tool_calls = tool_calls
    if isinstance(content, dict):
        msg.content = json.dumps(content)
    else:
        msg.content = content
    msg.model_dump = lambda: {
        "role": "assistant",
        "content": msg.content,
    }
    response.usage = MagicMock(prompt_tokens=100, completion_tokens=50, reasoning_tokens=0)
    return response


# ============================================================
# OrchestratorAgent Tests
# ============================================================

class TestOrchestratorAgent:
    """Tests for the main orchestrator."""

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_full_pipeline(
        self, mock_completion, mock_setup_keys,
        sample_inventory, sample_file_diffs,
    ):
        """Test the full orchestrator pipeline with mocked LLM calls."""
        # Set up sequential mock responses for each sub-agent call
        responses = [
            # 1. Dependency Analyzer
            _make_mock_llm_response({
                "edges": [
                    {"source": "H2_def", "target": "H1_abc",
                     "reason": "imports User", "strength": "must_be_ordered"},
                    {"source": "H3_ghi", "target": "H2_def",
                     "reason": "tests get_user", "strength": "must_be_ordered"},
                ],
                "independent_hunks": [],
                "reasoning_summary": "Linear chain.",
            }),
            # 2. Grouper
            _make_mock_llm_response({
                "groups": [
                    {"id": "C1", "hunk_ids": ["H1_abc"], "intent": "Add model"},
                    {"id": "C2", "hunk_ids": ["H2_def"], "intent": "Add API"},
                    {"id": "C3", "hunk_ids": ["H3_ghi"], "intent": "Add tests"},
                ],
            }),
            # 3. Orderer
            _make_mock_llm_response({
                "ordered_group_ids": ["C1", "C2", "C3"],
            }),
            # 4. Validator
            _make_mock_llm_response({
                "valid": True,
                "checkpoints": [
                    {"checkpoint": 1, "commit_id": "C1", "valid": True},
                    {"checkpoint": 2, "commit_id": "C2", "valid": True},
                    {"checkpoint": 3, "commit_id": "C3", "valid": True},
                ],
            }),
            # 5. Messenger
            _make_mock_llm_response({
                "version": "1",
                "warnings": [],
                "commits": [
                    {"id": "C1", "type": "feat", "scope": "models",
                     "title": "Add User model", "hunks": ["H1_abc"],
                     "bullets": ["Add User dataclass"]},
                    {"id": "C2", "type": "feat", "scope": "api",
                     "title": "Add user endpoint", "hunks": ["H2_def"],
                     "bullets": ["Add get_user function"]},
                    {"id": "C3", "type": "test", "scope": "api",
                     "title": "Add API tests", "hunks": ["H3_ghi"],
                     "bullets": ["Add test_get_user"]},
                ],
            }),
        ]
        mock_completion.side_effect = responses

        orchestrator = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
            style="blueprint",
        )
        state = orchestrator.run()

        assert state.plan is not None
        assert len(state.plan.commits) == 3
        assert state.plan.commits[0].id == "C1"
        assert state.plan.commits[0].type == "feat"
        assert state.dependency_graph is not None
        assert len(state.dependency_graph.edges) == 2

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_validation_retry_ordering_issue(
        self, mock_completion, mock_setup_keys,
        sample_inventory, sample_file_diffs,
    ):
        """Test that ordering issues trigger re-ordering only."""
        responses = [
            # Analyzer
            _make_mock_llm_response({
                "edges": [{"source": "H2_def", "target": "H1_abc",
                           "reason": "imports User", "strength": "must_be_ordered"}],
                "independent_hunks": ["H3_ghi"],
            }),
            # Grouper
            _make_mock_llm_response({
                "groups": [
                    {"id": "C1", "hunk_ids": ["H1_abc"]},
                    {"id": "C2", "hunk_ids": ["H2_def"]},
                    {"id": "C3", "hunk_ids": ["H3_ghi"]},
                ],
            }),
            # Orderer
            _make_mock_llm_response({
                "ordered_group_ids": ["C2", "C1", "C3"],  # Wrong order!
            }),
            # Validator (first attempt: FAILS with ordering issue)
            _make_mock_llm_response({
                "valid": False,
                "issue_type": "ordering",
                "checkpoints": [
                    {"checkpoint": 1, "commit_id": "C2", "valid": False,
                     "violations": [{"commit": "C2", "hunk": "H2_def",
                                     "issue": "imports User not yet committed",
                                     "missing_from": "C1",
                                     "fix": "ordering"}]},
                ],
                "fix_reasoning": "C1 (defines User) must come before C2 (imports User)",
            }),
            # Orderer (re-called with hint — correct order now)
            _make_mock_llm_response({
                "ordered_group_ids": ["C1", "C2", "C3"],
            }),
            # Validator (second attempt: PASSES)
            _make_mock_llm_response({
                "valid": True,
                "checkpoints": [
                    {"checkpoint": 1, "commit_id": "C1", "valid": True},
                    {"checkpoint": 2, "commit_id": "C2", "valid": True},
                    {"checkpoint": 3, "commit_id": "C3", "valid": True},
                ],
            }),
            # Messenger
            _make_mock_llm_response({
                "version": "1",
                "warnings": [],
                "commits": [
                    {"id": "C1", "type": "feat", "title": "Add User model",
                     "hunks": ["H1_abc"]},
                    {"id": "C2", "type": "feat", "title": "Add API",
                     "hunks": ["H2_def"]},
                    {"id": "C3", "type": "test", "title": "Add tests",
                     "hunks": ["H3_ghi"]},
                ],
            }),
        ]
        mock_completion.side_effect = responses

        orchestrator = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
            style="blueprint",
        )
        state = orchestrator.run()

        assert state.plan is not None
        assert len(state.plan.commits) == 3

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_validation_retry_grouping_issue(
        self, mock_completion, mock_setup_keys,
        sample_inventory, sample_file_diffs,
    ):
        """Test that grouping issues trigger re-grouping + re-ordering."""
        responses = [
            # Analyzer
            _make_mock_llm_response({
                "edges": [{"source": "H2_def", "target": "H1_abc",
                           "reason": "imports User", "strength": "must_be_together"}],
                "independent_hunks": ["H3_ghi"],
            }),
            # Grouper (incorrectly puts H1 and H2 in separate groups)
            _make_mock_llm_response({
                "groups": [
                    {"id": "C1", "hunk_ids": ["H1_abc"]},
                    {"id": "C2", "hunk_ids": ["H2_def"]},
                    {"id": "C3", "hunk_ids": ["H3_ghi"]},
                ],
            }),
            # Orderer
            _make_mock_llm_response({
                "ordered_group_ids": ["C1", "C2", "C3"],
            }),
            # Validator (FAILS with grouping issue)
            _make_mock_llm_response({
                "valid": False,
                "issue_type": "grouping",
                "checkpoints": [
                    {"checkpoint": 1, "commit_id": "C1", "valid": True},
                    {"checkpoint": 2, "commit_id": "C2", "valid": False,
                     "violations": [{"commit": "C2", "hunk": "H2_def",
                                     "issue": "must_be_together with H1_abc",
                                     "missing_from": "C1",
                                     "fix": "grouping"}]},
                ],
                "fix_reasoning": "H1_abc and H2_def have must_be_together dep, should be in same group",
            }),
            # Grouper (re-called with hint — merges H1+H2)
            _make_mock_llm_response({
                "groups": [
                    {"id": "C1", "hunk_ids": ["H1_abc", "H2_def"]},
                    {"id": "C2", "hunk_ids": ["H3_ghi"]},
                ],
            }),
            # Orderer (re-called after regrouping)
            _make_mock_llm_response({
                "ordered_group_ids": ["C1", "C2"],
            }),
            # Validator (PASSES)
            _make_mock_llm_response({
                "valid": True,
                "checkpoints": [
                    {"checkpoint": 1, "commit_id": "C1", "valid": True},
                    {"checkpoint": 2, "commit_id": "C2", "valid": True},
                ],
            }),
            # Messenger
            _make_mock_llm_response({
                "version": "1",
                "warnings": [],
                "commits": [
                    {"id": "C1", "type": "feat", "title": "Add core",
                     "hunks": ["H1_abc", "H2_def"]},
                    {"id": "C2", "type": "test", "title": "Add tests",
                     "hunks": ["H3_ghi"]},
                ],
            }),
        ]
        mock_completion.side_effect = responses

        orchestrator = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
            style="blueprint",
        )
        state = orchestrator.run()

        assert state.plan is not None
        assert len(state.plan.commits) == 2

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_fallback_on_persistent_failure(
        self, mock_completion, mock_setup_keys,
        sample_inventory, sample_file_diffs,
    ):
        """Test fallback to single commit when all retries fail."""
        # When issue_type is missing/null, the orchestrator falls back
        # to programmatic merge, then re-validates.
        responses = [
            # Analyzer
            _make_mock_llm_response({"edges": [], "independent_hunks": list(sample_inventory.keys())}),
            # Grouper
            _make_mock_llm_response({"groups": [
                {"id": "C1", "hunk_ids": ["H1_abc"]},
                {"id": "C2", "hunk_ids": ["H2_def"]},
                {"id": "C3", "hunk_ids": ["H3_ghi"]},
            ]}),
            # Orderer
            _make_mock_llm_response({"ordered_group_ids": ["C1", "C2", "C3"]}),
            # Validator fails 4 times (initial + 3 retries), no issue_type
            _make_mock_llm_response({"valid": False, "checkpoints": []}),
            _make_mock_llm_response({"valid": False, "checkpoints": []}),
            _make_mock_llm_response({"valid": False, "checkpoints": []}),
            _make_mock_llm_response({"valid": False, "checkpoints": []}),
            # Messenger (for the single merged group)
            _make_mock_llm_response({
                "version": "1", "warnings": [],
                "commits": [{"id": "C1", "type": "feat", "title": "All changes",
                              "hunks": sorted(sample_inventory.keys())}],
            }),
        ]
        mock_completion.side_effect = responses

        orchestrator = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
            style="blueprint",
        )
        state = orchestrator.run()

        assert state.plan is not None
        # Should have fallen back to single commit
        assert len(state.plan.commits) == 1


# ============================================================
# run_react_agent() convenience function
# ============================================================

class TestRunReactAgent:
    """Tests for the convenience function."""

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_convenience_function(
        self, mock_completion, mock_setup_keys,
        sample_inventory, sample_file_diffs,
    ):
        # Minimal responses for a simple pass-through
        responses = [
            _make_mock_llm_response({"edges": [], "independent_hunks": list(sample_inventory.keys())}),
            _make_mock_llm_response({"groups": [{"id": "C1", "hunk_ids": sorted(sample_inventory.keys())}]}),
            _make_mock_llm_response({"ordered_group_ids": ["C1"]}),
            _make_mock_llm_response({"valid": True, "checkpoints": [{"checkpoint": 1, "valid": True}]}),
            _make_mock_llm_response({
                "version": "1", "warnings": [],
                "commits": [{"id": "C1", "type": "feat", "title": "All changes",
                              "hunks": sorted(sample_inventory.keys())}],
            }),
        ]
        mock_completion.side_effect = responses

        state = run_react_agent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )

        assert isinstance(state, AgentState)
        assert state.plan is not None
        assert len(state.plan.commits) >= 1


# ============================================================
# Integration with agent.py wiring
# ============================================================

class TestAgentWiring:
    """Tests for run_compose_agent() delegation to ReAct agent."""

    def test_get_provider_name(self):
        """Test the _get_provider_name helper."""
        from hunknote.compose.agent import _get_provider_name

        class GoogleProvider:
            pass
        class AnthropicProvider:
            pass
        class OpenAIProvider:
            pass
        class MockGoogleProvider:
            pass

        assert _get_provider_name(GoogleProvider()) == "google"
        assert _get_provider_name(AnthropicProvider()) == "anthropic"
        assert _get_provider_name(OpenAIProvider()) == "openai"
        assert _get_provider_name(MockGoogleProvider()) == "google"

    def test_get_provider_name_unknown(self):
        from hunknote.compose.agent import _get_provider_name

        class SomeRandomProvider:
            pass
        assert _get_provider_name(SomeRandomProvider()) == "google"

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_run_compose_agent_uses_react(
        self, mock_completion, mock_setup_keys,
        sample_inventory, sample_file_diffs,
    ):
        """Test that run_compose_agent delegates to ReAct when use_react=True."""
        from hunknote.compose.agent import run_compose_agent

        responses = [
            _make_mock_llm_response({"edges": [], "independent_hunks": sorted(sample_inventory.keys())}),
            _make_mock_llm_response({"groups": [{"id": "C1", "hunk_ids": sorted(sample_inventory.keys())}]}),
            _make_mock_llm_response({"ordered_group_ids": ["C1"]}),
            _make_mock_llm_response({"valid": True, "checkpoints": []}),
            _make_mock_llm_response({
                "version": "1", "warnings": [],
                "commits": [{"id": "C1", "type": "feat", "title": "All changes",
                              "hunks": sorted(sample_inventory.keys())}],
            }),
        ]
        mock_completion.side_effect = responses

        class MockGoogleProvider:
            model = "gemini-2.5-flash"

        mock_provider = MockGoogleProvider()

        result = run_compose_agent(
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
            style="blueprint",
            max_commits=16,
            force_agent=True,
            provider=mock_provider,
            use_react=True,
        )

        assert result.used_agent is True
        assert len(result.plan.commits) == 1

    def test_run_compose_agent_programmatic_fallback(
        self, sample_inventory, sample_file_diffs,
    ):
        """Test that use_react=False uses the programmatic pipeline."""
        from hunknote.compose.agent import run_compose_agent

        mock_provider = MagicMock()
        mock_provider.model = "gemini-2.5-flash"
        mock_provider.generate_raw.return_value = MagicMock(
            model="gemini-2.5-flash",
            raw_response=json.dumps({
                "version": "1", "warnings": [],
                "commits": [{"id": "C1", "type": "feat", "title": "All changes",
                              "hunks": sorted(sample_inventory.keys())}],
            }),
            input_tokens=100,
            output_tokens=50,
            thinking_tokens=0,
        )

        result = run_compose_agent(
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
            style="blueprint",
            max_commits=16,
            force_agent=True,
            provider=mock_provider,
            use_react=False,
        )

        assert result.used_agent is True
        # Should have used the programmatic pipeline + LLM messaging
        mock_provider.generate_raw.assert_called_once()


# ============================================================
# False-positive filtering tests
# ============================================================

class TestFilterFalsePositives:
    """Tests for OrchestratorAgent._filter_false_positives."""

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    def test_filters_existing_file_violations(
        self, mock_setup_keys, sample_inventory, sample_file_diffs,
    ):
        """Violations mentioning existing files should be filtered out."""
        orch = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )
        validation_result = {
            "valid": False,
            "issue_type": "ordering",
            "checkpoints": [
                {"checkpoint": 1, "commit_id": "C1", "valid": False,
                 "violations": [
                     {"commit": "C1", "hunk": "H2_def",
                      "issue": "references symbol from src/models.py, not yet committed",
                      "missing_from": "C2", "fix": "ordering"},
                 ]},
            ],
        }
        # src/models.py is NOT a new file in sample_file_diffs → false positive
        result = orch._filter_false_positives(validation_result)
        assert result["valid"] is True

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    def test_keeps_new_file_violations(
        self, mock_setup_keys, sample_inventory, sample_file_diffs,
    ):
        """Violations mentioning new files should be kept."""
        orch = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )
        validation_result = {
            "valid": False,
            "issue_type": "ordering",
            "checkpoints": [
                {"checkpoint": 1, "commit_id": "C1", "valid": False,
                 "violations": [
                     {"commit": "C1", "hunk": "H2_def",
                      "issue": "imports get_user from tests/test_api, not yet committed",
                      "missing_from": "C3", "fix": "ordering"},
                 ]},
            ],
        }
        # tests/test_api.py IS a new file → real violation
        result = orch._filter_false_positives(validation_result)
        assert result["valid"] is False

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    def test_keeps_generic_violations(
        self, mock_setup_keys, sample_inventory, sample_file_diffs,
    ):
        """Violations that don't mention any file path should be kept."""
        orch = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )
        validation_result = {
            "valid": False,
            "issue_type": "grouping",
            "checkpoints": [
                {"checkpoint": 1, "commit_id": "C1", "valid": False,
                 "violations": [
                     {"commit": "C1", "hunk": "H2_def",
                      "issue": "must_be_together with H1_abc",
                      "missing_from": "C2", "fix": "grouping"},
                 ]},
            ],
        }
        result = orch._filter_false_positives(validation_result)
        # Generic violation (no file path) → should be kept
        assert result["valid"] is False

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    def test_no_filter_on_empty_checkpoints(
        self, mock_setup_keys, sample_inventory, sample_file_diffs,
    ):
        """Empty checkpoints list should not cause valid=True."""
        orch = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )
        validation_result = {
            "valid": False,
            "checkpoints": [],
        }
        result = orch._filter_false_positives(validation_result)
        assert result["valid"] is False


# ============================================================
# Violation detail formatting tests
# ============================================================

class TestFormatViolationDetails:
    """Tests for OrchestratorAgent._format_violation_details."""

    def test_formats_violations(self):
        validation_result = {
            "checkpoints": [
                {"checkpoint": 1, "commit_id": "C1", "valid": True},
                {"checkpoint": 2, "commit_id": "C2", "valid": False,
                 "violations": [
                     {"commit": "C2", "hunk": "H5_jkl",
                      "issue": "imports foo from new file bar",
                      "missing_from": "C4", "fix": "ordering"},
                 ]},
            ],
        }
        result = OrchestratorAgent._format_violation_details(validation_result)
        assert "C2/H5_jkl" in result
        assert "imports foo" in result
        assert "needs C4" in result

    def test_no_violations(self):
        validation_result = {
            "checkpoints": [
                {"checkpoint": 1, "commit_id": "C1", "valid": True},
            ],
        }
        result = OrchestratorAgent._format_violation_details(validation_result)
        assert "no specific violations" in result


# ============================================================
# State tracking & previous-state formatting tests
# ============================================================

class TestStateTracking:
    """Tests for OrchestratorAgent state history tracking."""

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    def test_initial_state_history_is_empty(
        self, mock_setup_keys, sample_inventory, sample_file_diffs,
    ):
        """All state history lists should be empty after init."""
        orch = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )
        assert orch._dep_graph is None
        assert orch._groups_history == []
        assert orch._ordered_history == []
        assert orch._validation_history == []


class TestFormatPreviousGroups:
    """Tests for OrchestratorAgent._format_previous_groups."""

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    def test_empty_history(
        self, mock_setup_keys, sample_inventory, sample_file_diffs,
    ):
        orch = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )
        result = orch._format_previous_groups()
        assert "no previous grouping" in result

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    def test_formats_groups(
        self, mock_setup_keys, sample_inventory, sample_file_diffs,
    ):
        orch = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )
        orch._groups_history.append([
            CommitGroup(
                hunk_ids=["H1_abc", "H2_def"],
                files=["src/models.py", "src/api.py"],
                reason="core models and API",
            ),
            CommitGroup(
                hunk_ids=["H3_ghi"],
                files=["tests/test_api.py"],
                reason="tests",
            ),
        ])
        result = orch._format_previous_groups()
        assert "C1" in result
        assert "H1_abc" in result
        assert "H2_def" in result
        assert "C2" in result
        assert "H3_ghi" in result
        assert "core models and API" in result

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    def test_uses_latest_history_entry(
        self, mock_setup_keys, sample_inventory, sample_file_diffs,
    ):
        """Should format the MOST RECENT grouping attempt."""
        orch = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )
        # First attempt
        orch._groups_history.append([
            CommitGroup(hunk_ids=["H1_abc"], files=["src/models.py"], reason="old"),
        ])
        # Second attempt (latest)
        orch._groups_history.append([
            CommitGroup(hunk_ids=["H1_abc", "H2_def"], files=["src/models.py", "src/api.py"],
                        reason="updated"),
        ])
        result = orch._format_previous_groups()
        assert "updated" in result
        # Should NOT contain the old entry as separate group
        assert result.count("C1") == 1


class TestFormatPreviousOrdering:
    """Tests for OrchestratorAgent._format_previous_ordering."""

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    def test_empty_history(
        self, mock_setup_keys, sample_inventory, sample_file_diffs,
    ):
        orch = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )
        result = orch._format_previous_ordering()
        assert "no previous ordering" in result

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    def test_formats_ordering(
        self, mock_setup_keys, sample_inventory, sample_file_diffs,
    ):
        orch = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )
        orch._ordered_history.append([
            CommitGroup(hunk_ids=["H3_ghi"], files=["tests/test_api.py"], reason="tests"),
            CommitGroup(hunk_ids=["H1_abc"], files=["src/models.py"], reason="models"),
        ])
        result = orch._format_previous_ordering()
        assert "Position 1" in result
        assert "Position 2" in result
        assert "H3_ghi" in result
        assert "H1_abc" in result

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    def test_includes_validation_summary(
        self, mock_setup_keys, sample_inventory, sample_file_diffs,
    ):
        """Should include the latest validator summary when available."""
        orch = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )
        orch._ordered_history.append([
            CommitGroup(hunk_ids=["H1_abc"], files=["src/models.py"], reason="m"),
        ])
        orch._validation_history.append({
            "valid": False,
            "reasoning_summary": "C1 imports from C2",
        })
        result = orch._format_previous_ordering()
        assert "C1 imports from C2" in result


# ============================================================
# Oscillation tolerance tests
# ============================================================

class TestOscillationTolerance:
    """Tests that oscillation detection requires 4 consecutive same-type issues."""

    @patch("hunknote.compose.react_agent.setup_litellm_api_keys")
    @patch("hunknote.compose.agents.base.litellm_completion")
    def test_no_oscillation_with_two_same_type(
        self, mock_completion, mock_setup_keys,
        sample_inventory, sample_file_diffs,
    ):
        """Two consecutive same-type issues should NOT trigger oscillation merge."""
        responses = [
            # Analyzer
            _make_mock_llm_response({"edges": [], "independent_hunks": list(sample_inventory.keys())}),
            # Grouper
            _make_mock_llm_response({"groups": [
                {"id": "C1", "hunk_ids": ["H1_abc"]},
                {"id": "C2", "hunk_ids": ["H2_def"]},
                {"id": "C3", "hunk_ids": ["H3_ghi"]},
            ]}),
            # Orderer
            _make_mock_llm_response({"ordered_group_ids": ["C1", "C2", "C3"]}),
            # Validator fails: ordering issue
            _make_mock_llm_response({
                "valid": False, "issue_type": "ordering",
                "checkpoints": [
                    {"checkpoint": 1, "commit_id": "C1", "valid": False,
                     "violations": [{"commit": "C1", "hunk": "H1_abc",
                                     "issue": "needs C2", "missing_from": "C2", "fix": "ordering"}]},
                ],
                "fix_reasoning": "C1 needs C2 first",
            }),
            # Orderer retry
            _make_mock_llm_response({"ordered_group_ids": ["C2", "C1", "C3"]}),
            # Validator fails again: ordering issue (2nd consecutive)
            _make_mock_llm_response({
                "valid": False, "issue_type": "ordering",
                "checkpoints": [
                    {"checkpoint": 1, "commit_id": "C2", "valid": False,
                     "violations": [{"commit": "C2", "hunk": "H2_def",
                                     "issue": "needs C3", "missing_from": "C3", "fix": "ordering"}]},
                ],
                "fix_reasoning": "C2 needs C3 first",
            }),
            # Orderer retry #2 (should still try, not oscillation-merge)
            _make_mock_llm_response({"ordered_group_ids": ["C3", "C2", "C1"]}),
            # Validator passes
            _make_mock_llm_response({
                "valid": True,
                "checkpoints": [
                    {"checkpoint": 1, "commit_id": "C3", "valid": True},
                    {"checkpoint": 2, "commit_id": "C2", "valid": True},
                    {"checkpoint": 3, "commit_id": "C1", "valid": True},
                ],
            }),
            # Messenger
            _make_mock_llm_response({
                "version": "1", "warnings": [],
                "commits": [
                    {"id": "C1", "type": "feat", "title": "A", "hunks": ["H3_ghi"]},
                    {"id": "C2", "type": "feat", "title": "B", "hunks": ["H2_def"]},
                    {"id": "C3", "type": "feat", "title": "C", "hunks": ["H1_abc"]},
                ],
            }),
        ]
        mock_completion.side_effect = responses

        orch = OrchestratorAgent(
            provider_name="google",
            model_name="gemini-2.5-flash",
            file_diffs=sample_file_diffs,
            inventory=sample_inventory,
        )
        state = orch.run()

        # Should have kept 3 commits (no oscillation merge)
        assert state.plan is not None
        assert len(state.plan.commits) == 3

        # Verify no oscillation_merge trace entry
        oscillation_phases = [
            t for t in state.trace_log
            if "details" in t and "oscillation" in t.get("phase", "")
        ]
        assert len(oscillation_phases) == 0
