"""Messenger sub-agent.

Generates conventional commit messages for validated commit groups.
This is a single-call agent (no ReAct loop) — it sends the groups and
diff context to the LLM in one shot and parses the commit messages.
"""

from __future__ import annotations

import logging

from hunknote.compose.agents.base import BaseSubAgent, SubAgentResult
from hunknote.compose.agents.prompts import MESSENGER_PROMPT
from hunknote.compose.models import (
    CommitGroup,
    ComposePlan,
    FileDiff,
    HunkRef,
    PlannedCommit,
)

logger = logging.getLogger(__name__)


class MessengerAgent(BaseSubAgent):
    """Sub-agent that generates commit messages for validated groups."""

    def __init__(
        self,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ):
        super().__init__(
            name="Messenger",
            system_prompt=MESSENGER_PROMPT,
            model=model,
            max_iterations=1,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def run(
        self,
        ordered_groups: list[CommitGroup],
        inventory: dict[str, HunkRef],
        file_diffs: list[FileDiff],
        style: str = "blueprint",
        branch: str = "",
        recent_commits: list[str] | None = None,
    ) -> ComposePlan:
        """Generate commit messages for the ordered groups.

        Args:
            ordered_groups: Validated, ordered commit groups.
            inventory: Hunk inventory.
            file_diffs: File diffs.
            style: Commit style.
            branch: Branch name.
            recent_commits: Recent commit subjects.

        Returns:
            ComposePlan with commit messages.
        """
        prompt = self._build_prompt(
            ordered_groups, inventory, file_diffs,
            style, branch, recent_commits,
        )

        result = self._single_call(prompt)

        if not result.success or not result.output:
            logger.warning("Message generation failed: %s, using placeholders", result.error)
            return self._fallback_plan(ordered_groups)

        return self._parse_output(result, ordered_groups)

    def _build_prompt(
        self,
        groups: list[CommitGroup],
        inventory: dict[str, HunkRef],
        file_diffs: list[FileDiff],
        style: str,
        branch: str,
        recent_commits: list[str] | None,
    ) -> str:
        """Build the user prompt for message generation."""
        sections: list[str] = []

        sections.append("[CONTEXT]")
        if branch:
            sections.append(f"Branch: {branch}")
        if recent_commits:
            sections.append(f"Recent commits: {', '.join(recent_commits[:3])}")
        sections.append(f"Style: {style}")
        sections.append(f"Total commits: {len(groups)}")
        sections.append("")

        sections.append("[COMMIT GROUPS]")
        for i, group in enumerate(groups, 1):
            sections.append(f"--- C{i} ---")
            sections.append(f"Files: {', '.join(group.files)}")
            sections.append(f"Hunks: {', '.join(group.hunk_ids)}")
            if group.reason:
                sections.append(f"Intent: {group.reason}")
            sections.append("")

            for hunk_id in group.hunk_ids:
                hunk = inventory.get(hunk_id)
                if hunk:
                    sections.append(f"  [{hunk_id}] {hunk.file_path}")
                    changed = [
                        ln for ln in hunk.lines
                        if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))
                    ]
                    for ln in changed[:15]:
                        sections.append(f"    {ln}")
                    if len(changed) > 15:
                        sections.append(f"    ... ({len(changed) - 15} more lines)")
                    sections.append("")

        sections.append("Output ONLY the JSON object with commit messages.")
        return "\n".join(sections)

    def _parse_output(
        self,
        result: SubAgentResult,
        groups: list[CommitGroup],
    ) -> ComposePlan:
        """Parse the LLM output into a ComposePlan."""
        data = result.output

        if "commits" in data:
            try:
                return ComposePlan(**data)
            except Exception as e:
                logger.warning("Failed to parse plan from LLM output: %s", e)

        return self._fallback_plan(groups)

    @staticmethod
    def _fallback_plan(groups: list[CommitGroup]) -> ComposePlan:
        """Create a fallback plan with placeholder messages."""
        commits = []
        for i, group in enumerate(groups, 1):
            commits.append(PlannedCommit(
                id=f"C{i}",
                type="feat",
                scope="",
                title=f"Update {', '.join(group.files[:3])}",
                bullets=[f"Modify {f}" for f in group.files],
                hunks=group.hunk_ids,
            ))
        return ComposePlan(commits=commits)

