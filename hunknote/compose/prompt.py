"""Compose prompt utilities for hunknote compose module.

Contains:
- COMPOSE_SYSTEM_PROMPT: System prompt for compose planning
- build_compose_prompt: Build the user prompt for compose planning
- build_compose_retry_prompt: Build retry prompt when validation fails
"""

from hunknote.compose.models import FileDiff, ComposePlan
from hunknote.compose.inventory import format_inventory_for_llm


COMPOSE_SYSTEM_PROMPT = """You are an expert software engineer creating a clean commit stack from a set of changes.

Your task is to split the given changes (hunks) into logical, atomic commits following best practices:
- Each commit should be cohesive and focused on one logical change
- Separate features, refactors, tests, docs, and config changes
- Order commits logically (infrastructure before features, etc.)
- Do not split hunks from the same new file across commits
- Reference ONLY the hunk IDs provided in the inventory

Output ONLY valid JSON matching the required schema. No markdown fences or commentary."""


COMPOSE_RETRY_SYSTEM_PROMPT = """You are an expert software engineer fixing errors in a compose plan.

Your previous compose plan had validation errors. You must fix these errors by:
- Using ONLY valid hunk IDs from the provided inventory
- Ensuring each hunk appears in exactly ONE commit
- Following the exact format specified

CRITICAL: Pay close attention to the exact hunk IDs. Each hunk ID has the format H<number>_<hash>.
You MUST use the EXACT hunk IDs from the inventory - do not modify the numbers or hashes.

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


def build_compose_retry_prompt(
    file_diffs: list[FileDiff],
    previous_plan: ComposePlan,
    validation_errors: list[str],
    valid_hunk_ids: list[str],
    max_commits: int,
) -> str:
    """Build a retry prompt when the previous plan had validation errors.

    Args:
        file_diffs: Parsed file diffs with hunks
        previous_plan: The plan that failed validation
        validation_errors: List of validation error messages
        valid_hunk_ids: List of ALL valid hunk IDs from the inventory
        max_commits: Maximum number of commits

    Returns:
        Retry prompt string for the LLM
    """
    inventory_text = format_inventory_for_llm(file_diffs)

    # Format the errors clearly
    errors_text = "\n".join(f"  - {error}" for error in validation_errors)

    # Format the previous plan's commit structure (for context)
    previous_commits_text = []
    for commit in previous_plan.commits:
        hunks_str = ", ".join(commit.hunks[:5])
        if len(commit.hunks) > 5:
            hunks_str += f", ... ({len(commit.hunks)} total)"
        previous_commits_text.append(
            f"  {commit.id}: {commit.title}\n"
            f"      hunks: [{hunks_str}]"
        )
    previous_plan_text = "\n".join(previous_commits_text)

    # Format the valid hunk IDs list (grouped for readability)
    valid_ids_lines = []
    for i in range(0, len(valid_hunk_ids), 10):
        chunk = valid_hunk_ids[i:i+10]
        valid_ids_lines.append("  " + ", ".join(chunk))
    valid_ids_text = "\n".join(valid_ids_lines)

    prompt = f"""Your previous compose plan had validation errors. Please fix them.

[VALIDATION ERRORS]
{errors_text}

[YOUR PREVIOUS PLAN]
{previous_plan_text}

[VALID HUNK IDs - USE ONLY THESE EXACT IDs]
{valid_ids_text}

[FULL HUNK INVENTORY FOR REFERENCE]
{inventory_text}

[INSTRUCTIONS]
1. Fix ALL validation errors listed above
2. Use ONLY the exact hunk IDs from the valid list - do NOT modify them
3. Ensure each hunk ID appears in exactly ONE commit
4. Keep the same logical grouping as your previous plan where possible
5. Maximum {max_commits} commits

[COMMON MISTAKES TO AVOID]
- Using wrong hash suffix (e.g., H2_xxxxxx when correct is H2_yyyyyy)
- Using wrong numeric prefix (e.g., H12_xxxxxx when correct is H11_xxxxxx)
- Referencing a hunk in multiple commits
- Using hunk IDs that don't exist in the inventory

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
      "title": "<short description>",
      "bullets": ["<change 1>", "<change 2>"],
      "summary": null,
      "sections": null,
      "hunks": ["<exact_hunk_id_1>", "<exact_hunk_id_2>"]
    }}
  ]
}}

Output ONLY the corrected JSON object:"""

    return prompt
