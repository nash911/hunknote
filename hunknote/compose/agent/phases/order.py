"""Phase 4: Commit Ordering.

Primarily deterministic. Uses Kahn's algorithm for topological sort,
with LLM tie-breaking when multiple groups have zero in-degree.
"""

import json
import logging
import time
from collections import defaultdict, deque
from typing import Callable, Optional

from hunknote.compose.agent.models import (
    CommitGroup,
    DependencyGraph,
    EdgeType,
    FrozenBaseline,
)
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.llm.base import RawLLMResult

logger = logging.getLogger(__name__)

_TIE_BREAK_SYSTEM_PROMPT = """You are ordering commit groups in a commit stack.
Rank the groups in the order they should be committed.

Preferred order: infrastructure/refactors first, then features, then bugfixes, then tests, then docs/config.

Output ONLY a JSON array of group IDs in order. No commentary. Example:
["_G3", "_G1", "_G2"]"""


def run_phase4_order(
    groups: list[CommitGroup],
    graph: DependencyGraph,
    frozen_baseline: FrozenBaseline,
    llm_call_fn: Callable[[str, str], RawLLMResult],
    trace: AgentTrace,
) -> list[CommitGroup]:
    """Order commit groups topologically with LLM tie-breaking.

    1. Lift hunk-level edges to group-level edges.
    2. Topological sort with Kahn's algorithm.
    3. When multiple groups have zero in-degree, ask LLM to pick order.
    4. Assign final sequential IDs: C1, C2, C3, ...

    Returns:
        Ordered list of CommitGroup objects with C{n} IDs.
    """
    if len(groups) <= 1:
        # Single group — just rename and return
        for i, g in enumerate(groups):
            g.group_id = f"C{i + 1}"
        return groups

    # Build group-level DAG
    group_deps = _build_group_dag(groups, graph)

    # Topological sort with LLM tie-breaking
    ordered = _topological_sort(groups, group_deps, llm_call_fn, trace)

    # Assign final C{n} IDs
    for i, group in enumerate(ordered):
        group.group_id = f"C{i + 1}"

    trace.state_change("phase4", f"Ordered {len(ordered)} groups: {[g.group_id for g in ordered]}")
    return ordered


def _build_group_dag(
    groups: list[CommitGroup],
    graph: DependencyGraph,
) -> dict[str, set[str]]:
    """Build group-level dependency DAG from hunk-level edges.

    Group A depends on group B if any hunk in A has a directional edge
    pointing to any hunk in B.
    """
    # Map hunk_id -> group_id
    hunk_to_group: dict[str, str] = {}
    for g in groups:
        for hid in g.hunk_ids:
            hunk_to_group[hid] = g.group_id

    # Build group-level edges (A depends on B means B must come first)
    deps: dict[str, set[str]] = {g.group_id: set() for g in groups}

    for edge in graph.edges:
        if edge.edge_type != EdgeType.DIRECTIONAL:
            continue
        from_group = hunk_to_group.get(edge.from_hunk)
        to_group = hunk_to_group.get(edge.to_hunk)
        if from_group and to_group and from_group != to_group:
            # from_hunk depends on to_hunk, so from_group depends on to_group
            deps[from_group].add(to_group)

    return deps


