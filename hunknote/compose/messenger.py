"""Message generation for the Compose Agent (Messenger sub-agent).

Generates conventional commit messages for pre-grouped hunk sets.
Uses a simpler LLM prompt since grouping is already decided.
"""


from hunknote.compose.models import (
    CommitGroup,
    ComposePlan,
    FileDiff,
    HunkRef,
    PlannedCommit,
)


# Simplified system prompt for message-only generation
COMPOSE_MESSAGE_SYSTEM_PROMPT = """You are an expert software engineer writing commit messages for pre-grouped changes.

Each group of changes has already been determined to form a single atomic commit.
Your job is ONLY to write an accurate, concise conventional commit message for each group.

Rules:
- Use appropriate commit type (feat, fix, refactor, test, docs, chore, build, ci, perf, style)
- Keep titles under 72 characters, in imperative mood
- The "title" field must contain ONLY the description, NOT the type/scope prefix
- Bullets should describe specific changes
- Scope should reflect the primary module/area affected

Output ONLY valid JSON matching the required schema. No markdown fences or commentary."""


def build_message_prompt(
    groups: list[CommitGroup],
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
    style: str,
    branch: str = "",
    recent_commits: list[str] | None = None,
) -> str:
    """Build a prompt for generating commit messages for pre-grouped hunks.

    Args:
        groups: List of CommitGroup objects with assigned hunks.
        inventory: Dictionary mapping hunk ID to HunkRef.
        file_diffs: Parsed file diffs.
        style: Style profile name.
        branch: Current branch name.
        recent_commits: Recent commit subjects for context.

    Returns:
        User prompt string.
    """
    sections: list[str] = []

    sections.append(f"[CONTEXT]")
    if branch:
        sections.append(f"Branch: {branch}")
    if recent_commits:
        sections.append(f"Recent commits: {', '.join(recent_commits[:3])}")
    sections.append(f"Style: {style}")
    sections.append(f"Total commits to generate: {len(groups)}")
    sections.append("")

    sections.append("[COMMIT GROUPS]")
    sections.append("Each group below is a single atomic commit. Write a message for each.")
    sections.append("")

    for i, group in enumerate(groups, 1):
        sections.append(f"--- Commit C{i} ---")
        sections.append(f"Files: {', '.join(group.files)}")
        sections.append(f"Hunks: {', '.join(group.hunk_ids)}")
        sections.append("")

        # Include the actual diff content for each hunk
        for hunk_id in group.hunk_ids:
            hunk = inventory.get(hunk_id)
            if hunk:
                sections.append(f"  [{hunk_id}] {hunk.file_path}")
                # Show changed lines (compact)
                changed = [ln for ln in hunk.lines if ln.startswith(("+", "-"))
                           and not ln.startswith(("+++", "---"))]
                for ln in changed[:20]:
                    sections.append(f"    {ln}")
                if len(changed) > 20:
                    sections.append(f"    ... ({len(changed) - 20} more lines)")
                sections.append("")

    sections.append("[OUTPUT SCHEMA]")
    sections.append("""Return a JSON object with this exact structure:
{
  "version": "1",
  "warnings": [],
  "commits": [
    {
      "id": "C1",
      "type": "<feat|fix|docs|refactor|test|chore|build|ci|perf|style>",
      "scope": "<optional scope>",
      "ticket": null,
      "title": "<short description, imperative mood, max 72 chars, WITHOUT type/scope prefix>",
      "bullets": ["<change 1>", "<change 2>"],
      "summary": null,
      "sections": null,
      "hunks": ["<hunk_id_1>", "<hunk_id_2>"]
    }
  ]
}""")
    sections.append("")
    sections.append("IMPORTANT: Use the EXACT hunk IDs from each group above.")
    sections.append("The commit order must match the group order (C1, C2, C3, ...).")
    sections.append("")
    sections.append("Output ONLY the JSON object:")

    return "\n".join(sections)


def create_plan_from_groups(
    groups: list[CommitGroup],
    plan_data: dict | None = None,
) -> ComposePlan:
    """Create a ComposePlan from commit groups and optional LLM-generated messages.

    If plan_data is provided (from LLM), uses the messages. Otherwise,
    creates placeholder messages based on the group metadata.

    Args:
        groups: List of CommitGroup objects.
        plan_data: Optional parsed JSON from LLM response.

    Returns:
        ComposePlan with all hunks assigned.
    """
    if plan_data and "commits" in plan_data:
        return ComposePlan(**plan_data)

    # Fallback: create placeholder messages
    commits: list[PlannedCommit] = []
    for i, group in enumerate(groups, 1):
        # Infer type from files
        commit_type = _infer_commit_type(group)

        commits.append(PlannedCommit(
            id=f"C{i}",
            type=commit_type,
            scope=_infer_scope(group),
            title=f"Update {', '.join(group.files[:3])}",
            bullets=[f"Modify {f}" for f in group.files],
            hunks=group.hunk_ids,
        ))

    return ComposePlan(commits=commits)


def _infer_commit_type(group: CommitGroup) -> str:
    """Infer the conventional commit type from file paths."""
    files = group.files
    if all("test" in f.lower() for f in files):
        return "test"
    if all(f.endswith((".md", ".rst", ".txt")) for f in files):
        return "docs"
    if any(f.lower() in ("dockerfile", ".dockerignore", "docker-compose.yml",
                           "makefile", "cmakelists.txt", ".github",
                           "pyproject.toml", "package.json", "cargo.toml",
                           "go.mod") or ".github/" in f.lower()
           for f in files):
        return "build"
    return "feat"


def _infer_scope(group: CommitGroup) -> str:
    """Infer the scope from file paths."""
    if not group.files:
        return ""
    # Use the common directory
    parts = [f.split("/") for f in group.files]
    if len(parts) == 1:
        return parts[0][-1].split(".")[0] if parts[0] else ""
    # Find common prefix
    common = []
    for level in zip(*parts):
        if len(set(level)) == 1:
            common.append(level[0])
        else:
            break
    if common:
        return common[-1]
    return ""

