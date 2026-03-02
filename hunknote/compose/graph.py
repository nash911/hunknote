"""Hunk-level dependency graph for the Compose Agent.

Implements:
- build_hunk_dependency_graph: Build directed edges between hunks
- detect_renames: Find old_name → new_name pairs across hunks
- find_related_hunks: Transitive closure from a starting hunk
- compute_connected_components: Group transitively connected hunks
- topological_sort_groups: Order commit groups by dependencies
"""

import re
from collections import defaultdict, deque

from hunknote.compose.models import HunkSymbols, Rename


def _extract_symbol_from_import(import_path: str) -> str:
    """Extract the symbol name from any language's import path.

    Normalises import paths across all language conventions:
    Python:  'core.utils.rate_limit'  → 'rate_limit'
    JS/TS:   './helpers'              → 'helpers'
    Go:      'pkg/auth'               → 'auth'
    Rust:    'crate::auth::service'   → 'service'
    Java:    'com.example.UserService' → 'UserService'
    Ruby:    'lib/auth/service'       → 'service'
    C/C++:   'auth/service.h'         → 'service'

    Args:
        import_path: Raw import path string.

    Returns:
        The final symbol/module name.
    """
    # Strip file extensions
    path = re.sub(
        r"\.(py|ts|tsx|js|jsx|go|rs|java|kt|rb|h|hpp|cs|swift|php|proto)$",
        "",
        import_path,
    )
    # Split by all common separators and take the last segment
    parts = re.split(r"[./\\:]+", path)
    return parts[-1] if parts else import_path


def detect_renames(
    symbol_analyses: dict[str, HunkSymbols],
) -> list[Rename]:
    """Detect rename pairs within hunks.

    A rename occurs when a hunk removes a symbol and defines a new one
    in the same hunk, and the names share a structural similarity
    (e.g., similar length, shared prefix/suffix, or Levenshtein distance).

    Args:
        symbol_analyses: Dictionary of hunk ID to HunkSymbols.

    Returns:
        List of detected Rename pairs.
    """
    renames: list[Rename] = []

    for hunk_id, symbols in symbol_analyses.items():
        for removed in symbols.removes:
            for added in symbols.defines:
                if _is_likely_rename(removed, added):
                    renames.append(Rename(
                        old_name=removed,
                        new_name=added,
                        defining_hunk=hunk_id,
                    ))

    return renames


def _is_likely_rename(old_name: str, new_name: str) -> bool:
    """Heuristic: check if old_name → new_name looks like a rename.

    Criteria:
    - Same case style (both camelCase, both snake_case, etc.)
    - Shared prefix or suffix of at least 3 characters
    - Not too different in length (±50%)

    Args:
        old_name: The removed symbol name.
        new_name: The added symbol name.

    Returns:
        True if this is likely a rename.
    """
    if old_name == new_name:
        return False

    # Length check: not too different
    len_ratio = len(new_name) / max(len(old_name), 1)
    if len_ratio < 0.5 or len_ratio > 2.0:
        return False

    # Same case style
    old_is_upper = old_name[0].isupper()
    new_is_upper = new_name[0].isupper()
    if old_is_upper != new_is_upper:
        return False

    # Shared prefix or suffix (at least 3 chars)
    min_shared = min(3, min(len(old_name), len(new_name)))
    has_prefix = old_name[:min_shared] == new_name[:min_shared]
    has_suffix = old_name[-min_shared:] == new_name[-min_shared:]

    return has_prefix or has_suffix


def build_hunk_dependency_graph(
    symbol_analyses: dict[str, HunkSymbols],
    renames: list[Rename] | None = None,
) -> dict[str, set[str]]:
    """Build a directed dependency graph between hunks.

    An edge from H_a to H_b means "H_a depends on H_b" (H_a references
    a module-scope symbol that H_b defines or modifies).

    Args:
        symbol_analyses: Dictionary of hunk ID to HunkSymbols.
        renames: Optional list of detected renames.

    Returns:
        Adjacency list: {hunk_id: {dependent_hunk_ids}}.
    """
    if renames is None:
        renames = detect_renames(symbol_analyses)

    # Build map: symbol_name → hunk that defines it
    symbol_to_hunk: dict[str, str] = {}
    for hunk_id, symbols in symbol_analyses.items():
        for sym in symbols.defines:
            symbol_to_hunk[sym] = hunk_id
        for sym in symbols.modifies:
            symbol_to_hunk.setdefault(sym, hunk_id)

    # Build rename map: old_name → (new_name, defining_hunk)
    rename_map: dict[str, tuple[str, str]] = {
        r.old_name: (r.new_name, r.defining_hunk) for r in renames
    }

    edges: dict[str, set[str]] = {}

    for hunk_id, symbols in symbol_analyses.items():
        deps: set[str] = set()

        # Direct reference: hunk uses a symbol defined by another hunk
        for ref in symbols.references:
            definer = symbol_to_hunk.get(ref)
            if definer and definer != hunk_id:
                deps.add(definer)

        # Import dependency (works for any language)
        for imp in symbols.imports_added:
            sym = _extract_symbol_from_import(imp)
            definer = symbol_to_hunk.get(sym)
            if definer and definer != hunk_id:
                deps.add(definer)

        # Rename chain: if this hunk removes an import for old_name,
        # and another hunk defines the rename, they're linked
        for removed_imp in symbols.imports_removed:
            sym = _extract_symbol_from_import(removed_imp)
            if sym in rename_map:
                rename_hunk = rename_map[sym][1]
                if rename_hunk != hunk_id:
                    deps.add(rename_hunk)

        # Export dependency: if this hunk exports something defined elsewhere
        for exp in symbols.exports_added:
            definer = symbol_to_hunk.get(exp)
            if definer and definer != hunk_id:
                deps.add(definer)

        if deps:
            edges[hunk_id] = deps

    return edges


