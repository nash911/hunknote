"""Grouper sub-agent.

Groups hunks into atomic commit groups based on the dependency graph.
Each group becomes a single commit (C1, C2, C3, ...).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from hunknote.compose.agents.base import BaseSubAgent, SubAgentResult
from hunknote.compose.agents.prompts import GROUPER_PROMPT
from hunknote.compose.agents.tools import build_hunk_summary_text
from hunknote.compose.models import (
    CommitGroup,
    DependencyGraph,
    FileDiff,
    HunkRef,
    HunkSymbols,
)

logger = logging.getLogger(__name__)


class GrouperAgent(BaseSubAgent):
    """Sub-agent that groups hunks into atomic commit groups."""

    def __init__(
        self,
        model: str,
        inventory: dict[str, HunkRef],
        file_diffs: list[FileDiff],
        max_iterations: int = 4,
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ):
        super().__init__(
            name="Grouper",
            system_prompt=GROUPER_PROMPT,
            model=model,
            max_iterations=max_iterations,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.inventory = inventory
        self.file_diffs = file_diffs

    def run(
        self,
        dependency_graph: DependencyGraph,
        max_commits: int = 16,
        symbol_analyses: dict[str, HunkSymbols] | None = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        regroup_hint: str | None = None,
    ) -> list[CommitGroup]:
        """Group hunks into commit groups.

        Args:
            dependency_graph: The dependency graph from the Analyzer.
            max_commits: Maximum number of commit groups.
            symbol_analyses: Optional symbol data for context.
            stream_callback: Optional callback for streaming status.
            regroup_hint: Optional hint from the validator about what
                went wrong with the previous grouping.

        Returns:
            List of CommitGroup objects.
        """
        # Build the dependency summary for the LLM
        dep_text = self._format_dependencies(dependency_graph)
        hunk_text = build_hunk_summary_text(
            self.inventory, self.file_diffs, symbol_analyses,
        )

        hint_section = ""
        if regroup_hint:
            hint_section = f"""

[PREVIOUS GROUPING FEEDBACK]
{regroup_hint}
Take this feedback into account and fix the grouping accordingly.
"""

        user_prompt = f"""\
Group the following hunks into atomic commits based on the dependency
analysis. Maximum {max_commits} commits allowed.

[DEPENDENCY GRAPH]
{dep_text}

[HUNKS]
{hunk_text}
{hint_section}
Remember:
- Hunks with "must_be_together" dependencies MUST be in the same group.
- Each group should represent a single logical change.
- Use group IDs: C1, C2, C3, etc.
- Every hunk must be assigned to exactly one group.
- Keep groups as small as possible while respecting constraints.

Output your grouping as the specified JSON object."""

        result = self._react_loop(user_prompt, stream_callback)

        if not result.success or not result.output:
            logger.warning("Grouping failed: %s, falling back to single group", result.error)
            return [CommitGroup(
                hunk_ids=list(self.inventory.keys()),
                files=[fd.file_path for fd in self.file_diffs],
                reason="Fallback: single group due to grouping failure",
            )]

        return self._parse_output(result)

    def _format_dependencies(self, graph: DependencyGraph) -> str:
        """Format the dependency graph for the LLM prompt."""
        if not graph.edges:
            return "No dependencies detected. All hunks are independent."

        lines = []
        for edge in graph.edges:
            lines.append(
                f"  {edge.source} → {edge.target} "
                f"[{edge.strength}]: {edge.reason}"
            )
        if graph.independent_hunks:
            lines.append(f"\n  Independent hunks: {', '.join(graph.independent_hunks)}")
        return "\n".join(lines)

    def _parse_output(self, result: SubAgentResult) -> list[CommitGroup]:
        """Parse the agent output into CommitGroup objects."""
        data = result.output
        groups: list[CommitGroup] = []
        all_hunk_ids = set(self.inventory.keys())
        assigned: set[str] = set()

        for g_data in data.get("groups", []):
            hunk_ids = g_data.get("hunk_ids", [])
            # Filter to valid hunk IDs
            valid_ids = [h for h in hunk_ids if h in all_hunk_ids]
            if not valid_ids:
                continue
            assigned.update(valid_ids)

            # Derive files
            files = sorted(set(
                self.inventory[h].file_path for h in valid_ids
                if h in self.inventory
            ))

            groups.append(CommitGroup(
                hunk_ids=valid_ids,
                files=files,
                reason=g_data.get("intent", g_data.get("rationale", "")),
            ))

        # Handle unassigned hunks
        unassigned = all_hunk_ids - assigned
        if unassigned:
            files = sorted(set(
                self.inventory[h].file_path for h in unassigned
                if h in self.inventory
            ))
            groups.append(CommitGroup(
                hunk_ids=sorted(unassigned),
                files=files,
                reason="Unassigned hunks collected into final group",
            ))

        return groups if groups else [CommitGroup(
            hunk_ids=sorted(all_hunk_ids),
            files=[fd.file_path for fd in self.file_diffs],
            reason="Fallback: all hunks in single group",
        )]

