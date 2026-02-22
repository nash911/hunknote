"""Ticket-prefixed style prompt template for LLM commit message generation.

This style extracts ticket/issue IDs from branch names and includes them
in the commit message.
"""

USER_PROMPT_TEMPLATE_TICKET = """Given the following git context, produce a JSON object for a ticket-prefixed commit message with these keys:
- "ticket": string or null (ticket/issue key like PROJ-123, JIRA-456 - extract from branch name or context if present)
- "subject": string (imperative mood, concise summary, <=60 chars)
- "scope": string or null (optional area of code affected)
- "body_bullets": array of 2-7 strings (each concise, describe what changed and why)

Rules:
- Output ONLY valid JSON. No markdown fences. No extra keys. No commentary.
- Subject in imperative mood (e.g., "Add feature" not "Added feature").
- Look for ticket patterns like ABC-123, PROJ-456 in:
  * Branch name (e.g., feature/PROJ-123-add-login)
  * File changes or context
- If no ticket is found, set "ticket" to null.
- "scope" is optional - use it if the change is clearly in one area.
- AVOID REDUNDANT SCOPE: Do not use scope values that are too generic or that would repeat the change type:
  * If ALL changes are test files, do not use scope="tests"
  * If ALL changes are docs, do not use scope="docs"
- Only describe changes shown in the diff. Do not infer or assume other changes.
- [FILE_CHANGES] shows:
  * NEW files (created in this commit)
  * MODIFIED files (already existed)
  * DELETED files (removed in this commit)
  * RENAMED files (moved/renamed in this commit).
  Use these to write accurate descriptions.

GIT CONTEXT:
{context_bundle}"""

