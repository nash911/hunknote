"""Messenger sub-agent."""

from __future__ import annotations

import json
import logging

from hunknote.compose.agents.base import BaseSubAgent
from hunknote.compose.agents.prompts import MESSENGER_PROMPT
from hunknote.compose.models import CommitGroup, ComposePlan, HunkRef, PlannedCommit

logger = logging.getLogger(__name__)


class MessengerAgent(BaseSubAgent):
    """Generate commit messages for final ordered groups."""

    def __init__(self, *, model: str, max_tokens: int = 9000) -> None:
        super().__init__(
            name="Messenger",
            model=model,
            system_prompt=MESSENGER_PROMPT,
            max_iterations=1,
            max_tokens=max_tokens,
            temperature=0.2,
        )

    def run(
        self,
        ordered_groups: list[CommitGroup],
        inventory: dict[str, HunkRef],
        style: str,
        branch: str,
        recent_commits: list[str],
    ) -> ComposePlan:
        payload_groups = []
        for i, group in enumerate(ordered_groups, start=1):
            items = []
            for hid in group.hunk_ids:
                h = inventory.get(hid)
                if not h:
                    continue
                lines = [
                    ln for ln in h.lines
                    if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))
                ]
                items.append({
                    "hunk_id": hid,
                    "file_path": h.file_path,
                    "changed_lines": lines[:12],
                })
            payload_groups.append({
                "id": f"C{i}",
                "intent": group.reason,
                "files": group.files,
                "hunks": items,
            })

        prompt = f"""Generate commit messages.

[CONTEXT]
style={style}
branch={branch}
recent_commits={recent_commits[:3]}

[GROUPS]
{json.dumps(payload_groups, indent=2)}

Return JSON now."""

        result = self._single_call(prompt)
        if result.success and result.output:
            try:
                return ComposePlan(**result.output)
            except Exception as exc:
                logger.warning("Messenger output invalid, using fallback: %s", exc)

        return self._fallback_plan(ordered_groups)

    @staticmethod
    def _fallback_plan(groups: list[CommitGroup]) -> ComposePlan:
        commits = []
        for i, group in enumerate(groups, start=1):
            commits.append(
                PlannedCommit(
                    id=f"C{i}",
                    type="chore",
                    scope="",
                    title=(group.reason or f"Update {', '.join(group.files[:2])}")[:72],
                    bullets=[f"Modify {f}" for f in group.files[:6]],
                    hunks=group.hunk_ids,
                )
            )
        return ComposePlan(commits=commits)
