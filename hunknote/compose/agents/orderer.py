"""Orderer sub-agent."""

from __future__ import annotations

import json
import logging

from hunknote.compose.agents.base import BaseSubAgent
from hunknote.compose.agents.prompts import ORDERER_PROMPT
from hunknote.compose.models import CommitGroup

logger = logging.getLogger(__name__)


class OrdererAgent(BaseSubAgent):
    """Order commit groups based on dependencies."""

    def __init__(self, *, model: str, max_tokens: int = 12000) -> None:
        super().__init__(
            name="Orderer",
            model=model,
            system_prompt=ORDERER_PROMPT,
            max_iterations=4,
            max_tokens=max_tokens,
            temperature=0.0,
        )

    def run(
        self,
        groups: list[CommitGroup],
        dependency_graph: dict,
        reorder_hint: str = "",
    ) -> list[CommitGroup]:
        if len(groups) <= 1:
            return groups

        group_payload = []
        for i, g in enumerate(groups, start=1):
            group_payload.append({
                "id": f"C{i}",
                "hunk_ids": g.hunk_ids,
                "files": g.files,
                "intent": g.reason,
            })

        hint_block = f"\n[RETRY_HINT]\n{reorder_hint}\n" if reorder_hint else ""
        prompt = f"""Order commit groups.

[GROUPS]
{json.dumps(group_payload, indent=2)}

[DEPENDENCY_GRAPH]
{json.dumps(dependency_graph, indent=2)}
{hint_block}
Return JSON now."""

        result = self._single_call(prompt)
        if not result.success or not result.output:
            logger.warning("Orderer failed; keep original order: %s", result.error)
            return groups

        ordered_ids = result.output.get("ordered_group_ids", [])
        return self._apply_order(groups, ordered_ids)

    @staticmethod
    def _apply_order(groups: list[CommitGroup], ordered_ids: list[str]) -> list[CommitGroup]:
        id_to_group = {f"C{i+1}": g for i, g in enumerate(groups)}
        ordered: list[CommitGroup] = []
        seen: set[str] = set()

        for gid in ordered_ids:
            if gid in id_to_group and gid not in seen:
                ordered.append(id_to_group[gid])
                seen.add(gid)

        for gid, group in id_to_group.items():
            if gid not in seen:
                ordered.append(group)

        return ordered
