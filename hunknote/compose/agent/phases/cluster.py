"""Phase 3: Commit Clustering.

Single LLM call (not ReAct). Uses summaries + dependency graph to group
hunks into candidate commit groups.
"""

import json
import logging
import re
import time
from typing import Callable

from hunknote.compose.agent.gates import (
    GateViolation,
    build_correction_prompt,
    validate_clustering_output,
)
from hunknote.compose.agent.models import (
    CommitGroup,
    DependencyGraph,
    EdgeType,
    FrozenBaseline,
    HunkSummary,
)
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.inventory import hunk_sort_key
from hunknote.llm.base import RawLLMResult

logger = logging.getLogger(__name__)

_CLUSTER_SYSTEM_PROMPT = """You are an expert software engineer grouping code changes into atomic commits.

Your task: Given hunk summaries and a dependency graph, cluster the hunks into
commit groups. Each group should be ONE cohesive logical change.

HARD CONSTRAINTS:
- Bidirectional edges (↔) mean those hunks MUST be in the SAME group.
- Directional edges (→) mean the source depends on the target — they can be
  in different groups, but ordering will be enforced later.
- All hunks in a new file MUST be in the same group.
- Every mutable hunk MUST be assigned to exactly one group.
- Do NOT reference any frozen hunk IDs.

GROUPING GUIDELINES:
- A feature implementation + its tests = one group.
- A refactor + its callers = one group (if callers change).
- Independent changes to different subsystems = separate groups.
- When in doubt, keep hunks together — a larger cohesive commit is better
  than broken small ones.

Output ONLY valid JSON. No markdown fences. No commentary."""


def run_phase3_cluster(
    summaries: dict[str, HunkSummary],
    graph: DependencyGraph,
    mutable_hunk_ids: list[str],
    frozen_baseline: FrozenBaseline,
    max_commits: int,
    llm_call_fn: Callable[[str, str], RawLLMResult],
    trace: AgentTrace,
    max_attempts: int = 3,
) -> list[CommitGroup]:
    """Group hunks into candidate commits.

    Args:
        summaries: Phase 1 hunk summaries.
        graph: Phase 2 dependency graph.
        mutable_hunk_ids: Hunk IDs that can be clustered.
        frozen_baseline: Read-only context of validated commits.
        max_commits: Maximum number of commits allowed.
        llm_call_fn: LLM call function.
        trace: Trace instance.
        max_attempts: Max reprompt attempts if gate fails.

    Returns:
        List of CommitGroup objects with temporary _G{n} IDs.
    """
    mutable_set = set(mutable_hunk_ids)
    frozen_set = frozen_baseline.all_hunk_ids

    user_prompt = _build_cluster_prompt(
        summaries, graph, mutable_hunk_ids, frozen_baseline, max_commits,
    )

    for attempt in range(max_attempts):
        trace.llm_call("phase3", _CLUSTER_SYSTEM_PROMPT, user_prompt)
        start_time = time.time()

        try:
            result = llm_call_fn(_CLUSTER_SYSTEM_PROMPT, user_prompt)
        except Exception as e:
            logger.warning("Phase 3 LLM call failed: %s", e)
            trace.warning("phase3", f"LLM call failed: {e}")
            break

        duration_ms = (time.time() - start_time) * 1000
        trace.llm_response(
            "phase3", result.raw_response, result.model,
            {"input": result.input_tokens, "output": result.output_tokens,
             "thinking": result.thinking_tokens},
            duration_ms,
        )

        # Parse response
        groups_data = _parse_clustering_response(result.raw_response)
        if groups_data is None:
            trace.warning("phase3", "Failed to parse clustering response")
            user_prompt += "\n\n[Your previous response was not valid JSON. Output ONLY the JSON object.]"
            continue

        # Validate via gate
        valid, violations = validate_clustering_output(
            groups_data, mutable_set, frozen_set, max_commits,
        )

        if valid:
            trace.gate_pass("phase3", f"Clustering valid: {len(groups_data)} groups")
            return _build_commit_groups(groups_data)

        # Gate failed — build correction prompt
        trace.gate_violation("phase3", [
            {"type": v.violation_type, "hunk_id": v.hunk_id, "detail": v.detail}
            for v in violations
        ])

        correction = build_correction_prompt(violations, mutable_set)
        user_prompt = user_prompt + "\n\n" + correction

    # All attempts failed — build a single group with all mutable hunks
    logger.warning("Phase 3: all attempts failed, creating single group")
    trace.warning("phase3", "All clustering attempts failed, using single group")
    return [CommitGroup(
        group_id="_G1",
        hunk_ids=list(mutable_hunk_ids),
        theme="All changes",
        category="chore",
    )]


