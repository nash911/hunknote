"""Phase 6: Commit Message Generation.

Single LLM call per commit. Produces PlannedCommit objects compatible
with the existing style rendering pipeline.
"""

import json
import logging
import re
import time
from typing import Callable, Optional

from hunknote.compose.agent.models import CommitGroup, HunkSummary
from hunknote.compose.agent.tracing import AgentTrace
from hunknote.compose.models import HunkRef, PlannedCommit
from hunknote.llm.base import RawLLMResult

logger = logging.getLogger(__name__)

_MESSAGE_SYSTEM_PROMPT = """You are generating commit messages for a stack of atomic commits.
Output ONLY valid JSON. No markdown fences. No commentary."""


def run_phase6_messages(
    ordered_groups: list[CommitGroup],
    inventory: dict[str, HunkRef],
    summaries: dict[str, HunkSummary],
    style_config,
    effective_profile,
    llm_call_fn: Callable[[str, str], RawLLMResult],
    trace: AgentTrace,
) -> list[PlannedCommit]:
    """Generate commit messages for each ordered group.

    Returns:
        List of PlannedCommit objects with C{n} IDs.
    """
    planned_commits: list[PlannedCommit] = []
    previous_commits: list[str] = []

    for group in ordered_groups:
        user_prompt = _build_message_prompt(
            group, inventory, summaries, previous_commits, len(ordered_groups),
        )

        trace.llm_call("phase6", _MESSAGE_SYSTEM_PROMPT, user_prompt)
        start_time = time.time()

        try:
            result = llm_call_fn(_MESSAGE_SYSTEM_PROMPT, user_prompt)
        except Exception as e:
            logger.warning("Phase 6 LLM call failed for %s: %s", group.group_id, e)
            trace.warning("phase6", f"LLM call failed for {group.group_id}: {e}")
            # Fallback
            planned_commits.append(_fallback_commit(group))
            previous_commits.append(f"{group.group_id}: {group.theme}")
            continue

        duration_ms = (time.time() - start_time) * 1000
        trace.llm_response(
            "phase6", result.raw_response, result.model,
            {"input": result.input_tokens, "output": result.output_tokens,
             "thinking": result.thinking_tokens},
            duration_ms,
        )

        commit = _parse_message_response(result.raw_response, group)
        if commit is None:
            commit = _fallback_commit(group)
            trace.warning("phase6", f"Failed to parse message for {group.group_id}, using fallback")

        planned_commits.append(commit)
        previous_commits.append(f"{commit.id}: {commit.type}({commit.scope}): {commit.title}" if commit.scope
                                else f"{commit.id}: {commit.type}: {commit.title}" if commit.type
                                else f"{commit.id}: {commit.title}")

    return planned_commits


def _build_message_prompt(
    group: CommitGroup,
    inventory: dict[str, HunkRef],
    summaries: dict[str, HunkSummary],
    previous_commits: list[str],
    total_commits: int,
) -> str:
    """Build the prompt for generating a commit message."""
    lines = [
        f"Generate a commit message for this set of changes.",
        f"",
        f"Commit {group.group_id} — position {group.group_id[1:]} of {total_commits} in the stack.",
    ]

    if previous_commits:
        lines.append("Previous commits:")
        for pc in previous_commits:
            lines.append(f"  {pc}")
        lines.append("")

    lines.append("Changes in this commit:")
    for hid in group.hunk_ids:
        summary = summaries.get(hid)
        hunk = inventory.get(hid)
        if summary:
            lines.append(f"  {hid}: {summary.file_path}")
            lines.append(f"    Intent: {summary.intent}")
            if summary.symbols_modified:
                lines.append(f"    Symbols: {', '.join(summary.symbols_modified[:8])}")
        elif hunk:
            lines.append(f"  {hid}: {hunk.file_path}")
            # Show first 20 lines of diff
            snippet = "\n".join(hunk.lines[:20])
            lines.append(f"    Diff snippet:\n{snippet}")
        lines.append("")

    lines.append("""Output JSON:
{
  "type": "<feat|fix|refactor|test|docs|chore|style|perf|ci|build>",
  "scope": "<component/module affected, or null>",
  "title": "<imperative mood, NO type prefix>",
  "bullets": ["<specific change 1>", "<specific change 2>"]
}

Rules:
- Title must NOT include the type or scope prefix (those are separate fields).
- CHARACTER LIMIT: The final rendered commit header is "type(scope): title"
  or "type: title" (without scope). The ENTIRE header must be at most 72
  characters. Subtract the overhead of "type(scope): " from 72 to get max
  title length. If you pick a long scope, shorten the title to compensate.
  Example: type="feat", scope="agent/validation" → overhead=24 → title ≤ 48 chars.
  Example: type="fix", scope=null → overhead=5 → title ≤ 67 chars.
- Each bullet should reference specific function names, file names, or behaviors.
- Do not use vague bullets like "Updated code" or "Made improvements".""")

    return "\n".join(lines)


def _parse_message_response(response: str, group: CommitGroup) -> Optional[PlannedCommit]:
    """Parse LLM response into a PlannedCommit."""
    text = response.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        else:
            return None

    if not isinstance(data, dict):
        return None

    return PlannedCommit(
        id=group.group_id,
        type=data.get("type", group.category),
        scope=data.get("scope"),
        title=data.get("title", group.theme),
        bullets=data.get("bullets", []),
        hunks=list(group.hunk_ids),
    )


def _fallback_commit(group: CommitGroup) -> PlannedCommit:
    """Create a fallback commit when LLM call fails."""
    return PlannedCommit(
        id=group.group_id,
        type=group.category or "chore",
        title=group.theme or "Changes",
        bullets=[],
        hunks=list(group.hunk_ids),
    )