def _topological_sort(
    groups: list[CommitGroup],
    deps: dict[str, set[str]],
    llm_call_fn: Callable[[str, str], RawLLMResult],
    trace: AgentTrace,
) -> list[CommitGroup]:
    """Kahn's algorithm with LLM tie-breaking."""
    group_map = {g.group_id: g for g in groups}

    # Compute in-degrees
    in_degree: dict[str, int] = {gid: 0 for gid in group_map}
    for gid, dep_set in deps.items():
        for dep in dep_set:
            if dep in in_degree:
                # dep must come before gid, so gid has an incoming edge from dep
                pass
    # Recompute: for each group, count how many other groups depend on it coming first
    # Actually: in_degree[gid] = number of groups that gid depends on (that must come first)
    # No — Kahn's: in_degree counts incoming edges. If A depends on B, edge B→A, in_degree[A]++

    # Build adjacency list (B → A means B must come before A)
    adj: dict[str, list[str]] = {gid: [] for gid in group_map}
    in_degree = {gid: 0 for gid in group_map}

    for gid, dep_set in deps.items():
        for dep in dep_set:
            if dep in adj:
                adj[dep].append(gid)
                in_degree[gid] += 1

    # Kahn's algorithm
    queue: list[str] = [gid for gid, deg in in_degree.items() if deg == 0]
    ordered: list[CommitGroup] = []

    while queue:
        if len(queue) > 1:
            # Tie-break: try LLM, fall back to category heuristic
            queue = _tie_break(queue, group_map, llm_call_fn, trace)

        current = queue.pop(0)
        ordered.append(group_map[current])

        for neighbor in adj.get(current, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Handle cycles: if some groups weren't visited, append them
    visited = {g.group_id for g in ordered}
    for g in groups:
        if g.group_id not in visited:
            logger.warning("Phase 4: group %s in cycle, appending at end", g.group_id)
            trace.warning("phase4", f"Group {g.group_id} in dependency cycle, appended at end")
            ordered.append(g)

    return ordered


_CATEGORY_ORDER = {
    "refactor": 0,
    "config": 1,
    "chore": 2,
    "feature": 3,
    "feat": 3,
    "bugfix": 4,
    "fix": 4,
    "test": 5,
    "docs": 6,
}


def _tie_break(
    queue: list[str],
    group_map: dict[str, CommitGroup],
    llm_call_fn: Callable[[str, str], RawLLMResult],
    trace: AgentTrace,
) -> list[str]:
    """Break ties among zero-in-degree groups. Try LLM, fall back to heuristic."""
    if len(queue) <= 1:
        return queue

    # Build context for LLM
    group_descriptions = []
    for gid in queue:
        g = group_map[gid]
        group_descriptions.append(
            f"  {gid}: category={g.category}, theme=\"{g.theme}\", hunks={len(g.hunk_ids)}"
        )

    user_prompt = (
        "Rank these commit groups in the order they should be committed:\n\n"
        + "\n".join(group_descriptions)
        + "\n\nOutput ONLY a JSON array of group IDs."
    )

    try:
        trace.llm_call("phase4", _TIE_BREAK_SYSTEM_PROMPT, user_prompt)
        start_time = time.time()
        result = llm_call_fn(_TIE_BREAK_SYSTEM_PROMPT, user_prompt)
        duration_ms = (time.time() - start_time) * 1000
        trace.llm_response(
            "phase4", result.raw_response, result.model,
            {"input": result.input_tokens, "output": result.output_tokens,
             "thinking": result.thinking_tokens},
            duration_ms,
        )

        # Parse ordered IDs
        ordered_ids = _parse_ordered_ids(result.raw_response, set(queue))
        if ordered_ids:
            return ordered_ids
    except Exception as e:
        logger.debug("Phase 4 LLM tie-break failed: %s, using heuristic", e)
        trace.warning("phase4", f"LLM tie-break failed: {e}, using heuristic")

    # Heuristic fallback: sort by category order
    return sorted(queue, key=lambda gid: _CATEGORY_ORDER.get(
        group_map[gid].category.lower(), 3
    ))


def _parse_ordered_ids(response: str, valid_ids: set[str]) -> Optional[list[str]]:
    """Parse LLM response as a JSON array of group IDs."""
    text = response.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        ids = json.loads(text)
    except json.JSONDecodeError:
        # Try to find array
        import re
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                ids = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        else:
            return None

    if not isinstance(ids, list):
        return None

    # Validate all IDs are in the valid set
    result = [str(i) for i in ids if str(i) in valid_ids]
    # Add any missing IDs at the end
    for vid in valid_ids:
        if vid not in result:
            result.append(vid)

    return result
