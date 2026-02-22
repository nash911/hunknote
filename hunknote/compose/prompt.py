"""Compose prompt utilities for hunknote compose module.

Contains:
- COMPOSE_SYSTEM_PROMPT: System prompt for compose planning
- build_compose_prompt: Build the user prompt for compose planning
"""

from hunknote.compose.models import FileDiff
from hunknote.compose.inventory import format_inventory_for_llm


COMPOSE_SYSTEM_PROMPT = """You are an expert software engineer creating a clean commit stack from a set of changes.

Your task is to split the given changes (hunks) into logical, atomic commits following best practices:
- Each commit should be cohesive and focused on one logical change
- Separate features, refactors, tests, docs, and config changes
- Order commits logically (infrastructure before features, etc.)
- Do not split hunks from the same new file across commits
- Reference ONLY the hunk IDs provided in the inventory

Output ONLY valid JSON matching the required schema. No markdown fences or commentary."""


def build_compose_prompt(
    file_diffs: list[FileDiff],
    branch: str,
    recent_commits: list[str],
    style: str,
    max_commits: int,
) -> str:
    """Build the user prompt for compose planning.

    Args:
        file_diffs: Parsed file diffs with hunks
        branch: Current branch name
        recent_commits: Last N commit subjects
        style: Style profile name
        max_commits: Maximum number of commits

    Returns:
        User prompt string
    """
    inventory_text = format_inventory_for_llm(file_diffs)

    # Count stats
    total_files = len([f for f in file_diffs if not f.is_binary])
    total_hunks = sum(len(f.hunks) for f in file_diffs)

    prompt = f"""Split the following changes into a clean commit stack.

[CONTEXT]
Branch: {branch}
Recent commits: {', '.join(recent_commits[:5]) if recent_commits else 'None'}
Style: {style}
Max commits: {max_commits}

[STATS]
Files with changes: {total_files}
Total hunks: {total_hunks}

{inventory_text}

[OUTPUT SCHEMA]
Return a JSON object with this exact structure:
{{
  "version": "1",
  "warnings": [],
  "commits": [
    {{
      "id": "C1",
      "type": "<feat|fix|docs|refactor|test|chore|build|ci|perf|style>",
      "scope": "<optional scope>",
      "ticket": null,
      "title": "<short description in imperative mood, max 72 chars, WITHOUT type/scope prefix>",
      "bullets": ["<change 1>", "<change 2>"],
      "summary": null,
      "sections": null,
      "hunks": ["<hunk_id_1>", "<hunk_id_2>"]
    }}
  ]
}}

IMPORTANT: The "title" field must contain ONLY the description, NOT the conventional commit prefix.
The type and scope are already separate JSON fields — do NOT repeat them inside the title.
  Correct:   "type": "feat", "scope": "api", "title": "Add pagination support to list endpoints"
  WRONG:     "type": "feat", "scope": "api", "title": "feat(api): Add pagination support to list endpoints"

  Correct:   "type": "fix", "title": "Prevent null pointer on empty input"
  WRONG:     "type": "fix", "title": "fix: Prevent null pointer on empty input"

  Correct:   "type": "refactor", "scope": "cache", "title": "Replace dict lookup with constant-time set"
  WRONG:     "type": "refactor", "scope": "cache", "title": "refactor(cache): Replace dict lookup with constant-time set"

[RULES]
1. Reference ONLY hunk IDs from the inventory above
2. Each hunk must appear in exactly ONE commit
3. Maximum {max_commits} commits
4. Keep new file hunks together in one commit
5. Order: infrastructure → features → tests → docs
6. Use appropriate commit type based on changes

Output ONLY the JSON object:"""

    return prompt

