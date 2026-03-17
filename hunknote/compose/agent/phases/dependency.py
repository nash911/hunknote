"""Phase 2: Dependency Graph Construction (ReAct Agent).

Uses a ReAct agent with tools to investigate relationships between hunks
and build a typed dependency graph.
"""

import logging
from pathlib import Path
from typing import Callable

from hunknote.compose.agent.gates import validate_dependency_output
from hunknote.compose.agent.models import (
    DependencyEdge,
    DependencyGraph,
    EdgeType,
    HunkSummary,
)
from hunknote.compose.agent.react import ReActConfig, run_react_loop
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.models import FileDiff, HunkRef
from hunknote.llm.base import RawLLMResult

logger = logging.getLogger(__name__)

_DEPENDENCY_SYSTEM_PROMPT = """You are an expert code analyst investigating dependencies between code changes (hunks).

Your task: Determine which hunks depend on which other hunks. A dependency means
that committing hunk A without hunk B would leave the codebase in a broken state.

There are two types of dependencies:
- DIRECTIONAL (A → B): A needs B to be committed first. B is valid without A.
  Example: A calls a function that B defines.
- BIDIRECTIONAL (A ↔ B): A and B must be in the SAME commit.
  Example: A changes a function's behavior, B updates the test for that behavior.
  If either is committed alone, the test fails.

FILE OPERATIONS (renames and deletions):
Some entries are file-level operations (R_* or D_*) with no content hunks.
These are critical for correctness:

- A RENAME entry (e.g. R_1_abc123) means a file was renamed via git mv.
  If a regular hunk updates import statements to reference the NEW file path,
  that hunk DEPENDS on the rename (directional: hunk → rename).
  If a hunk modifies code in the renamed file using the OLD path references,
  it may also depend on the rename.

- A DELETE entry (e.g. D_1_abc123) means a file was deleted via git rm.
  If a regular hunk removes imports or references to the deleted file, the
  delete and that hunk should be BIDIRECTIONAL (same commit).

Use the list_file_operations tool to see full details of renames and deletions.
Use ripgrep to search for import statements or references to renamed/deleted paths.

You have access to tools to investigate the codebase. Use them to:
1. Trace symbol references (who defines X? who calls X?)
2. Check if a behavior change has corresponding test updates
3. Find string-level dependencies (config keys, API paths, env vars)
4. Verify import chains
5. Check whether renames/deletions have corresponding import updates

Be thorough but efficient. Focus on hunks that modify or reference shared symbols.
Trivial changes (comments, formatting) rarely have dependencies.

Note: Hunks from new files are already pre-linked (they must stay together).
You do not need to investigate intra-file dependencies for new files."""

_DEPENDENCY_OUTPUT_SCHEMA = """
When you have enough information, produce your final Output as JSON:
{
  "edges": [
    {
      "from": "H3_abc123",
      "to": "H7_def456",
      "type": "directional",
      "reason": "H3 calls calculate_backoff() which H7 defines"
    },
    {
      "from": "H5_111aaa",
      "to": "H12_222bbb",
      "type": "bidirectional",
      "reason": "H5 changes parse_config behavior; H12 updates test to match"
    }
  ],
  "warnings": [
    "app.py:87 catches KeyError from parse_config — dead code after H5 but no hunk addresses it"
  ]
}

The "edges" list may be empty if no dependencies are found.
Use "directional" when one hunk must come before another.
Use "bidirectional" when two hunks must be in the SAME commit."""


