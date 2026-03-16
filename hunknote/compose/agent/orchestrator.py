"""Agent Orchestrator — deterministic state machine.

Runs the full 6-phase pipeline: Summarize → Dependency → Cluster → Order →
Validate (with retry via Diagnose) → Messages. Returns a ComposePlan.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from hunknote.compose.agent.models import (
    CommitGroup,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
    FrozenBaseline,
    HunkSummary,
    Remediation,
    RemediationAction,
    ValidationFailure,
)
from hunknote.compose.agent.phases.cluster import run_phase3_cluster
from hunknote.compose.agent.phases.dependency import run_phase2_dependency_graph
from hunknote.compose.agent.phases.diagnose import run_phase5b_diagnose
from hunknote.compose.agent.phases.messages import run_phase6_messages
from hunknote.compose.agent.phases.order import run_phase4_order
from hunknote.compose.agent.phases.summarize import run_phase1_summarize
from hunknote.compose.agent.phases.validate import run_phase5a_validate
from hunknote.compose.agent.tracing import AgentTrace, TraceEvent, TraceEventType
from hunknote.compose.models import ComposePlan, FileDiff, HunkRef, PlannedCommit
from hunknote.llm.base import RawLLMResult

logger = logging.getLogger(__name__)


class AgentPipelineError(Exception):
    """Raised when the agent pipeline fails unrecoverably."""

    def __init__(self, message: str, diagnosis: str = ""):
        super().__init__(message)
        self.diagnosis = diagnosis


@dataclass
class OrchestratorConfig:
    max_retries: int = 3
    max_commits: int = 6
    run_tests: bool = False
    style_config: object = None
    effective_profile: object = None
    python_bin: Optional[str] = None  # Path to Python binary for validation (e.g. venv python)


class AgentOrchestrator:
    """Main orchestrator for the Compose Agent pipeline."""

    def __init__(
        self,
        file_diffs: list[FileDiff],
        inventory: dict[str, HunkRef],
        repo_root: Path,
        llm_call_fn: Callable[[str, str], RawLLMResult],
        config: OrchestratorConfig,
        trace: Optional[AgentTrace] = None,
    ):
        self.file_diffs = file_diffs
        self.inventory = inventory
        self.repo_root = repo_root
        self.llm_call_fn = llm_call_fn
        self.config = config
        self.trace = trace or AgentTrace()

        # Pipeline state
        self.summaries: dict[str, HunkSummary] = {}
        self.dependency_graph = DependencyGraph()
        self.commit_groups: list[CommitGroup] = []
        self.ordered_groups: list[CommitGroup] = []
        self.frozen_baseline = FrozenBaseline()
        self.planned_commits: list[PlannedCommit] = []
        self.retry_count = 0
        self.revalidate_from = 0

    def run(self) -> ComposePlan:
        """Execute the full agent pipeline and return a ComposePlan.

        Returns:
            ComposePlan compatible with the existing compose rendering/execution.

        Raises:
            AgentPipelineError: If the pipeline fails after max retries.
        """
        # Phase 1: Summarize
        self.trace.phase_start("phase1", f"Summarizing {len(self.inventory)} hunks")
        self.summaries = run_phase1_summarize(
            self.inventory, self.file_diffs, self.repo_root,
            self.llm_call_fn, self.trace,
        )
        self.trace.phase_end("phase1")
        self.trace.save_to_file(self.repo_root)

        # Phase 2: Dependency Graph
        self.trace.phase_start("phase2", "Building dependency graph")
        self.dependency_graph = run_phase2_dependency_graph(
            self.inventory, self.summaries, self.file_diffs,
            self.repo_root, self.llm_call_fn, self.trace,
        )
        self.trace.phase_end("phase2")
        self.trace.save_to_file(self.repo_root)

        # Phase 3: Clustering
        all_hunk_ids = sorted(self.inventory.keys())
        self.trace.phase_start("phase3", "Clustering hunks into commits")
        self.commit_groups = run_phase3_cluster(
            self.summaries, self.dependency_graph,
            mutable_hunk_ids=all_hunk_ids,
            frozen_baseline=self.frozen_baseline,
            max_commits=self.config.max_commits,
            llm_call_fn=self.llm_call_fn,
            trace=self.trace,
        )
        self.trace.phase_end("phase3")
        self.trace.save_to_file(self.repo_root)

        # Phase 4: Ordering
        self.trace.phase_start("phase4", "Ordering commits")
        self.ordered_groups = run_phase4_order(
            self.commit_groups, self.dependency_graph,
            self.frozen_baseline, self.llm_call_fn, self.trace,
        )
        self.trace.phase_end("phase4")
        self.trace.save_to_file(self.repo_root)

        # Phase 5: Validate + retry loop
        while self.retry_count <= self.config.max_retries:
            self.trace.phase_start(
                "phase5",
                f"Validating commit sequence (attempt {self.retry_count + 1})",
            )
            failure, self.frozen_baseline = run_phase5a_validate(
                self.ordered_groups, self.inventory, self.file_diffs,
                self.repo_root, self.trace,
                summaries=self.summaries,
                start_from_index=self.revalidate_from,
                run_tests=self.config.run_tests,
                python_bin=self.config.python_bin,
            )
            self.trace.phase_end("phase5")
            self.trace.save_to_file(self.repo_root)

            if failure is None:
                break  # All commits validated

            if self.retry_count >= self.config.max_retries:
                raise AgentPipelineError(
                    f"Validation failed after {self.config.max_retries} retries",
                    diagnosis=(
                        f"Commit {failure.commit_index} failed at "
                        f"{failure.layer.value}: {failure.error_output[:500]}"
                    ),
                )

            # Phase 5b: Diagnose and remediate
            self.trace.phase_start(
                "phase5b",
                f"Diagnosing failure at commit {failure.commit_index}",
            )

            mutable_ids = self._get_mutable_hunk_ids()
            remediation = run_phase5b_diagnose(
                failure, self.ordered_groups, self.dependency_graph,
                self.summaries, self.frozen_baseline, mutable_ids,
                self.inventory, self.repo_root, self.llm_call_fn, self.trace,
            )
            self.trace.phase_end("phase5b")
            self.trace.save_to_file(self.repo_root)

            if remediation.action == RemediationAction.FAIL:
                raise AgentPipelineError(
                    "Agent determined the failure cannot be resolved by regrouping",
                    diagnosis=remediation.diagnosis,
                )

            self._apply_remediation(remediation)
            self.retry_count += 1

        # Phase 6: Generate messages
        self.trace.phase_start("phase6", "Generating commit messages")
        self.planned_commits = run_phase6_messages(
            self.ordered_groups, self.inventory, self.summaries,
            self.config.style_config, self.config.effective_profile,
            self.llm_call_fn, self.trace,
        )
        self.trace.phase_end("phase6")
        self.trace.save_to_file(self.repo_root)

        # Convert to ComposePlan
        return ComposePlan(
            version="1",
            warnings=list(self.dependency_graph.warnings),
            commits=self.planned_commits,
        )

    def _get_mutable_hunk_ids(self) -> list[str]:
        """Get hunk IDs not consumed by frozen commits."""
        frozen = self.frozen_baseline.all_hunk_ids
        return [hid for hid in self.inventory.keys() if hid not in frozen]

    def _apply_remediation(self, remediation: Remediation) -> None:
        """Apply a remediation action: update graph, recluster, reorder."""
        self.trace.emit(TraceEvent(
            event_type=TraceEventType.REMEDIATION,
            phase="orchestrator",
            message=f"Applying {remediation.action.value}: {remediation.diagnosis}",
            data={
                "action": remediation.action.value,
                "modifications": remediation.modifications,
            },
        ))

        if remediation.action == RemediationAction.UNLOCK_AND_RECLUSTER:
            # Unfreeze commits from the specified index onward
            unlock_from = remediation.unlock_from_commit_index or 0
            self.frozen_baseline.commits = self.frozen_baseline.commits[:unlock_from]
            self.revalidate_from = unlock_from

        # Apply graph modifications
        mods = remediation.modifications
        for edge_data in mods.get("add_dependency_edges", []):
            try:
                edge_type = EdgeType(edge_data.get("type", "bidirectional"))
            except ValueError:
                edge_type = EdgeType.BIDIRECTIONAL
            self.dependency_graph.add_edge(DependencyEdge(
                from_hunk=edge_data["from"],
                to_hunk=edge_data["to"],
                edge_type=edge_type,
                reason=edge_data.get("reason", ""),
            ))
        for group in mods.get("merge_hunks_into_same_commit", []):
            self.dependency_graph.add_bidirectional(
                group, reason="forced by remediation",
            )

        # Re-cluster and re-order based on action type
        if remediation.action in (
            RemediationAction.RECLUSTER,
            RemediationAction.UNLOCK_AND_RECLUSTER,
        ):
            mutable_ids = self._get_mutable_hunk_ids()
            self.commit_groups = run_phase3_cluster(
                self.summaries, self.dependency_graph,
                mutable_hunk_ids=mutable_ids,
                frozen_baseline=self.frozen_baseline,
                max_commits=self.config.max_commits,
                llm_call_fn=self.llm_call_fn,
                trace=self.trace,
            )
            self.ordered_groups = run_phase4_order(
                self.commit_groups, self.dependency_graph,
                self.frozen_baseline, self.llm_call_fn, self.trace,
            )
        elif remediation.action == RemediationAction.REORDER:
            self.ordered_groups = run_phase4_order(
                self.commit_groups, self.dependency_graph,
                self.frozen_baseline, self.llm_call_fn, self.trace,
            )
        elif remediation.action == RemediationAction.SPLIT_COMMIT:
            split_idx = mods.get("split_commit_index", 0)
            split_into = mods.get("split_into", [])
            if split_into and split_idx < len(self.commit_groups):
                original = self.commit_groups[split_idx]
                new_groups = []
                for j, hunk_list in enumerate(split_into):
                    new_groups.append(CommitGroup(
                        group_id=f"{original.group_id}_{j}",
                        hunk_ids=hunk_list,
                        theme=f"Split {j + 1} of {original.theme}",
                        category=original.category,
                    ))
                self.commit_groups = (
                    self.commit_groups[:split_idx]
                    + new_groups
                    + self.commit_groups[split_idx + 1:]
                )
            self.ordered_groups = run_phase4_order(
                self.commit_groups, self.dependency_graph,
                self.frozen_baseline, self.llm_call_fn, self.trace,
            )

        self.revalidate_from = remediation.revalidate_from_commit_index

        # Prepend frozen baseline's ordered groups for full sequence
        frozen_groups = []
        for fc in self.frozen_baseline.commits:
            frozen_groups.append(CommitGroup(
                group_id=f"frozen_{fc.index}",
                hunk_ids=fc.hunk_ids,
                theme=fc.message,
                category="",
            ))
        self.ordered_groups = frozen_groups + self.ordered_groups
