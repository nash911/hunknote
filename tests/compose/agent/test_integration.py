"""End-to-end integration test for the Compose Agent pipeline.

Exercises the full pipeline from orchestrator through all 6 phases
using a mock LLM, verifying that phases connect correctly and produce
a valid ComposePlan.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hunknote.compose.agent.models import (
    CommitGroup,
    DependencyGraph,
    FrozenBaseline,
    HunkSummary,
    Remediation,
    RemediationAction,
    ValidationFailure,
    ValidationLayer,
)
from hunknote.compose.agent.orchestrator import (
    AgentOrchestrator,
    OrchestratorConfig,
)
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.models import ComposePlan, FileDiff, HunkRef
from hunknote.llm.base import RawLLMResult


def _make_llm_response(text, input_tokens=50, output_tokens=30):
    """Helper to build a RawLLMResult."""
    return RawLLMResult(
        raw_response=text,
        model="test-model",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class TestEndToEndPipeline:
    """Full pipeline integration test with mock LLM and mocked validation."""

    @pytest.fixture
    def mock_llm(self):
        """LLM that routes responses based on system prompt content."""
        call_log = []

        def llm_fn(system_prompt: str, user_prompt: str) -> RawLLMResult:
            call_log.append({"system": system_prompt[:100], "user": user_prompt[:100]})
            sp = system_prompt.lower()

            # Phase 1: Summarize (matches "analyzing code changes")
            if "analyzing code changes" in sp:
                # Parser expects JSON array, not dict
                return _make_llm_response(json.dumps([
                    {"hunk_id": "H1_abc123", "file_path": "foo.py",
                     "intent": "Add hello function", "category": "feature",
                     "symbols_modified": ["hello"], "symbols_referenced": ["os"]},
                    {"hunk_id": "H2_def456", "file_path": "foo.py",
                     "intent": "Add goodbye function", "category": "feature",
                     "symbols_modified": ["goodbye"], "symbols_referenced": []},
                    {"hunk_id": "H3_789ghi", "file_path": "bar.py",
                     "intent": "Call hello from bar", "category": "feature",
                     "symbols_modified": ["result"], "symbols_referenced": ["hello"]},
                    {"hunk_id": "H4_jkl012", "file_path": "tests/test_foo.py",
                     "intent": "Add test for hello", "category": "test",
                     "symbols_modified": ["test_hello"], "symbols_referenced": ["hello"]},
                    {"hunk_id": "H5_mno345", "file_path": "new_module.py",
                     "intent": "Add new module", "category": "feature",
                     "symbols_modified": ["new_func"], "symbols_referenced": [],
                     "is_new_file": True},
                ]))

            # Phase 2: Dependency graph (matches "expert code analyst")
            if "expert code analyst" in sp:
                return _make_llm_response(
                    'Thought: Done analyzing.\n'
                    'Output:\n```json\n'
                    + json.dumps({"edges": [
                        {"from": "H3_789ghi", "to": "H1_abc123",
                         "type": "directional", "reason": "bar imports hello from foo"},
                        {"from": "H4_jkl012", "to": "H1_abc123",
                         "type": "directional", "reason": "test imports hello"},
                    ]})
                    + '\n```'
                )

            # Phase 3: Clustering (matches "grouping code changes")
            if "grouping code changes" in sp:
                return _make_llm_response(json.dumps({
                    "groups": [
                        {"id": "_G1", "hunks": ["H1_abc123", "H4_jkl012"],
                         "theme": "Add hello with tests", "category": "feature"},
                        {"id": "_G2", "hunks": ["H2_def456"],
                         "theme": "Add goodbye", "category": "feature"},
                        {"id": "_G3", "hunks": ["H3_789ghi"],
                         "theme": "Integrate bar", "category": "feature"},
                        {"id": "_G4", "hunks": ["H5_mno345"],
                         "theme": "New module", "category": "feature"},
                    ]
                }))

            # Phase 4: Ordering tie-break (matches "ordering commit groups")
            if "ordering commit groups" in sp:
                return _make_llm_response(json.dumps(
                    ["_G1", "_G4", "_G2", "_G3"]
                ))

            # Phase 6: Messages (matches "commit message")
            if "commit message" in sp:
                return _make_llm_response(json.dumps({
                    "title": "Add functionality",
                    "type": "feat",
                    "body": ["Added new code"],
                }))

            # Default fallback
            return _make_llm_response("{}")

        llm_fn.call_log = call_log
        return llm_fn

    @patch("hunknote.compose.agent.orchestrator.run_phase5a_validate")
    def test_full_pipeline_produces_valid_plan(
        self, mock_validate, inventory, all_file_diffs, temp_repo, mock_llm,
    ):
        """End-to-end: orchestrator produces a ComposePlan with multiple commits."""
        # Skip actual git worktree validation
        mock_validate.return_value = (None, FrozenBaseline())

        config = OrchestratorConfig(max_commits=6)
        trace = AgentTrace()
        orch = AgentOrchestrator(
            all_file_diffs, inventory, temp_repo,
            mock_llm, config, trace,
        )
        plan = orch.run()

        assert isinstance(plan, ComposePlan)
        assert len(plan.commits) >= 2  # Must produce multiple commits
        # All hunk IDs should be covered
        all_assigned = set()
        for c in plan.commits:
            all_assigned.update(c.hunks)
        assert all_assigned == set(inventory.keys())

    @patch("hunknote.compose.agent.orchestrator.run_phase5a_validate")
    def test_trace_records_all_phases(
        self, mock_validate, inventory, all_file_diffs, temp_repo, mock_llm,
    ):
        """Trace records phase_start/phase_end for all 6 phases."""
        mock_validate.return_value = (None, FrozenBaseline())

        config = OrchestratorConfig()
        trace = AgentTrace()
        orch = AgentOrchestrator(
            all_file_diffs, inventory, temp_repo,
            mock_llm, config, trace,
        )
        plan = orch.run()

        # Check phase events recorded in trace
        phase_names = set()
        for child in trace.root.children:
            if hasattr(child, 'phase'):
                phase_names.add(child.phase)

        assert "phase1" in phase_names
        assert "phase2" in phase_names
        assert "phase3" in phase_names
        assert "phase4" in phase_names
        assert "phase5" in phase_names
        assert "phase6" in phase_names

    @patch("hunknote.compose.agent.orchestrator.run_phase5a_validate")
    def test_llm_called_for_each_phase(
        self, mock_validate, inventory, all_file_diffs, temp_repo, mock_llm,
    ):
        """LLM is called at least once per phase that uses it."""
        mock_validate.return_value = (None, FrozenBaseline())

        config = OrchestratorConfig()
        orch = AgentOrchestrator(
            all_file_diffs, inventory, temp_repo,
            mock_llm, config,
        )
        plan = orch.run()

        # Should have been called for phases 1, 2, 3, 4, 6
        assert len(mock_llm.call_log) >= 5

    @patch("hunknote.compose.agent.orchestrator.run_phase5a_validate")
    def test_token_tracking(
        self, mock_validate, inventory, all_file_diffs, temp_repo, mock_llm,
    ):
        """Trace accumulates token counts from LLM calls."""
        mock_validate.return_value = (None, FrozenBaseline())

        config = OrchestratorConfig()
        trace = AgentTrace()
        orch = AgentOrchestrator(
            all_file_diffs, inventory, temp_repo,
            mock_llm, config, trace,
        )
        plan = orch.run()

        summary = trace.get_summary()
        assert summary["total_llm_calls"] > 0
        assert summary["total_input_tokens"] > 0


class TestEndToEndWithRetry:
    """Integration test verifying the retry loop works end-to-end."""

    @patch("hunknote.compose.agent.orchestrator.run_phase6_messages")
    @patch("hunknote.compose.agent.orchestrator.run_phase5b_diagnose")
    @patch("hunknote.compose.agent.orchestrator.run_phase5a_validate")
    @patch("hunknote.compose.agent.orchestrator.run_phase4_order")
    @patch("hunknote.compose.agent.orchestrator.run_phase3_cluster")
    @patch("hunknote.compose.agent.orchestrator.run_phase2_dependency_graph")
    @patch("hunknote.compose.agent.orchestrator.run_phase1_summarize")
    def test_retry_converges(
        self, mock_p1, mock_p2, mock_p3, mock_p4, mock_p5a, mock_p5b, mock_p6,
        inventory, all_file_diffs, temp_repo, summaries,
    ):
        """Pipeline retries once with reorder remediation and succeeds."""
        groups = [
            CommitGroup(group_id="_G1", hunk_ids=["H1_abc123", "H4_jkl012"],
                        theme="Hello with tests", category="feature"),
            CommitGroup(group_id="_G2", hunk_ids=["H2_def456", "H5_mno345"],
                        theme="Other functions", category="feature"),
            CommitGroup(group_id="_G3", hunk_ids=["H3_789ghi"],
                        theme="Bar integration", category="feature"),
        ]
        ordered = [
            CommitGroup(group_id="C1", hunk_ids=["H1_abc123", "H4_jkl012"],
                        theme="Hello with tests", category="feature"),
            CommitGroup(group_id="C2", hunk_ids=["H3_789ghi"],
                        theme="Bar integration", category="feature"),
            CommitGroup(group_id="C3", hunk_ids=["H2_def456", "H5_mno345"],
                        theme="Other functions", category="feature"),
        ]

        mock_p1.return_value = summaries
        mock_p2.return_value = DependencyGraph()
        mock_p3.return_value = groups
        mock_p4.return_value = ordered

        # First validate fails, second succeeds
        failure = ValidationFailure(
            commit_index=1,
            commit_group=ordered[1],
            layer=ValidationLayer.IMPORT,
            error_output="ImportError",
        )
        mock_p5a.side_effect = [
            (failure, FrozenBaseline()),
            (None, FrozenBaseline()),
        ]

        mock_p5b.return_value = Remediation(
            action=RemediationAction.REORDER,
            diagnosis="Wrong commit order",
            modifications={},
        )

        from hunknote.compose.models import PlannedCommit
        mock_p6.return_value = [
            PlannedCommit(id="C1", title="Hello", type="feat",
                          hunks=["H1_abc123", "H4_jkl012"]),
            PlannedCommit(id="C2", title="Bar", type="feat",
                          hunks=["H3_789ghi"]),
            PlannedCommit(id="C3", title="Other", type="feat",
                          hunks=["H2_def456", "H5_mno345"]),
        ]

        llm_fn = MagicMock()
        config = OrchestratorConfig(max_retries=2)
        trace = AgentTrace()
        orch = AgentOrchestrator(
            all_file_diffs, inventory, temp_repo, llm_fn, config, trace,
        )
        plan = orch.run()

        assert isinstance(plan, ComposePlan)
        assert len(plan.commits) == 3
        assert mock_p5a.call_count == 2
        assert mock_p5b.call_count == 1
        assert orch.retry_count == 1
