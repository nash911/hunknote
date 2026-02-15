"""Base classes and shared utilities for LLM providers."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from hunknote.formatters import CommitMessageJSON


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

    commit_json: CommitMessageJSON
    model: str
    input_tokens: int
    output_tokens: int


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
- Choose "type" based on the nature of changes:
  * feat: new feature or capability
  * fix: bug fix
  * docs: documentation only changes
  * refactor: code change that neither fixes a bug nor adds a feature
  * perf: performance improvement
  * test: adding or updating tests
  * build: build system or external dependencies
  * ci: CI configuration files and scripts
  * chore: maintenance tasks, tooling
  * style: formatting, whitespace, semicolons (no logic change)
  * revert: reverting a previous commit
- "scope" should identify the component/module affected (can be null if unclear).
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


def validate_commit_json(parsed: dict, raw_response: str) -> CommitMessageJSON:
    """Validate parsed JSON against the CommitMessageJSON schema.

    Args:
        parsed: The parsed JSON dictionary.
        raw_response: The original raw response (for error messages).

    Returns:
        A validated CommitMessageJSON object.

    Raises:
        JSONParseError: If validation fails.
    """
    try:
        return CommitMessageJSON(**parsed)
    except Exception as e:
        raise JSONParseError(
            f"LLM response does not match expected schema.\n"
            f"Error: {e}\n"
            f"Parsed JSON: {parsed}"
        )


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
            style: The style profile name (default, conventional, ticket, kernel).

        Returns:
            The formatted user prompt for the specified style.
        """
        style_lower = style.lower() if style else "default"

        if style_lower == "conventional":
            return USER_PROMPT_TEMPLATE_CONVENTIONAL.format(context_bundle=context_bundle)
        elif style_lower == "ticket":
            return USER_PROMPT_TEMPLATE_TICKET.format(context_bundle=context_bundle)
        elif style_lower == "kernel":
            return USER_PROMPT_TEMPLATE_KERNEL.format(context_bundle=context_bundle)
        else:  # default
            return USER_PROMPT_TEMPLATE_DEFAULT.format(context_bundle=context_bundle)

