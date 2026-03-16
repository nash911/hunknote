"""Data models for the Compose Agent pipeline.

Holds all intermediate state produced by each phase. The orchestrator owns
instances of these and passes them between phases.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── Phase 1 output ──

@dataclass
class HunkSummary:
    """Output of Phase 1 for a single hunk."""

    hunk_id: str               # e.g. "H1_abc123" — uses existing IDs from parser
    file_path: str
    intent: str                # e.g. "Add retry logic with exponential backoff"
    category: str              # "feature", "bugfix", "refactor", "test", "docs", "config"
    symbols_modified: list[str] = field(default_factory=list)
    symbols_referenced: list[str] = field(default_factory=list)
    is_new_file: bool = False


# ── Phase 2 output ──

class EdgeType(Enum):
    DIRECTIONAL = "directional"      # A needs B first; B is valid without A
    BIDIRECTIONAL = "bidirectional"   # A and B must be in the same commit


@dataclass
class DependencyEdge:
    from_hunk: str       # e.g. "H3_abc123"
    to_hunk: str         # e.g. "H7_def456"
    edge_type: EdgeType
    reason: str


@dataclass
class DependencyGraph:
    edges: list[DependencyEdge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_edge(self, edge: DependencyEdge) -> None:
        """Add a single edge to the graph."""
        self.edges.append(edge)

    def add_bidirectional(self, hunk_ids: list[str], reason: str) -> None:
        """Add bidirectional edges between all pairs in hunk_ids."""
        for i in range(len(hunk_ids)):
            for j in range(i + 1, len(hunk_ids)):
                self.edges.append(DependencyEdge(
                    from_hunk=hunk_ids[i],
                    to_hunk=hunk_ids[j],
                    edge_type=EdgeType.BIDIRECTIONAL,
                    reason=reason,
                ))

    def get_edges_for_hunk(self, hunk_id: str) -> list[DependencyEdge]:
        """Get all edges involving this hunk (as source or target)."""
        return [
            e for e in self.edges
            if e.from_hunk == hunk_id or e.to_hunk == hunk_id
        ]

    def get_bidirectional_groups(self) -> list[set[str]]:
        """Compute connected components of bidirectional edges using union-find."""
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            if x not in parent:
                parent[x] = x
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for edge in self.edges:
            if edge.edge_type == EdgeType.BIDIRECTIONAL:
                union(edge.from_hunk, edge.to_hunk)

        groups: dict[str, set[str]] = {}
        for node in parent:
            root = find(node)
            groups.setdefault(root, set()).add(node)

        return [g for g in groups.values() if len(g) > 1]

    def get_dependencies_of(self, hunk_id: str) -> set[str]:
        """Get all hunk IDs that hunk_id depends on (directional edges where hunk_id is 'from')."""
        deps: set[str] = set()
        for edge in self.edges:
            if edge.edge_type == EdgeType.DIRECTIONAL and edge.from_hunk == hunk_id:
                deps.add(edge.to_hunk)
        return deps


# ── Phase 3 output ──

@dataclass
class CommitGroup:
    """A candidate commit. Uses temporary _G{n} IDs during Phase 3,
    renamed to C{n} during Phase 4 ordering."""

    group_id: str           # "_G1" during clustering, "C1" after ordering
    hunk_ids: list[str]     # e.g. ["H1_abc123", "H5_def456"]
    theme: str              # Short description of what this group does
    category: str           # "feature", "refactor", "test", etc.


# ── Phase 5a output ──

class ValidationLayer(Enum):
    PATCH_APPLY = "patch_apply"
    SYNTAX = "syntax"
    COMPILE = "compile"
    IMPORT = "import"
    IMPORT_DEPS = "import_deps"
    TEST = "test"


@dataclass
class ValidationFailure:
    commit_index: int
    commit_group: CommitGroup
    layer: ValidationLayer
    error_output: str
    file_path: Optional[str] = None


# ── Phase 5b output ──

class RemediationAction(Enum):
    RECLUSTER = "recluster"
    REORDER = "reorder"
    SPLIT_COMMIT = "split_commit"
    UNLOCK_AND_RECLUSTER = "unlock_and_recluster"
    FAIL = "fail"


@dataclass
class Remediation:
    action: RemediationAction
    diagnosis: str
    modifications: dict = field(default_factory=dict)
    revalidate_from_commit_index: int = 0
    unlock_from_commit_index: Optional[int] = None


# ── Frozen/Mutable state ──

@dataclass
class FrozenCommit:
    """A validated commit that should not be modified."""

    index: int
    message: str
    hunk_ids: list[str]
    symbols_introduced: list[str] = field(default_factory=list)
    symbols_removed: list[str] = field(default_factory=list)


@dataclass
class FrozenBaseline:
    commits: list[FrozenCommit] = field(default_factory=list)

    @property
    def all_hunk_ids(self) -> set[str]:
        """Return all hunk IDs consumed by frozen commits."""
        ids: set[str] = set()
        for c in self.commits:
            ids.update(c.hunk_ids)
        return ids


@dataclass
class MutableWorkingSet:
    hunk_ids: list[str] = field(default_factory=list)
    hunk_summaries: dict[str, HunkSummary] = field(default_factory=dict)
    dependency_edges: list[DependencyEdge] = field(default_factory=list)
