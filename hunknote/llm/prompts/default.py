"""Default style prompt template for LLM commit message generation.

This is the simplest commit message format with just title and body bullets.
"""

USER_PROMPT_TEMPLATE_DEFAULT = """Given the following git context, produce a JSON object with exactly these keys:
- "title": string (imperative mood, <=72 chars)
- "body_bullets": array of 2-7 strings (each concise, describe what changed and why)

Rules:
- Output ONLY valid JSON. No markdown fences. No extra keys. No commentary.
- Title in imperative mood (e.g., "Add feature" not "Added feature").
- Only describe changes shown in the diff. Do not infer or assume other changes.
- [FILE_CHANGES] shows:
  * NEW files (created in this commit)
  * MODIFIED files (already existed)
  * DELETED files (removed in this commit)
  * RENAMED files (moved/renamed in this commit).
  Use these to write accurate descriptions.

GIT CONTEXT:
{context_bundle}"""

# Backward compatibility alias
USER_PROMPT_TEMPLATE = USER_PROMPT_TEMPLATE_DEFAULT