def run_phase2_dependency_graph(
    inventory: dict[str, HunkRef],
    summaries: dict[str, HunkSummary],
    file_diffs: list[FileDiff],
    repo_root: Path,
    llm_call_fn: Callable[[str, str], RawLLMResult],
    trace: AgentTrace,
) -> DependencyGraph:
    """Build a typed dependency graph between hunks.

    Pre-processing:
    1. Auto-add bidirectional edges between all hunks of the same new file.

    Then runs a ReAct agent to investigate cross-file and cross-hunk dependencies.

    Returns:
        DependencyGraph with directional and bidirectional edges.
    """
    graph = DependencyGraph()

    # Auto-link new file hunks
    for file_diff in file_diffs:
        if file_diff.is_new_file and len(file_diff.hunks) > 1:
            hunk_ids = [h.id for h in file_diff.hunks]
            graph.add_bidirectional(hunk_ids, reason="All hunks belong to new file")

    # Build initial context for the ReAct agent
    initial_context = _build_initial_context(inventory, summaries, graph)

    # Run ReAct loop
    config = ReActConfig(
        max_iterations=15,
        max_tool_calls=15,
        system_prompt=_DEPENDENCY_SYSTEM_PROMPT,
        output_schema_description=_DEPENDENCY_OUTPUT_SCHEMA,
    )

    react_result = run_react_loop(
        config=config,
        initial_context=initial_context,
        llm_call_fn=llm_call_fn,
        repo_root=repo_root,
        inventory=inventory,
        trace=trace,
        phase_name="phase2",
        hunk_summaries=summaries,
    )

    # Parse agent's edges and merge with pre-added edges
    agent_edges = react_result.output.get("edges", [])
    agent_warnings = react_result.output.get("warnings", [])

    # Validate edges
    inventory_ids = set(inventory.keys())
    valid, violations = validate_dependency_output(agent_edges, inventory_ids)

    if not valid:
        trace.gate_violation("phase2", [
            {"type": v.violation_type, "hunk_id": v.hunk_id, "detail": v.detail}
            for v in violations
        ])
        # Strip invalid edges
        invalid_ids = {v.hunk_id for v in violations}
        agent_edges = [
            e for e in agent_edges
            if e.get("from") not in invalid_ids and e.get("to") not in invalid_ids
            and e.get("from") != e.get("to")
        ]
    else:
        trace.gate_pass("phase2", "All dependency edges valid")

    # Add valid edges to graph
    for edge_data in agent_edges:
        from_id = edge_data.get("from", "")
        to_id = edge_data.get("to", "")
        edge_type_str = edge_data.get("type", "directional")
        reason = edge_data.get("reason", "")

        if from_id in inventory_ids and to_id in inventory_ids and from_id != to_id:
            try:
                edge_type = EdgeType(edge_type_str)
            except ValueError:
                edge_type = EdgeType.DIRECTIONAL

            graph.add_edge(DependencyEdge(
                from_hunk=from_id,
                to_hunk=to_id,
                edge_type=edge_type,
                reason=reason,
            ))

    graph.warnings.extend(agent_warnings)

    return graph


def _build_initial_context(
    inventory: dict[str, HunkRef],
    summaries: dict[str, HunkSummary],
    graph: DependencyGraph,
) -> str:
    """Build the initial context message for the ReAct agent."""
    from hunknote.compose.inventory import is_file_op_id, RENAME_PREFIX, DELETE_PREFIX

    # Separate regular hunks from file operations
    regular_ids = sorted(
        [hid for hid in inventory if not is_file_op_id(hid)],
        key=lambda x: int(x.split("_")[0][1:]),
    )
    file_op_ids = sorted(
        [hid for hid in inventory if is_file_op_id(hid)],
    )

    lines = ["Here are all the hunks to analyze:", ""]

    for hid in regular_ids:
        hunk = inventory[hid]
        summary = summaries.get(hid)

        line = f"  {hid}: {hunk.file_path}  {hunk.header.strip()}"
        if summary:
            line += f"\n    Intent: {summary.intent}"
            line += f"\n    Category: {summary.category}"
            if summary.symbols_modified:
                line += f"\n    Symbols modified: {', '.join(summary.symbols_modified)}"
            if summary.symbols_referenced:
                line += f"\n    Symbols referenced: {', '.join(summary.symbols_referenced)}"
            if summary.is_new_file:
                line += "\n    (new file — auto-linked with other hunks in same file)"
        lines.append(line)
        lines.append("")

    # File operations section
    if file_op_ids:
        lines.append("FILE OPERATIONS (must be assigned to a commit):")
        lines.append("")
        for hid in file_op_ids:
            hunk = inventory[hid]
            if hid.startswith(RENAME_PREFIX):
                lines.append(
                    f"  {hid}: RENAME — {hunk.header}"
                )
                lines.append(
                    f"    Any hunk that updates imports to use the new path "
                    f"depends on this rename."
                )
            elif hid.startswith(DELETE_PREFIX):
                lines.append(
                    f"  {hid}: DELETE — {hunk.header}"
                )
                lines.append(
                    f"    Any hunk that removes references to this file "
                    f"should be in the same commit."
                )
            lines.append("")

    # Show pre-existing edges
    if graph.edges:
        lines.append("Pre-existing edges (auto-detected):")
        for edge in graph.edges:
            lines.append(
                f"  {edge.from_hunk} ↔ {edge.to_hunk}: {edge.reason}"
            )
        lines.append("")

    lines.append(
        "Investigate the dependencies between these hunks. Start by identifying "
        "hunks that share symbols or touch related functionality, then use tools "
        "to verify."
    )
    if file_op_ids:
        lines.append(
            "Pay special attention to FILE OPERATIONS — use ripgrep to find "
            "which hunks update imports referencing the renamed/deleted paths, "
            "and add appropriate dependency edges."
        )

    return "\n".join(lines)