def find_related_hunks(
    hunk_id: str,
    graph: dict[str, set[str]],
) -> set[str]:
    """Find all hunks transitively connected to a given hunk.

    Treats the graph as undirected: follows edges in both directions
    to find all hunks that must be in the same commit group.

    Args:
        hunk_id: The starting hunk ID.
        graph: Directed dependency graph.

    Returns:
        Set of all transitively connected hunk IDs (including start).
    """
    # Build undirected adjacency
    undirected: dict[str, set[str]] = defaultdict(set)
    for source, targets in graph.items():
        for target in targets:
            undirected[source].add(target)
            undirected[target].add(source)

    # BFS
    visited: set[str] = set()
    queue: deque[str] = deque([hunk_id])

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for neighbor in undirected.get(current, set()):
            if neighbor not in visited:
                queue.append(neighbor)

    return visited


def compute_connected_components(
    graph: dict[str, set[str]],
    all_hunk_ids: set[str],
) -> list[set[str]]:
    """Compute connected components of the hunk dependency graph.

    Treats the graph as undirected. Hunks not in the graph are
    returned as singleton components.

    Args:
        graph: Directed dependency graph.
        all_hunk_ids: Complete set of all hunk IDs.

    Returns:
        List of sets, each set being a connected component.
    """
    # Build undirected adjacency
    undirected: dict[str, set[str]] = defaultdict(set)
    for source, targets in graph.items():
        for target in targets:
            undirected[source].add(target)
            undirected[target].add(source)

    visited: set[str] = set()
    components: list[set[str]] = []

    for hunk_id in sorted(all_hunk_ids):
        if hunk_id in visited:
            continue
        # BFS to find the component
        component: set[str] = set()
        queue: deque[str] = deque([hunk_id])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            for neighbor in undirected.get(current, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        components.append(component)

    return components


def build_inter_group_edges(
    groups: list[set[str]],
    graph: dict[str, set[str]],
) -> dict[int, set[int]]:
    """Build dependency edges between commit groups.

    Group A depends on group B if any hunk in A depends on any hunk in B.

    Args:
        groups: List of commit groups (sets of hunk IDs).
        graph: Directed hunk dependency graph.

    Returns:
        Directed edges between group indices.
    """
    # Map hunk → group index
    hunk_to_group: dict[str, int] = {}
    for i, group in enumerate(groups):
        for hunk_id in group:
            hunk_to_group[hunk_id] = i

    group_edges: dict[int, set[int]] = defaultdict(set)

    for source, targets in graph.items():
        source_group = hunk_to_group.get(source)
        if source_group is None:
            continue
        for target in targets:
            target_group = hunk_to_group.get(target)
            if target_group is not None and target_group != source_group:
                group_edges[source_group].add(target_group)

    return dict(group_edges)


def topological_sort_groups(
    groups: list[set[str]],
    graph: dict[str, set[str]],
) -> list[set[str]]:
    """Topologically sort commit groups by inter-group dependencies.

    If cycles exist, the cyclic groups are merged.

    Args:
        groups: List of commit groups (sets of hunk IDs).
        graph: Directed hunk dependency graph.

    Returns:
        Ordered list of commit groups (dependencies first).
    """
    if len(groups) <= 1:
        return list(groups)

    group_edges = build_inter_group_edges(groups, graph)

    # Kahn's algorithm for topological sort
    in_degree: dict[int, int] = {i: 0 for i in range(len(groups))}
    for source, targets in group_edges.items():
        for target in targets:
            if target in in_degree:
                # source depends on target, so target must come first
                # We need reverse edges for topological sort
                pass

    # Reverse: if group A depends on group B, B comes before A
    reverse_edges: dict[int, set[int]] = defaultdict(set)
    for source, targets in group_edges.items():
        for target in targets:
            reverse_edges[target].add(source)

    # In-degree based on who comes before whom
    in_degree = {i: 0 for i in range(len(groups))}
    for source, targets in group_edges.items():
        in_degree[source] = in_degree.get(source, 0) + len(targets)

    # Wait — rethink: if A depends on B, then B must come BEFORE A
    # So the edge direction for topological sort is B → A
    # in_degree of A increases by 1 for each dependency
    in_degree = {i: 0 for i in range(len(groups))}
    for group_idx, deps in group_edges.items():
        in_degree[group_idx] = len(deps)

    queue: deque[int] = deque()
    for idx, degree in in_degree.items():
        if degree == 0:
            queue.append(idx)

    sorted_indices: list[int] = []
    while queue:
        current = queue.popleft()
        sorted_indices.append(current)
        # Find groups that depend on current
        for group_idx, deps in group_edges.items():
            if current in deps:
                deps_copy = deps - {current}
                group_edges[group_idx] = deps_copy
                in_degree[group_idx] = len(deps_copy)
                if len(deps_copy) == 0 and group_idx not in sorted_indices:
                    queue.append(group_idx)

    # Handle cycles: any groups not in sorted_indices
    remaining = set(range(len(groups))) - set(sorted_indices)
    if remaining:
        # Merge all cyclic groups into one
        merged: set[str] = set()
        for idx in remaining:
            merged.update(groups[idx])
        # Insert merged group at the beginning
        result = [merged]
        for idx in sorted_indices:
            if idx not in remaining:
                result.append(groups[idx])
        return result

    return [groups[idx] for idx in sorted_indices]

