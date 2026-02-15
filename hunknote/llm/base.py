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


# System prompt for the LLM (shared across all providers)
SYSTEM_PROMPT = """You are an expert software engineer writing git commit messages.
Be precise: only describe changes actually shown in the diff.
The [FILE_CHANGES] section tells you which files are NEW vs MODIFIED - use this to write accurate descriptions."""

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
- "type": string (REQUIRED, one of: feat, fix, docs, refactor, perf, test, build, ci, chore, style, revert)
- "scope": string or null (the area of code affected, e.g., api, ui, auth, core)
- "subject": string (imperative mood, concise summary, <=60 chars, no period at end)
- "body_bullets": array of 2-7 strings (each concise, describe what changed and why)
- "breaking_change": boolean (true if this introduces breaking changes)
- "footers": array of strings (optional footer lines like "Refs: PROJ-123", "Co-authored-by: ...")

Rules:
- Output ONLY valid JSON. No markdown fences. No extra keys. No commentary.
- Subject in imperative mood (e.g., "Add feature" not "Added feature").

TYPE SELECTION - CRITICAL: Look at FILE EXTENSIONS first, then decide type:
- If ANY .py/.js/.ts/.go/.rs/.java file is modified → type is feat/fix/refactor/perf (NEVER docs)
- "docs" ONLY when ALL changed files are .md/.rst/.txt documentation files
- "test" ONLY when ALL changed files are in tests/ or named *_test.py/test_*.py

Type definitions:
  * feat: new feature or capability
  * fix: bug fix, correction, OR improving existing behavior to work better/correctly
  * docs: ONLY standalone doc files (.md, .rst) - NEVER for .py files regardless of content
  * refactor: ONLY internal code restructuring with NO behavior change (same inputs → same outputs)
  * perf: performance improvement
  * test: ONLY test files
  * build: build system or dependencies
  * ci: CI config files (.github/, .gitlab-ci.yml)
  * chore: maintenance, tooling
  * style: formatting only (no logic change)
  * revert: reverting a commit

FIX vs REFACTOR - choose carefully:
- "fix" = change improves/corrects behavior, fixes a problem, or makes something work better
- "refactor" = ONLY when behavior stays exactly the same, just internal code structure changes
- If the change makes the code behave differently or better → use "fix", NOT "refactor"
- If changing prompts/templates to improve output quality → use "fix" (behavior is improved)

IMPORTANT: A .py file containing prompts/text/instructions is CODE, not documentation. Use fix/feat/refactor.

- "scope" should identify the component/module affected.
- AVOID REDUNDANT SCOPE: If scope would just repeat the type, set scope to null:
  * type="test" with scope="tests" → set scope to null (redundant)
  * type="docs" with scope="docs" or scope="documentation" → set scope to null
  * type="ci" with scope="ci" → set scope to null
  * type="build" with scope="build" or scope="deps" → set scope to null
- Only describe changes shown in the diff. Do not infer or assume other changes.
- [FILE_CHANGES] shows:
  * NEW files (created in this commit)
  * MODIFIED files (already existed)
  * DELETED files (removed in this commit)
  * RENAMED files (moved/renamed in this commit).
  Use these to write accurate descriptions.

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
  "type": "feat|fix|docs|refactor|perf|test|build|ci|chore|style|revert",
  "scope": "string or null (the affected component/module)",
  "title": "string (imperative, <=60 chars, no period)",
  "summary": "string (2-4 sentences)",
  "sections": [
    {{"title": "Changes|Implementation|Testing|Documentation|Notes", "bullets": ["..."]}}
  ]
}}

TYPE SELECTION - CRITICAL: Look at FILE EXTENSIONS in [FILE_CHANGES] first:
- If ANY .py/.js/.ts/.go/.rs/.java file is modified → type is feat/fix/refactor/perf (NEVER "docs")
- "docs" ONLY when ALL changed files are .md/.rst/.txt documentation files
- "test" ONLY when ALL changed files are in tests/ or named *_test.py/test_*.py

Type definitions:
- feat: New feature or capability for users
- fix: Bug fix, error correction, OR improving existing behavior to work better/correctly
- docs: ONLY standalone doc files (.md, .rst) - NEVER use for .py files regardless of their content
- refactor: ONLY internal code restructuring with NO behavior change (same inputs → same outputs)
- perf: Performance improvement
- test: ONLY test files
- build: Build system or dependencies
- ci: CI/CD configuration files (.github/, .gitlab-ci.yml)
- chore: Maintenance, tooling, or other non-user-facing changes

FIX vs REFACTOR - choose carefully:
- "fix" = change improves/corrects behavior, fixes a problem, or makes something work better
- "refactor" = ONLY when behavior stays exactly the same, just internal code structure changes
- If the change makes the code behave differently or better → use "fix", NOT "refactor"
- If changing prompts/templates to improve output quality → use "fix" (output behavior is improved)

IMPORTANT: A .py file containing prompts, instructions, or text strings is CODE, not documentation.
If you see base.py, cli.py, or any .py file in the diff → use fix/feat/refactor, NEVER "docs".

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

