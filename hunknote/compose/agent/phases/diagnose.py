"""Phase 5b: Failure Diagnosis (ReAct Agent).

Diagnoses validation failures and emits structured remediation actions.
"""

import json
import logging
from pathlib import Path
from typing import Callable

from hunknote.compose.agent.gates import validate_remediation_output
from hunknote.compose.agent.models import (
    CommitGroup,
    DependencyGraph,
    FrozenBaseline,
    HunkSummary,
    Remediation,
    RemediationAction,
    ValidationFailure,
)
from hunknote.compose.agent.react import ReActConfig, run_react_loop
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.inventory import hunk_sort_key
from hunknote.compose.models import HunkRef
from hunknote.llm.base import RawLLMResult

logger = logging.getLogger(__name__)

_DIAGNOSE_SYSTEM_PROMPT = """You are diagnosing a commit sequence failure. A series of commits was being
validated and one of them failed. Your job is to investigate WHY it failed
and propose a fix.

You have access to tools to investigate the codebase and the hunks.

Your remediation MUST only rearrange hunks in the mutable set.
Use "unlock_and_recluster" only if the failure is impossible to fix otherwise.
Prefer "recluster" (add bidirectional edges to force hunks together) for most issues."""

_DIAGNOSE_OUTPUT_SCHEMA = """
When you have enough information, produce your final Output as JSON:
{
  "action": "recluster" | "reorder" | "split_commit" | "unlock_and_recluster" | "fail",
  "diagnosis": "<explanation of what went wrong>",
  "modifications": {
    "merge_hunks_into_same_commit": [["H1_abc123", "H5_def456"]],
    "add_dependency_edges": [{"from": "H1_abc123", "to": "H5_def456", "type": "bidirectional", "reason": "..."}]
  },
  "revalidate_from_commit_index": <int>,
  "unlock_from_commit_index": <int or null>
}

Actions:
- "recluster": Re-run clustering with updated dependency edges. Use when hunks need to be in the same commit.
- "reorder": Re-run ordering only. Use when the commit order is wrong but grouping is fine.
- "split_commit": Split a commit into smaller pieces. Provide "split_commit_index" and "split_into" in modifications.
- "unlock_and_recluster": Unfreeze validated commits from a certain index and recluster. Last resort.
- "fail": The failure cannot be resolved by regrouping. Provide a clear diagnosis."""


def run_phase5b_diagnose(
    failure: ValidationFailure,
    ordered_groups: list[CommitGroup],
    graph: DependencyGraph,
    summaries: dict[str, HunkSummary],
    frozen_baseline: FrozenBaseline,
    mutable_hunk_ids: list[str],
    inventory: dict[str, HunkRef],
    repo_root: Path,
    llm_call_fn: Callable[[str, str], RawLLMResult],
    trace: AgentTrace,
) -> Remediation:
    """Diagnose a validation failure and produce a remediation action."""
    mutable_set = set(mutable_hunk_ids)
    frozen_set = frozen_baseline.all_hunk_ids
    inventory_ids = set(inventory.keys())

    # Build initial context
    initial_context = _build_diagnosis_context(
        failure, ordered_groups, summaries, frozen_baseline, mutable_hunk_ids,
    )

    # Build system prompt with frozen/mutable context
    system_additions = []
    if frozen_baseline.commits:
        system_additions.append("\nFROZEN COMMITS (read-only, do not modify):")
        for fc in frozen_baseline.commits:
            system_additions.append(
                f"  C{fc.index + 1}: {fc.message} (hunks: {', '.join(fc.hunk_ids[:5])})"
            )

    system_additions.append("\nMUTABLE HUNKS (these are the hunks you can rearrange):")
    for hid in sorted(mutable_hunk_ids, key=hunk_sort_key)[:30]:
        s = summaries.get(hid)
        if s:
            system_additions.append(f"  {hid}: {s.file_path} — {s.intent[:60]}")
        else:
            system_additions.append(f"  {hid}")

    full_system = _DIAGNOSE_SYSTEM_PROMPT + "\n".join(system_additions)

    config = ReActConfig(
        max_iterations=12,
        max_tool_calls=12,
        system_prompt=full_system,
        output_schema_description=_DIAGNOSE_OUTPUT_SCHEMA,
    )

    react_result = run_react_loop(
        config=config,
        initial_context=initial_context,
        llm_call_fn=llm_call_fn,
        repo_root=repo_root,
        inventory=inventory,
        trace=trace,
        phase_name="phase5b",
        hunk_summaries=summaries,
    )

    # Parse remediation from output
    output = react_result.output
    if not output:
        logger.warning("Phase 5b: no output from diagnosis agent")
        return Remediation(
            action=RemediationAction.FAIL,
            diagnosis="Diagnosis agent produced no output",
        )

    # Validate remediation output
    valid, violations = validate_remediation_output(
        output, mutable_set, frozen_set, inventory_ids,
    )

    if not valid:
        trace.gate_violation("phase5b", [
            {"type": v.violation_type, "hunk_id": v.hunk_id, "detail": v.detail}
            for v in violations
        ])
        # Strip invalid modifications but keep the action and diagnosis
        output["modifications"] = _strip_invalid_modifications(
            output.get("modifications", {}), inventory_ids, mutable_set, frozen_set,
            output.get("action", ""),
        )
    else:
        trace.gate_pass("phase5b", "Remediation output valid")

    return _parse_remediation(output)


