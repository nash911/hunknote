"""Orderer sub-agent.

Determines the correct commit order so that every intermediate checkpoint
leaves the codebase in a valid state.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from hunknote.compose.agents.base import BaseSubAgent, SubAgentResult
from hunknote.compose.agents.prompts import ORDERER_PROMPT
from hunknote.compose.models import (
    CommitGroup,
    DependencyGraph,
    FileDiff,
    HunkRef,
    HunkSymbols,
)

logger = logging.getLogger(__name__)


class OrdererAgent(BaseSubAgent):
    """Sub-agent that orders commit groups for valid checkpoints."""

    def __init__(
        self,
        model: str,
        max_iterations: int = 4,
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ):
        super().__init__(
            name="Orderer",
            system_prompt=ORDERER_PROMPT,
            model=model,
            max_iterations=max_iterations,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def run(
        self,
        groups: list[CommitGroup],
        dependency_graph: DependencyGraph,
        inventory: dict[str, HunkRef],
        file_diffs: list[FileDiff],
        symbol_analyses: dict[str, HunkSymbols] | None = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        reorder_hint: str | None = None,
    ) -> list[CommitGroup]:
        """Order the commit groups.

        Args:
            groups: Commit groups from the Grouper.
            dependency_graph: The dependency graph.
            inventory: Hunk inventory.
            file_diffs: File diffs.
            symbol_analyses: Optional symbol data.
            stream_callback: Optional streaming callback.
            reorder_hint: Optional hint from the validator about what
                went wrong with the previous ordering.

        Returns:
            Ordered list of CommitGroup objects.
        """
        if len(groups) <= 1:
            return groups

        # Build group summary
        group_text = self._format_groups(groups, inventory)
        dep_text = self._format_cross_group_deps(groups, dependency_graph)

        hint_section = ""
        if reorder_hint:
            hint_section = f"""

[PREVIOUS ORDERING FEEDBACK]
{reorder_hint}
Take this feedback into account and fix the ordering accordingly.
"""

        user_prompt = f"""\
Order the following commit groups so that every intermediate checkpoint
is valid.

[COMMIT GROUPS]
{group_text}

[CROSS-GROUP DEPENDENCIES]
{dep_text}
{hint_section}
Order the groups and output the JSON object with "ordered_group_ids"
containing the group IDs in the correct commit order."""

        result = self._react_loop(user_prompt, stream_callback)

        if not result.success or not result.output:
            logger.warning("Ordering failed: %s, using original order", result.error)
            return groups

        return self._parse_output(result, groups)

    def _format_groups(
        self,
        groups: list[CommitGroup],
        inventory: dict[str, HunkRef],
    ) -> str:
        """Format groups for the LLM prompt."""
        lines = []
        for i, g in enumerate(groups, 1):
            gid = f"C{i}"
            lines.append(f"\n  {gid}: {len(g.hunk_ids)} hunks, files: {', '.join(g.files)}")
            lines.append(f"    Hunks: {', '.join(g.hunk_ids)}")
            if g.reason:
                lines.append(f"    Intent: {g.reason}")

            # Show snippet of what each hunk does
            for hid in g.hunk_ids[:5]:
                hunk = inventory.get(hid)
                if hunk:
                    changed = [ln for ln in hunk.lines
                               if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
                    snippet = "; ".join(ln.strip() for ln in changed[:3])
                    lines.append(f"      {hid} ({hunk.file_path}): {snippet[:100]}")
            if len(g.hunk_ids) > 5:
                lines.append(f"      ... and {len(g.hunk_ids) - 5} more hunks")

        return "\n".join(lines)

    def _format_cross_group_deps(
        self,
        groups: list[CommitGroup],
        dependency_graph: DependencyGraph,
    ) -> str:
        """Format cross-group dependencies."""
        # Build hunk-to-group mapping
        hunk_to_group: dict[str, str] = {}
        for i, g in enumerate(groups, 1):
            gid = f"C{i}"
            for hid in g.hunk_ids:
                hunk_to_group[hid] = gid

        cross_deps = []
        for edge in dependency_graph.edges:
            src_group = hunk_to_group.get(edge.source, "?")
            tgt_group = hunk_to_group.get(edge.target, "?")
            if src_group != tgt_group:
                cross_deps.append(
                    f"  {src_group} depends on {tgt_group}: "
                    f"{edge.source} → {edge.target} [{edge.strength}]"
                )

        if not cross_deps:
            return "  No cross-group dependencies. Groups can be in any order."
        return "\n".join(cross_deps)

    def _parse_output(
        self,
        result: SubAgentResult,
        groups: list[CommitGroup],
    ) -> list[CommitGroup]:
        """Parse the ordering output and reorder groups."""
        data = result.output
        ordered_ids = data.get("ordered_group_ids", [])

        if not ordered_ids:
            return groups

        # Build group-id → group mapping
        id_to_group = {f"C{i+1}": g for i, g in enumerate(groups)}

        ordered_groups = []
        seen = set()
        for gid in ordered_ids:
            if gid in id_to_group and gid not in seen:
                ordered_groups.append(id_to_group[gid])
                seen.add(gid)

        # Append any groups that weren't mentioned
        for gid, g in id_to_group.items():
            if gid not in seen:
                ordered_groups.append(g)

        return ordered_groups

