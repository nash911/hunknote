"""Conventional Commits style prompt template for LLM commit message generation.

This follows the Conventional Commits specification with type, scope, subject,
body bullets, breaking change flag, and footers.
"""

USER_PROMPT_TEMPLATE_CONVENTIONAL = """Given the following git context, produce a JSON object for a Conventional Commits message with these keys:
- "type": string (REQUIRED, one of: feat, fix, docs, refactor, perf, test, build, ci, chore, style, revert, merge)
- "scope": string or null (the area of code affected, e.g., api, ui, auth, core)
- "subject": string (imperative mood, concise summary, <=60 chars, no period at end)
- "body_bullets": array of 2-7 strings (each concise, describe what changed and why)
- "breaking_change": boolean (true if this introduces breaking changes)
- "footers": array of strings (optional footer lines like "Refs: PROJ-123", "Co-authored-by: ...")

Rules:
- Output ONLY valid JSON. No markdown fences. No extra keys. No commentary.
- Subject in imperative mood (e.g., "Add feature" not "Added feature").

=== MERGE STATE CHECK (HIGHEST PRIORITY) ===

FIRST, check the [MERGE_STATE] section:
- If it says "MERGE IN PROGRESS" → type MUST be "merge"
- If it says "MERGE CONFLICT" → type MUST be "merge"
  (For merge conflicts that are resolved and staged, use type="merge")

When type="merge":
- Look for "Merging branch: <branch-name>" in [MERGE_STATE] to get the source branch
- Subject format: "Merge branch <source-branch>" (e.g., "Merge branch feature-auth")
- If merging into a specific target, can use: "Merge <source-branch> into <target-branch>"
- Use the ACTUAL branch name from [MERGE_STATE], not the current branch from [BRANCH]
- Body bullets should summarize the key changes being merged
- Scope can indicate the primary area affected by the merge, or set to null

=== TYPE SELECTION - ABSOLUTE RULES (FILE EXTENSION DETERMINES TYPE) ===

STEP 1: Look at [FILE_CHANGES] and identify ALL file extensions being changed.

STEP 2: Apply these ABSOLUTE rules:

Rule A: If ALL changed files are .md/.rst/.txt → type MUST be "docs"
        (Even if docs describe features/fixes - the type is still "docs")

Rule B: If ALL changed files are test files → type MUST be "test"

Rule C: If ALL changed files are CI files → type MUST be "ci"

Rule D: If ANY .py/.js/.ts/.go/.rs/.java code file is changed → type is feat/fix/refactor

CRITICAL: Type is determined by WHAT FILES changed, NOT by what the content describes.
- Documentation describing new features → type = "docs"
- Documentation describing bug fixes → type = "docs"
- Code that adds features → type = "feat"
- Code that fixes bugs → type = "fix"

Type definitions (apply after merge check and file-based rules):
  * merge: ONLY when [MERGE_STATE] indicates merge in progress or conflict resolution
  * docs: ONLY for .md/.rst/README files - use this when ALL files are documentation
  * test: ONLY for test files
  * ci: ONLY for CI config files
  * feat: new feature (code changes only)
  * fix: bug fix or behavior improvement (code changes only)
  * refactor: code restructuring with no behavior change
  * perf: performance improvement
  * build: build system or dependencies
  * chore: maintenance, tooling
  * style: formatting only

- "scope" should identify the component/module affected.
- AVOID REDUNDANT SCOPE: If scope would repeat the type, set scope to null:
  * type="docs" → scope should be null (not "docs" or "documentation")
  * type="test" → scope should be null (not "tests")
  * type="ci" → scope should be null (not "ci")
- Only describe changes shown in the diff.
- [FILE_CHANGES] shows NEW/MODIFIED/DELETED/RENAMED files.

GIT CONTEXT:
{context_bundle}"""

# Backward compatibility alias
USER_PROMPT_TEMPLATE_STYLED = USER_PROMPT_TEMPLATE_CONVENTIONAL

