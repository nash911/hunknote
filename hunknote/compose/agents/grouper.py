"""Grouper sub-agent."""

from __future__ import annotations

import json
import logging

from hunknote.compose.agents.base import BaseSubAgent
from hunknote.compose.agents.prompts import GROUPER_PROMPT
from hunknote.compose.agents.tools import build_hunk_summaries
from hunknote.compose.models import CommitGroup, FileDiff, HunkRef

logger = logging.getLogger(__name__)


class GrouperAgent(BaseSubAgent):
    """Group hunks into atomic commit groups."""

    def __init__(
        self,
        *,
        model: str,
        inventory: dict[str, HunkRef],
        file_diffs: list[FileDiff],
        max_tokens: int = 16000,
    ) -> None:
        super().__init__(
            name="Grouper",
            model=model,
            system_prompt=GROUPER_PROMPT,
            max_iterations=4,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        self.inventory = inventory
        self.file_diffs = file_diffs

    def run(
        self,
        dependency_graph: dict,
        max_commits: int,
        regroup_hint: str = "",
    ) -> list[CommitGroup]:
        hunk_text = build_hunk_summaries(self.inventory, self.file_diffs)
        dep_text = json.dumps(dependency_graph, indent=2)
        hint_block = f"\n[RETRY_HINT]\n{regroup_hint}\n" if regroup_hint else ""

        prompt = f"""Group hunks into <= {max_commits} commits.

[DEPENDENCY_GRAPH]
{dep_text}

[HUNKS]
{hunk_text}
{hint_block}
Return JSON now."""

        result = self._single_call(prompt)
        if not result.success or not result.output:
            logger.warning("Grouper failed, fallback to single group: %s", result.error)
            return [
                CommitGroup(
                    hunk_ids=sorted(self.inventory.keys()),
                    files=sorted({h.file_path for h in self.inventory.values()}),
                    reason="Fallback single group",
                )
            ]

        groups = self._parse_groups(result.output)
        if len(groups) > max_commits:
            groups = self._merge_down(groups, max_commits)
        return groups

    def _parse_groups(self, payload: dict) -> list[CommitGroup]:
        all_hunks = set(self.inventory.keys())
        assigned: set[str] = set()
        groups: list[CommitGroup] = []

        for g in payload.get("groups", []):
            hunk_ids = [hid for hid in g.get("hunk_ids", []) if hid in all_hunks]
            if not hunk_ids:
                continue
            assigned.update(hunk_ids)
            files = sorted({self.inventory[hid].file_path for hid in hunk_ids})
            groups.append(
                CommitGroup(
                    hunk_ids=hunk_ids,
                    files=files,
                    reason=g.get("intent", ""),
                )
            )

        remaining = sorted(all_hunks - assigned)
        if remaining:
            groups.append(
                CommitGroup(
                    hunk_ids=remaining,
                    files=sorted({self.inventory[hid].file_path for hid in remaining}),
                    reason="Collected unassigned hunks",
                )
            )

        return groups or [
            CommitGroup(
                hunk_ids=sorted(all_hunks),
                files=sorted({h.file_path for h in self.inventory.values()}),
                reason="Fallback single group",
            )
        ]

    @staticmethod
    def _merge_down(groups: list[CommitGroup], max_commits: int) -> list[CommitGroup]:
        merged = list(groups)
        while len(merged) > max_commits and len(merged) > 1:
            first = merged.pop()
            prev = merged.pop()
            merged.append(
                CommitGroup(
                    hunk_ids=sorted(set(prev.hunk_ids + first.hunk_ids)),
                    files=sorted(set(prev.files + first.files)),
                    reason="Merged to satisfy max_commits",
                )
            )
        return merged
