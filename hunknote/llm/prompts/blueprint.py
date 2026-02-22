"""Blueprint style prompt template for LLM commit message generation.

This is the most detailed style with type, scope, title, summary,
and structured sections (Changes, Implementation, Testing, Documentation, Notes).
"""

USER_PROMPT_TEMPLATE_BLUEPRINT = """Analyze the git diff and produce a detailed, high-quality commit message as a JSON object.

OUTPUT SCHEMA:
{{
  "type": "feat|fix|docs|refactor|perf|test|build|ci|chore|style|revert|merge",
  "scope": "string or null (the affected component/module)",
  "title": "string (imperative, <=60 chars, no period)",
  "summary": "string (2-4 sentences)",
  "sections": [
    {{"title": "Changes|Implementation|Testing|Documentation|Notes", "bullets": ["..."]}}
  ]
}}

=== MERGE STATE CHECK (HIGHEST PRIORITY) ===

FIRST, check the [MERGE_STATE] section:
- If it says "MERGE IN PROGRESS" → type MUST be "merge"
- If it says "MERGE CONFLICT" → type MUST be "merge"
  (For merge conflicts that are resolved and staged, use type="merge")

When type="merge":
- Look for "Merging branch: <branch-name>" in [MERGE_STATE] to get the source branch
- Title format: "Merge branch <source-branch>" (e.g., "Merge branch feature-auth")
- If merging into a specific target, can use: "Merge <source-branch> into <target-branch>"
- Use the ACTUAL branch name from [MERGE_STATE], not the current branch from [BRANCH]
- Summary should explain what the merged branch introduces
- "Changes" section should list the key features/fixes being merged
- Scope can indicate the primary area affected by the merge, or set to null

=== TYPE SELECTION - ABSOLUTE RULES (FILE EXTENSION DETERMINES TYPE) ===

STEP 1: Look at [FILE_CHANGES] section and list ALL file extensions being changed.

STEP 2: Apply these ABSOLUTE rules based on file extensions:

Rule A: If ALL changed files are .md/.rst/.txt files → type MUST be "docs"
        (Even if the docs describe features, fixes, or tests - it's still "docs")

Rule B: If ALL changed files are test files → type MUST be "test"
        (Test files = tests/, *_test.py, test_*.py, *.spec.ts, etc.)

Rule C: If ALL changed files are CI files → type MUST be "ci"
        (CI files = .github/, .gitlab-ci.yml, .circleci/, Jenkinsfile, etc.)

Rule D: If ANY .py/.js/.ts/.go/.rs/.java code file is changed → type is feat/fix/refactor
        (NEVER use "docs" for code files, even if they contain text/prompts)

CRITICAL: The type is determined by WHAT FILES are changed, NOT by what the content describes.
- Documentation that describes new features → type is "docs" (not "feat")
- Documentation that describes bug fixes → type is "docs" (not "fix")
- Code that improves behavior → type is "fix" or "feat" (not "docs")

Type definitions (use only after merge check and file-based rules):
- merge: ONLY when [MERGE_STATE] indicates merge in progress or conflict resolution
- feat: New feature or capability (only for code changes)
- fix: Bug fix or behavior improvement (only for code changes)
- docs: Documentation files only (.md, .rst, README, docs/)
- refactor: Code restructuring with no behavior change
- perf: Performance improvement
- test: Test files only
- build: Build system or dependencies
- ci: CI/CD configuration files
- chore: Maintenance, cleanup, lint warning fixes, tooling, non-user-facing changes

FIX vs REFACTOR (for code changes only):
- "fix" = change improves/corrects behavior
- "refactor" = behavior stays exactly the same, only internal structure changes

SCOPE RULES:
Determine the primary component, module, or subsystem affected by analyzing the actual code changes.
- Focus on WHAT the changes accomplish functionally, not just the file locations
- Good scopes: "auth", "api", "cache", "cli", "config", "core", "db", "parser", "ui", "llm"
- AVOID REDUNDANT SCOPE: If scope would just repeat or be synonymous with the type, set scope to null:
  * type="test" with scope="tests" or scope="testing" → set scope to null
  * type="docs" with scope="docs" or scope="documentation" → set scope to null
  * type="ci" with scope="ci" or scope="pipeline" → set scope to null
  * type="build" with scope="build" or scope="deps" → set scope to null
- If changes affect multiple areas, choose the most significant one as the scope
- Set scope to null if changes are truly generic with no identifiable focus

TITLE: Write a clear, specific title that captures the essence of the change. Use imperative mood ("Add", "Fix", "Update", not "Added", "Fixed", "Updated").

SUMMARY: Write 2-4 sentences that explain:
- WHAT problem this change addresses or what it accomplishes
- WHY this change was needed (the motivation)
- The high-level approach taken

SECTIONS - Include ALL that apply based on files changed:

"Changes" (ALWAYS include):
- What user-visible behavior changed
- What was added, removed, or modified from a user perspective
- Be specific: name the features, options, or behaviors affected

"Implementation" (include if .py/.js/.ts/code files modified):
- Key code changes: functions/classes added or modified
- Architecture decisions or patterns used
- Important logic changes or edge cases handled
- Reference specific modules or files when relevant

"Testing" (REQUIRED if test files modified):
- What tests were added or updated
- What functionality the tests cover
- Test count changes if significant

"Documentation" (REQUIRED if README.md, docs/, or .md files modified):
- What documentation was added or updated
- What was clarified or expanded

"Notes" (include when relevant):
- Breaking changes or migration considerations
- Configuration changes users need to know
- Follow-up work or known limitations
- Compatibility notes

QUALITY GUIDELINES:
1. Each bullet should be specific and informative, not generic
2. BAD: "Update the code" / "Fix the bug" / "Add changes"
3. GOOD: "Add strip_type_prefix() function to remove duplicate type prefixes" / "Fix double 'feat:' prefix when title already contains type"
4. Reference actual function names, file names, or features from the diff
5. Each section should have 2-5 substantive bullets
6. Avoid repeating the same information across sections

Output ONLY valid JSON. No markdown fences. No commentary.

GIT CONTEXT:
{context_bundle}"""

