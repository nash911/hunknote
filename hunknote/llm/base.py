"""Base classes and shared utilities for LLM providers."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from hunknote.formatters import CommitMessageJSON
from hunknote.styles import ExtendedCommitJSON, BlueprintSection


class LLMError(Exception):
    """Base exception for LLM-related errors."""

    pass


class MissingAPIKeyError(LLMError):
    """Raised when the required API key is not set."""

    pass


class JSONParseError(LLMError):
    """Raised when the LLM response cannot be parsed as valid JSON."""

    pass


@dataclass
class LLMResult:
    """Result from an LLM generation call, including token usage."""

    commit_json: ExtendedCommitJSON  # Changed from CommitMessageJSON to ExtendedCommitJSON
    model: str
    input_tokens: int
    output_tokens: int
    raw_response: str = ""  # Raw LLM response for debugging
    # Character counts for debugging
    input_chars: int = 0  # Characters in context bundle
    prompt_chars: int = 0  # Characters in full prompt (system + user)
    output_chars: int = 0  # Characters in LLM response


@dataclass
class RawLLMResult:
    """Result from a raw LLM call (no JSON parsing)."""

    raw_response: str
    model: str
    input_tokens: int
    output_tokens: int


# System prompt for the LLM (shared across all providers)
SYSTEM_PROMPT = """You are an expert software engineer writing git commit messages.
Be precise: only describe changes actually shown in the diff.
The [FILE_CHANGES] section tells you which files are NEW vs MODIFIED - use this to write accurate descriptions.

