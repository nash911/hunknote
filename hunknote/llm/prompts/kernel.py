"""Linux Kernel style prompt template for LLM commit message generation.

This follows the Linux kernel commit message style with subsystem prefix
and lowercase subject line.
"""

USER_PROMPT_TEMPLATE_KERNEL = """Given the following git context, produce a JSON object for a Linux kernel-style commit message with these keys:
- "subsystem": string or null (the subsystem/component being changed, e.g., "net", "fs", "mm", "auth", "api")
- "subject": string (imperative mood, concise summary, <=60 chars, lowercase preferred)
- "body_bullets": array of 2-5 strings (each concise, describe what changed and why - kernel style often has fewer bullets)

Rules:
- Output ONLY valid JSON. No markdown fences. No extra keys. No commentary.
- Subject in imperative mood, typically lowercase (e.g., "add support for..." not "Add support for...").
- "subsystem" should be inferred from the path of changed files:
  * If files are in "auth/", subsystem might be "auth"
  * If files are in "api/", subsystem might be "api"
  * If unclear, set to null
- Kernel-style commits are typically concise with short subjects.
- Only describe changes shown in the diff. Do not infer or assume other changes.
- [FILE_CHANGES] shows:
  * NEW files (created in this commit)
  * MODIFIED files (already existed)
  * DELETED files (removed in this commit)
  * RENAMED files (moved/renamed in this commit).
  Use these to write accurate descriptions.

GIT CONTEXT:
{context_bundle}"""

