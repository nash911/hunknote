"""Tests for hunknote.compose.agent.orchestrator — Agent pipeline state machine."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hunknote.compose.agent.models import (
    CommitGroup,
    DependencyGraph,
    FrozenBaseline,
    FrozenCommit,
    HunkSummary,
    Remediation,
    RemediationAction,
    ValidationFailure,
    ValidationLayer,
)
from hunknote.compose.agent.orchestrator import (
    AgentOrchestrator,
    AgentPipelineError,
    OrchestratorConfig,
)
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.models import ComposePlan, FileDiff, HunkRef, PlannedCommit
from hunknote.llm.base import RawLLMResult


# ── OrchestratorConfig ──


class TestOrchestratorConfig:
    """Tests for OrchestratorConfig defaults."""

    def test_defaults(self):
        cfg = OrchestratorConfig()
        assert cfg.max_retries == 3
        assert cfg.max_commits == 6
        assert cfg.run_tests is False

    def test_custom_values(self):
        cfg = OrchestratorConfig(max_retries=5, max_commits=10, run_tests=True)
        assert cfg.max_retries == 5
        assert cfg.max_commits == 10
        assert cfg.run_tests is True


# ── AgentPipelineError ──


class TestAgentPipelineError:
    """Tests for AgentPipelineError."""

    def test_error_with_diagnosis(self):
        err = AgentPipelineError("Pipeline failed", diagnosis="Import error in bar.py")
        assert str(err) == "Pipeline failed"
        assert err.diagnosis == "Import error in bar.py"

    def test_error_without_diagnosis(self):
        err = AgentPipelineError("Failed")
        assert err.diagnosis == ""


# ── AgentOrchestrator ──


class TestOrchestratorRun:
    """Tests for the orchestrator run() method with all phases mocked."""

    @pytest.fixture
    def mock_summaries(self, inventory):
        return {
            hid: HunkSummary(
                hunk_id=hid, file_path=h.file_path,
                intent=f"Change in {h.file_path}", category="feature",
            )
            for hid, h in inventory.items()
        }

    @pytest.fixture
    def mock_groups(self):
        return [
            CommitGroup(group_id="_G1", hunk_ids=["H1_abc123", "H2_def456"],
                        theme="Foo changes", category="feature"),
            CommitGroup(group_id="_G2", hunk_ids=["H3_789ghi"],
                        theme="Bar integration", category="feature"),
            CommitGroup(group_id="_G3", hunk_ids=["H4_jkl012"],
                        theme="Add tests", category="test"),
            CommitGroup(group_id="_G4", hunk_ids=["H5_mno345"],
                        theme="New module", category="feature"),
        ]

    @pytest.fixture
    def mock_ordered_groups(self):
        return [
            CommitGroup(group_id="C1", hunk_ids=["H1_abc123", "H2_def456"],
                        theme="Foo changes", category="feature"),
            CommitGroup(group_id="C2", hunk_ids=["H3_789ghi"],
                        theme="Bar integration", category="feature"),
            CommitGroup(group_id="C3", hunk_ids=["H4_jkl012"],
                        theme="Add tests", category="test"),
            CommitGroup(group_id="C4", hunk_ids=["H5_mno345"],
                        theme="New module", category="feature"),
        ]

    @pytest.fixture
    def mock_planned_commits(self):
        return [
            PlannedCommit(id="C1", title="Add foo functions", type="feat",
                          hunks=["H1_abc123", "H2_def456"]),
            PlannedCommit(id="C2", title="Integrate bar", type="feat",
                          hunks=["H3_789ghi"]),
            PlannedCommit(id="C3", title="Add tests", type="test",
                          hunks=["H4_jkl012"]),
            PlannedCommit(id="C4", title="New module", type="feat",
                          hunks=["H5_mno345"]),
        ]

    @patch("hunknote.compose.agent.orchestrator.run_phase6_messages")
    @patch("hunknote.compose.agent.orchestrator.run_phase5a_validate")
    @patch("hunknote.compose.agent.orchestrator.run_phase4_order")
    @patch("hunknote.compose.agent.orchestrator.run_phase3_cluster")
    @patch("hunknote.compose.agent.orchestrator.run_phase2_dependency_graph")
    @patch("hunknote.compose.agent.orchestrator.run_phase1_summarize")
    def test_happy_path(
        self, mock_p1, mock_p2, mock_p3, mock_p4, mock_p5a, mock_p6,
        inventory, all_file_diffs, temp_repo,
        mock_summaries, mock_groups, mock_ordered_groups, mock_planned_commits,
    ):
        """Full pipeline succeeds with no validation failures."""
        mock_p1.return_value = mock_summaries
        mock_p2.return_value = DependencyGraph()
        mock_p3.return_value = mock_groups
        mock_p4.return_value = mock_ordered_groups
        mock_p5a.return_value = (None, FrozenBaseline())
        mock_p6.return_value = mock_planned_commits

        llm_fn = MagicMock()
        config = OrchestratorConfig()
        orch = AgentOrchestrator(
            all_file_diffs, inventory, temp_repo, llm_fn, config,
        )
        plan = orch.run()

        assert isinstance(plan, ComposePlan)
        assert len(plan.commits) == 4
        assert mock_p1.call_count == 1
        assert mock_p2.call_count == 1
        assert mock_p3.call_count == 1
        assert mock_p4.call_count == 1
        assert mock_p5a.call_count == 1
        assert mock_p6.call_count == 1

    @patch("hunknote.compose.agent.orchestrator.run_phase6_messages")
    @patch("hunknote.compose.agent.orchestrator.run_phase4_order")
    @patch("hunknote.compose.agent.orchestrator.run_phase3_cluster")
    @patch("hunknote.compose.agent.orchestrator.run_phase5b_diagnose")
    @patch("hunknote.compose.agent.orchestrator.run_phase5a_validate")
    @patch("hunknote.compose.agent.orchestrator.run_phase2_dependency_graph")
    @patch("hunknote.compose.agent.orchestrator.run_phase1_summarize")
    def test_retry_on_validation_failure(
        self, mock_p1, mock_p2, mock_p5a, mock_p5b, mock_p3, mock_p4, mock_p6,
        inventory, all_file_diffs, temp_repo,
        mock_summaries, mock_groups, mock_ordered_groups, mock_planned_commits,
    ):
        """Pipeline retries on validation failure with recluster remediation."""
        mock_p1.return_value = mock_summaries
        mock_p2.return_value = DependencyGraph()
        mock_p3.return_value = mock_groups
        mock_p4.return_value = mock_ordered_groups
        mock_p6.return_value = mock_planned_commits

        failure = ValidationFailure(
            commit_index=1,
            commit_group=mock_ordered_groups[1],
            layer=ValidationLayer.IMPORT,
            error_output="ImportError: cannot import name 'hello'",
        )
        # First call fails, second succeeds
        mock_p5a.side_effect = [
            (failure, FrozenBaseline()),
            (None, FrozenBaseline()),
        ]
        mock_p5b.return_value = Remediation(
            action=RemediationAction.RECLUSTER,
            diagnosis="Need to merge hunks",
            modifications={"merge_hunks_into_same_commit": [["H1_abc123", "H3_789ghi"]]},
        )

        llm_fn = MagicMock()
        config = OrchestratorConfig()
        orch = AgentOrchestrator(
            all_file_diffs, inventory, temp_repo, llm_fn, config,
        )
        plan = orch.run()

        assert isinstance(plan, ComposePlan)
        assert mock_p5a.call_count == 2
        assert mock_p5b.call_count == 1
        # Recluster triggers re-run of phase 3 and 4
        assert mock_p3.call_count >= 2
        assert mock_p4.call_count >= 2

    @patch("hunknote.compose.agent.orchestrator.run_phase5a_validate")
    @patch("hunknote.compose.agent.orchestrator.run_phase4_order")
    @patch("hunknote.compose.agent.orchestrator.run_phase3_cluster")
    @patch("hunknote.compose.agent.orchestrator.run_phase2_dependency_graph")
    @patch("hunknote.compose.agent.orchestrator.run_phase1_summarize")
    def test_max_retries_exceeded(
        self, mock_p1, mock_p2, mock_p3, mock_p4, mock_p5a,
        inventory, all_file_diffs, temp_repo,
        mock_summaries, mock_groups, mock_ordered_groups,
    ):
        """Pipeline raises AgentPipelineError after max retries."""
        mock_p1.return_value = mock_summaries
        mock_p2.return_value = DependencyGraph()
        mock_p3.return_value = mock_groups
        mock_p4.return_value = mock_ordered_groups

        failure = ValidationFailure(
            commit_index=0,
            commit_group=mock_ordered_groups[0],
            layer=ValidationLayer.PATCH_APPLY,
            error_output="patch does not apply",
        )
        mock_p5a.return_value = (failure, FrozenBaseline())

        llm_fn = MagicMock()
        config = OrchestratorConfig(max_retries=0)
        orch = AgentOrchestrator(
            all_file_diffs, inventory, temp_repo, llm_fn, config,
        )

        with pytest.raises(AgentPipelineError, match="Validation failed"):
            orch.run()

    @patch("hunknote.compose.agent.orchestrator.run_phase6_messages")
    @patch("hunknote.compose.agent.orchestrator.run_phase5b_diagnose")
    @patch("hunknote.compose.agent.orchestrator.run_phase5a_validate")
    @patch("hunknote.compose.agent.orchestrator.run_phase4_order")
    @patch("hunknote.compose.agent.orchestrator.run_phase3_cluster")
    @patch("hunknote.compose.agent.orchestrator.run_phase2_dependency_graph")
    @patch("hunknote.compose.agent.orchestrator.run_phase1_summarize")
    def test_fail_remediation_raises(
        self, mock_p1, mock_p2, mock_p3, mock_p4, mock_p5a, mock_p5b, mock_p6,
        inventory, all_file_diffs, temp_repo,
        mock_summaries, mock_groups, mock_ordered_groups,
    ):
        """FAIL remediation raises AgentPipelineError immediately."""
        mock_p1.return_value = mock_summaries
        mock_p2.return_value = DependencyGraph()
        mock_p3.return_value = mock_groups
        mock_p4.return_value = mock_ordered_groups

        failure = ValidationFailure(
            commit_index=0,
            commit_group=mock_ordered_groups[0],
            layer=ValidationLayer.SYNTAX,
            error_output="SyntaxError: invalid syntax",
        )
        mock_p5a.return_value = (failure, FrozenBaseline())
        mock_p5b.return_value = Remediation(
            action=RemediationAction.FAIL,
            diagnosis="Cannot fix syntax error by regrouping",
        )

        llm_fn = MagicMock()
        config = OrchestratorConfig()
        orch = AgentOrchestrator(
            all_file_diffs, inventory, temp_repo, llm_fn, config,
        )

        with pytest.raises(AgentPipelineError, match="cannot be resolved"):
            orch.run()


class TestApplyRemediation:
    """Tests for the _apply_remediation internal method."""

    @pytest.fixture
    def orch(self, inventory, all_file_diffs, temp_repo):
        llm_fn = MagicMock()
        config = OrchestratorConfig()
        o = AgentOrchestrator(
            all_file_diffs, inventory, temp_repo, llm_fn, config,
        )
        o.summaries = {
            hid: HunkSummary(
                hunk_id=hid, file_path=h.file_path,
                intent=f"Change {h.file_path}", category="feature",
            )
            for hid, h in inventory.items()
        }
        o.dependency_graph = DependencyGraph()
        o.commit_groups = [
            CommitGroup(group_id="_G1", hunk_ids=["H1_abc123"],
                        theme="A", category="feature"),
            CommitGroup(group_id="_G2", hunk_ids=["H2_def456"],
                        theme="B", category="feature"),
        ]
        o.ordered_groups = [
            CommitGroup(group_id="C1", hunk_ids=["H1_abc123"],
                        theme="A", category="feature"),
            CommitGroup(group_id="C2", hunk_ids=["H2_def456"],
                        theme="B", category="feature"),
        ]
        return o

    @patch("hunknote.compose.agent.orchestrator.run_phase4_order")
    @patch("hunknote.compose.agent.orchestrator.run_phase3_cluster")
    def test_recluster_reruns_phases_3_and_4(self, mock_p3, mock_p4, orch):
        """RECLUSTER remediation triggers re-run of phases 3 and 4."""
        mock_p3.return_value = orch.commit_groups
        mock_p4.return_value = orch.ordered_groups

        remediation = Remediation(
            action=RemediationAction.RECLUSTER,
            diagnosis="Need to merge hunks",
            modifications={
                "merge_hunks_into_same_commit": [["H1_abc123", "H2_def456"]],
            },
        )
        orch._apply_remediation(remediation)

        assert mock_p3.call_count == 1
        assert mock_p4.call_count == 1
        # Bidirectional edges should have been added
        bidir_edges = [
            e for e in orch.dependency_graph.edges
            if e.from_hunk == "H1_abc123" and e.to_hunk == "H2_def456"
        ]
        assert len(bidir_edges) > 0

    @patch("hunknote.compose.agent.orchestrator.run_phase4_order")
    def test_reorder_only_reruns_phase_4(self, mock_p4, orch):
        """REORDER remediation only triggers phase 4 re-run."""
        mock_p4.return_value = orch.ordered_groups

        remediation = Remediation(
            action=RemediationAction.REORDER,
            diagnosis="Wrong order",
            modifications={},
        )
        orch._apply_remediation(remediation)
        assert mock_p4.call_count == 1

    @patch("hunknote.compose.agent.orchestrator.run_phase4_order")
    def test_split_commit(self, mock_p4, orch):
        """SPLIT_COMMIT creates new sub-groups and re-orders."""
        mock_p4.return_value = orch.ordered_groups

        remediation = Remediation(
            action=RemediationAction.SPLIT_COMMIT,
            diagnosis="Commit too large",
            modifications={
                "split_commit_index": 0,
                "split_into": [["H1_abc123"]],
            },
        )
        orch._apply_remediation(remediation)
        assert mock_p4.call_count == 1

    @patch("hunknote.compose.agent.orchestrator.run_phase4_order")
    @patch("hunknote.compose.agent.orchestrator.run_phase3_cluster")
    def test_unlock_and_recluster_clears_frozen(self, mock_p3, mock_p4, orch):
        """UNLOCK_AND_RECLUSTER clears frozen commits from the specified index."""
        mock_p3.return_value = orch.commit_groups
        mock_p4.return_value = orch.ordered_groups

        orch.frozen_baseline.commits = [
            FrozenCommit(index=0, message="C0", hunk_ids=["H1_abc123"]),
            FrozenCommit(index=1, message="C1", hunk_ids=["H2_def456"]),
        ]

        remediation = Remediation(
            action=RemediationAction.UNLOCK_AND_RECLUSTER,
            diagnosis="Need to unlock",
            modifications={},
            unlock_from_commit_index=1,
        )
        orch._apply_remediation(remediation)

        # Only the first frozen commit remains
        assert len(orch.frozen_baseline.commits) == 1
        assert orch.frozen_baseline.commits[0].index == 0


class TestGetMutableHunkIds:
    """Tests for _get_mutable_hunk_ids."""

    def test_all_mutable_when_no_frozen(self, inventory, all_file_diffs, temp_repo):
        llm_fn = MagicMock()
        orch = AgentOrchestrator(
            all_file_diffs, inventory, temp_repo, llm_fn, OrchestratorConfig(),
        )
        mutable = orch._get_mutable_hunk_ids()
        assert set(mutable) == set(inventory.keys())

    def test_frozen_hunks_excluded(self, inventory, all_file_diffs, temp_repo):
        llm_fn = MagicMock()
        orch = AgentOrchestrator(
            all_file_diffs, inventory, temp_repo, llm_fn, OrchestratorConfig(),
        )
        orch.frozen_baseline.commits.append(
            FrozenCommit(index=0, message="C0", hunk_ids=["H1_abc123", "H2_def456"]),
        )
        mutable = orch._get_mutable_hunk_ids()
        assert "H1_abc123" not in mutable
        assert "H2_def456" not in mutable
        assert "H3_789ghi" in mutable