def _build_cluster_prompt(
    summaries: dict[str, HunkSummary],
    graph: DependencyGraph,
    mutable_hunk_ids: list[str],
    frozen_baseline: FrozenBaseline,
    max_commits: int,
) -> str:
    """Build the clustering prompt."""
    lines: list[str] = []

    # Frozen baseline context
    if frozen_baseline.commits:
        lines.append("[FROZEN COMMITS — read-only context, DO NOT modify]")
        for fc in frozen_baseline.commits:
            lines.append(f"  C{fc.index + 1}: {fc.message} (hunks: {', '.join(fc.hunk_ids[:5])})")
        lines.append("")

    # Mutable hunks with summaries
    lines.append("[MUTABLE HUNKS — assign each to exactly one group]")
    for hid in sorted(mutable_hunk_ids, key=hunk_sort_key):
        summary = summaries.get(hid)
        if summary:
            new_flag = " [NEW FILE]" if summary.is_new_file else ""
            lines.append(f"  {hid}: {summary.file_path}{new_flag}")
            lines.append(f"    Intent: {summary.intent}")
            lines.append(f"    Category: {summary.category}")
            if summary.symbols_modified:
                lines.append(f"    Symbols modified: {', '.join(summary.symbols_modified[:10])}")
        else:
            lines.append(f"  {hid}: (no summary)")
    lines.append("")

    # Dependency edges (mutable hunks only)
    mutable_set = set(mutable_hunk_ids)
    relevant_edges = [
        e for e in graph.edges
        if e.from_hunk in mutable_set and e.to_hunk in mutable_set
    ]
    if relevant_edges:
        lines.append("[DEPENDENCY GRAPH]")
        for edge in relevant_edges:
            arrow = "↔" if edge.edge_type == EdgeType.BIDIRECTIONAL else "→"
            lines.append(f"  {edge.from_hunk} {arrow} {edge.to_hunk}: {edge.reason}")
        lines.append("")

    # Bidirectional groups (must be in same commit)
    bidir_groups = graph.get_bidirectional_groups()
    relevant_bidir = [g for g in bidir_groups if g & mutable_set]
    if relevant_bidir:
        lines.append("[MUST-COLOCATE GROUPS — these hunks MUST be in the same group]")
        for i, group in enumerate(relevant_bidir, 1):
            group_ids = sorted(group & mutable_set)
            lines.append(f"  Group {i}: {', '.join(group_ids)}")
        lines.append("")

    lines.append(f"[CONSTRAINTS]")
    lines.append(f"Maximum groups: {max_commits}")
    lines.append("")

    lines.append("""[OUTPUT SCHEMA]
{
  "groups": [
    {
      "id": "_G1",
      "theme": "Add retry logic with exponential backoff",
      "category": "feature",
      "hunks": ["H3_abc123", "H7_def456", "H12_222bbb"]
    }
  ]
}""")

    return "\n".join(lines)


def _parse_clustering_response(response: str) -> list[dict] | None:
    """Parse the clustering response into a list of group dicts."""
    text = response.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        else:
            return None

    if isinstance(data, dict) and "groups" in data:
        return data["groups"]
    return None


def _build_commit_groups(groups_data: list[dict]) -> list[CommitGroup]:
    """Convert parsed group dicts to CommitGroup objects."""
    groups: list[CommitGroup] = []
    for i, gd in enumerate(groups_data):
        groups.append(CommitGroup(
            group_id=gd.get("id", f"_G{i + 1}"),
            hunk_ids=gd.get("hunks", []),
            theme=gd.get("theme", ""),
            category=gd.get("category", "chore"),
        ))
    return groups