INTENT HANDLING:
- If an [INTENT] section exists, use it as the primary source for WHY/motivation framing.
- The intent guides the narrative but does not override technical facts from the diff.
- Do not invent technical details not present in the diff - intent can guide framing, not fabricate code changes.
- If intent contradicts the diff, prefer the diff and produce a neutral message."""

# User prompt template for default style (backward compatible)
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

# User prompt template for Conventional Commits style
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

# User prompt template for Ticket-prefixed style
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

# User prompt template for Linux Kernel style
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

# User prompt template for Blueprint style (structured sections)
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
- chore: Maintenance, tooling

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

# Backward compatibility: generic styled template (uses conventional as default)
USER_PROMPT_TEMPLATE_STYLED = USER_PROMPT_TEMPLATE_CONVENTIONAL


def parse_json_response(raw_response: str) -> dict:
    """Parse the LLM response as JSON.

    Args:
        raw_response: The raw text response from the LLM.

    Returns:
        The parsed JSON as a dictionary.

    Raises:
        JSONParseError: If parsing fails.
    """
    # Clean up the response - remove any markdown fences if present
    cleaned = raw_response.strip()

    # Remove markdown code fences if the model included them despite instructions
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line (```json or ```)
        lines = lines[1:]
        # Remove last line if it's ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    # Try to extract JSON object if there's extra content
    # Find the first { and last }
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        cleaned = cleaned[first_brace:last_brace + 1]

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise JSONParseError(
            f"Failed to parse LLM response as JSON.\n"
            f"Error: {e}\n"
            f"Raw response:\n{raw_response}"
        )


def validate_commit_json(parsed: dict, raw_response: str) -> ExtendedCommitJSON:
    """Validate parsed JSON against the ExtendedCommitJSON schema.

    This validates the LLM response and converts it to ExtendedCommitJSON,
    which supports all style formats (default, blueprint, conventional, ticket, kernel).

    Args:
        parsed: The parsed JSON dictionary.
        raw_response: The original raw response (for error messages).

    Returns:
        A validated ExtendedCommitJSON object.

    Raises:
        JSONParseError: If validation fails.
    """
    try:
        # Normalize the parsed data to handle different style formats
        normalized = _normalize_commit_json(parsed)
        return ExtendedCommitJSON(**normalized)
    except Exception as e:
        raise JSONParseError(
            f"LLM response does not match expected schema.\n"
            f"Error: {e}\n"
            f"Parsed JSON: {parsed}"
        )


def _normalize_commit_json(parsed: dict) -> dict:
    """Normalize parsed JSON to handle different style formats.

    Different styles use different field names:
    - default: title, body_bullets
    - blueprint: type, scope, title, summary, sections
    - conventional: type, scope, subject, body_bullets, breaking_change, footers
    - ticket: ticket, subject, scope, body_bullets
    - kernel: subsystem (mapped to scope), subject, body_bullets

    Args:
        parsed: The raw parsed JSON dictionary.

    Returns:
        Normalized dictionary compatible with ExtendedCommitJSON.
    """
    result = dict(parsed)  # Copy to avoid modifying original

    # Handle kernel style: subsystem -> scope
    if "subsystem" in result and "scope" not in result:
        result["scope"] = result.pop("subsystem")

    # Ensure we have either title or subject
    # If only subject is provided, also set title for backward compatibility
    if "subject" in result and "title" not in result:
        result["title"] = result["subject"]
    elif "title" in result and "subject" not in result:
        result["subject"] = result["title"]

    # Ensure body_bullets exists (may be empty for blueprint style)
    if "body_bullets" not in result:
        result["body_bullets"] = []

    # Handle sections for blueprint style - convert dicts to BlueprintSection
    if "sections" in result:
        sections = []
        for section in result["sections"]:
            if isinstance(section, dict):
                sections.append(section)
            else:
                sections.append(section)
        result["sections"] = sections

    return result


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def generate(self, context_bundle: str) -> LLMResult:
        """Generate a commit message from the git context bundle.

        Args:
            context_bundle: The formatted git context string.

        Returns:
            An LLMResult containing the commit message and metadata.

        Raises:
            MissingAPIKeyError: If the API key is not set.
            JSONParseError: If the response cannot be parsed.
            LLMError: For other LLM-related errors.
        """
        pass

    def generate_raw(
        self, system_prompt: str, user_prompt: str
    ) -> RawLLMResult:
        """Generate a raw LLM response without JSON parsing.

        This is used for compose and other features that need custom prompts.
        Default implementation raises NotImplementedError; providers can override.

        Args:
            system_prompt: The system prompt to use.
            user_prompt: The user prompt to use.

        Returns:
            A RawLLMResult containing the raw response and token usage.

        Raises:
            MissingAPIKeyError: If the API key is not set.
            LLMError: For other LLM-related errors.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support generate_raw. "
            "This provider cannot be used for compose."
        )

    @abstractmethod
    def get_api_key(self) -> str:
        """Get the API key from environment or credentials file.

        Checks in order:
        1. Environment variable
        2. ~/.hunknote/credentials file
        3. Repo-level .env file (if loaded)

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If the API key is not found.
        """
        pass

    def _get_api_key_with_fallback(self, env_var_name: str, provider_name: str) -> str:
        """Helper to get API key with fallback to credentials file.

        Args:
            env_var_name: Environment variable name to check.
            provider_name: Human-readable provider name for error messages.

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If the API key is not found.
        """
        import os

        # First check environment variable
        api_key = os.getenv(env_var_name)
        if api_key:
            return api_key

        # Then check credentials file
        try:
            from hunknote.global_config import get_credential
            api_key = get_credential(env_var_name)
            if api_key:
                return api_key
        except Exception:
            # If global_config isn't available, continue to error
            pass

        # Not found anywhere
        raise MissingAPIKeyError(
            f"{provider_name} API key not found. Set it using:\n"
            f"  1. Environment variable: export {env_var_name}=your_key_here\n"
            f"  2. Run: hunknote config set-key {provider_name.lower()}\n"
            f"  3. Manually add to ~/.hunknote/credentials"
        )

    def build_user_prompt(self, context_bundle: str) -> str:
        """Build the user prompt from the context bundle (default style).

        Args:
            context_bundle: The git context string.

        Returns:
            The formatted user prompt.
        """
        return USER_PROMPT_TEMPLATE_DEFAULT.format(context_bundle=context_bundle)

    def build_user_prompt_styled(self, context_bundle: str) -> str:
        """Build the extended user prompt for style profiles (conventional as default).

        Args:
            context_bundle: The git context string.

        Returns:
            The formatted user prompt with extended schema instructions.
        """
        return USER_PROMPT_TEMPLATE_CONVENTIONAL.format(context_bundle=context_bundle)

    def build_user_prompt_for_style(self, context_bundle: str, style: str) -> str:
        """Build the user prompt for a specific style profile.

        Args:
            context_bundle: The git context string.
            style: The style profile name (default, blueprint, conventional, ticket, kernel).

        Returns:
            The formatted user prompt for the specified style.
        """
        style_lower = style.lower() if style else "default"

        if style_lower == "blueprint":
            return USER_PROMPT_TEMPLATE_BLUEPRINT.format(context_bundle=context_bundle)
        elif style_lower == "conventional":
            return USER_PROMPT_TEMPLATE_CONVENTIONAL.format(context_bundle=context_bundle)
        elif style_lower == "ticket":
            return USER_PROMPT_TEMPLATE_TICKET.format(context_bundle=context_bundle)
        elif style_lower == "kernel":
            return USER_PROMPT_TEMPLATE_KERNEL.format(context_bundle=context_bundle)
        else:  # default
            return USER_PROMPT_TEMPLATE_DEFAULT.format(context_bundle=context_bundle)

