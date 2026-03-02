"""Grouping logic for the Compose Agent.

Implements:
- should_use_agent: Threshold check for activating agent mode
- group_hunks_programmatic: Connected-component-based grouping with validation
"""

from hunknote.compose.checkpoint import validate_commit_checkpoint
from hunknote.compose.graph import (
    build_hunk_dependency_graph,
    compute_connected_components,
    detect_renames,
    topological_sort_groups,
)
from hunknote.compose.models import CommitGroup, FileDiff, HunkRef, HunkSymbols


# Configurable thresholds (per design doc — resolved decisions)
AGENT_HUNK_THRESHOLD = 10
AGENT_CONNECTIVITY_THRESHOLD = 0.5


def should_use_agent(
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
    hunk_threshold: int = AGENT_HUNK_THRESHOLD,
    connectivity_threshold: float = AGENT_CONNECTIVITY_THRESHOLD,
) -> bool:
    """Determine whether to use the agent or single-shot LLM.

    Activates agent mode when:
    - The number of hunks exceeds the threshold (default: >10)
    - OR the file-level dependency graph has high connectivity (>50% of files)

    Args:
        inventory: Dictionary mapping hunk ID to HunkRef.
        file_diffs: Parsed file diffs.
        hunk_threshold: Minimum hunks for agent activation.
        connectivity_threshold: Minimum file connectivity ratio.

    Returns:
        True if agent mode should be used.
    """
    # Check hunk count
    if len(inventory) > hunk_threshold:
        return True

    # Check file connectivity (simple heuristic: if many hunks are in few files)
    total_files = len(file_diffs)
    if total_files <= 1:
        return False

    # Count files that share symbols
    files_with_hunks = {fd.file_path for fd in file_diffs if fd.hunks}
    if len(files_with_hunks) > 0:
        hunks_per_file = len(inventory) / len(files_with_hunks)
        if hunks_per_file > 3 and len(files_with_hunks) > 3:
            return True

    return False


def group_hunks_programmatic(
    symbol_analyses: dict[str, HunkSymbols],
    all_hunk_ids: set[str],
    graph: dict[str, set[str]] | None = None,
) -> list[CommitGroup]:
    """Group hunks into atomic commit groups using the dependency graph.

    Uses connected components as initial groups, validates each checkpoint,
    and merges groups if violations are found.

    Args:
        symbol_analyses: Dictionary of hunk ID to HunkSymbols.
        all_hunk_ids: Complete set of all hunk IDs.
        graph: Optional pre-computed dependency graph.

    Returns:
        Ordered list of CommitGroup objects.
    """
    if graph is None:
        renames = detect_renames(symbol_analyses)
        graph = build_hunk_dependency_graph(symbol_analyses, renames)

    # Compute connected components
    components = compute_connected_components(graph, all_hunk_ids)

    # Topologically sort the components
    sorted_components = topological_sort_groups(components, graph)

    # Validate checkpoints and merge if needed
    groups = _validate_and_merge(sorted_components, graph, symbol_analyses, all_hunk_ids)

    # Convert to CommitGroup objects
    result: list[CommitGroup] = []
    for group_hunks in groups:
        # Determine files touched
        files: set[str] = set()
        for hunk_id in group_hunks:
            symbols = symbol_analyses.get(hunk_id)
            if symbols:
                files.add(symbols.file_path)

        result.append(CommitGroup(
            hunk_ids=sorted(group_hunks),
            files=sorted(files),
        ))

    return result


def _validate_and_merge(
    groups: list[set[str]],
    graph: dict[str, set[str]],
    symbol_analyses: dict[str, HunkSymbols],
    all_hunk_ids: set[str],
    max_iterations: int = 10,
) -> list[set[str]]:
    """Validate checkpoints and merge groups that cause violations.

    Iteratively checks each checkpoint. If a violation is found,
    merges the violating groups and re-validates.

    Args:
        groups: Initial list of commit groups.
        graph: Directed hunk dependency graph.
        symbol_analyses: Symbol analysis for all hunks.
        all_hunk_ids: Complete set of all hunk IDs.
        max_iterations: Maximum merge iterations to prevent infinite loops.

    Returns:
        Validated and possibly merged list of commit groups.
    """
    for _ in range(max_iterations):
        committed_so_far: set[str] = set()
        merge_needed = False
        merge_indices: tuple[int, int] | None = None

        for i, group in enumerate(groups):
            checkpoint = committed_so_far | group
            remaining = all_hunk_ids - checkpoint

            result = validate_commit_checkpoint(
                committed_hunks=checkpoint,
                remaining_hunks=remaining,
                graph=graph,
                symbol_analyses=symbol_analyses,
            )

            if not result.valid:
                # Find which group contains the violating hunk
                for violation in result.violations:
                    violating_hunk = violation.hunk if not violation.in_commit else violation.defined_in
                    for j, other_group in enumerate(groups):
                        if j != i and violating_hunk in other_group:
                            merge_indices = (min(i, j), max(i, j))
                            merge_needed = True
                            break
                    if merge_needed:
                        break

            if merge_needed:
                break

            committed_so_far = checkpoint

        if not merge_needed:
            break

        if merge_indices:
            idx_a, idx_b = merge_indices
            merged = groups[idx_a] | groups[idx_b]
            new_groups = []
            for k, g in enumerate(groups):
                if k == idx_a:
                    new_groups.append(merged)
                elif k == idx_b:
                    continue
                else:
                    new_groups.append(g)
            groups = new_groups
            # Re-sort after merge
            groups = topological_sort_groups(groups, graph)

    return groups