def _build_diagnosis_context(
    failure: ValidationFailure,
    ordered_groups: list[CommitGroup],
    summaries: dict[str, HunkSummary],
    frozen_baseline: FrozenBaseline,
    mutable_hunk_ids: list[str],
) -> str:
    """Build the initial context message for the diagnosis agent."""
    lines = [
        "FAILURE DETAILS:",
        f"- Failed at commit index: {failure.commit_index}",
        f"- Commit: {failure.commit_group.group_id} — {failure.commit_group.theme}",
        f"  Hunks: {', '.join(failure.commit_group.hunk_ids)}",
        f"- Validation layer: {failure.layer.value}",
    ]

    if failure.file_path:
        lines.append(f"- File: {failure.file_path}")

    lines.append(f"- Error output:")
    lines.append(failure.error_output[:2000])
    lines.append("")

    lines.append("ALL COMMITS IN CURRENT PLAN:")
    for i, group in enumerate(ordered_groups):
        marker = " <<<FAILED" if i == failure.commit_index else ""
        hunk_list = ", ".join(group.hunk_ids[:8])
        if len(group.hunk_ids) > 8:
            hunk_list += f" (+{len(group.hunk_ids) - 8} more)"
        lines.append(f"  {group.group_id}: {group.theme} [{hunk_list}]{marker}")

    lines.append("")
    lines.append("Investigate the failure and propose a fix.")

    return "\n".join(lines)


def _parse_remediation(output: dict) -> Remediation:
    """Parse the diagnosis output into a Remediation dataclass."""
    try:
        action = RemediationAction(output.get("action", "fail"))
    except ValueError:
        action = RemediationAction.FAIL

    return Remediation(
        action=action,
        diagnosis=output.get("diagnosis", ""),
        modifications=output.get("modifications", {}),
        revalidate_from_commit_index=output.get("revalidate_from_commit_index", 0),
        unlock_from_commit_index=output.get("unlock_from_commit_index"),
    )


def _strip_invalid_modifications(
    modifications: dict,
    inventory_ids: set[str],
    mutable_ids: set[str],
    frozen_ids: set[str],
    action: str,
) -> dict:
    """Remove invalid hunk references from modifications."""
    cleaned = {}

    merge_groups = modifications.get("merge_hunks_into_same_commit", [])
    if merge_groups:
        valid_groups = []
        for group in merge_groups:
            valid_group = [
                hid for hid in group
                if hid in inventory_ids and (
                    hid in mutable_ids or
                    (action == "unlock_and_recluster" and hid in frozen_ids)
                )
            ]
            if len(valid_group) >= 2:
                valid_groups.append(valid_group)
        if valid_groups:
            cleaned["merge_hunks_into_same_commit"] = valid_groups

    edges = modifications.get("add_dependency_edges", [])
    if edges:
        valid_edges = [
            e for e in edges
            if e.get("from", "") in inventory_ids
            and e.get("to", "") in inventory_ids
            and e.get("from") != e.get("to")
        ]
        if valid_edges:
            cleaned["add_dependency_edges"] = valid_edges

    # Pass through other keys
    for key in modifications:
        if key not in ("merge_hunks_into_same_commit", "add_dependency_edges"):
            cleaned[key] = modifications[key]

    return cleaned
