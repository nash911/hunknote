"""Base classes and shared utilities for LLM providers.

This module has been refactored. Prompts have been moved to hunknote/llm/prompts/
and parsing functions to hunknote/llm/parsing.py.

This module now contains:
- Exception classes (imported from exceptions.py for backward compatibility)
- Result dataclasses (LLMResult, RawLLMResult)
- BaseLLMProvider abstract class
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from hunknote.styles import ExtendedCommitJSON

# Import exceptions from exceptions.py (for backward compatibility, re-export here)
from hunknote.llm.exceptions import (
    LLMError,
    MissingAPIKeyError,
    JSONParseError,
)

# Import prompts from prompts package (for backward compatibility, re-export here)
from hunknote.llm.prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE_DEFAULT,
    USER_PROMPT_TEMPLATE_CONVENTIONAL,
    USER_PROMPT_TEMPLATE_BLUEPRINT,
    USER_PROMPT_TEMPLATE_TICKET,
    USER_PROMPT_TEMPLATE_KERNEL,
    USER_PROMPT_TEMPLATE,  # Backward compatibility alias
    USER_PROMPT_TEMPLATE_STYLED,  # Backward compatibility alias
)

# Import parsing functions from parsing.py (for backward compatibility, re-export here)
from hunknote.llm.parsing import (
    parse_json_response,
    validate_commit_json,
    _normalize_commit_json,
)


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
        """Get the API key from system keychain or environment.

        Checks in order:
        1. System keychain (via keyring library)
        2. Environment variable / .env file

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If the API key is not found.
        """
        pass

    def _get_api_key_with_fallback(self, env_var_name: str, provider_name: str) -> str:
        """Helper to get API key with fallback to environment variable.

        Resolution order:
        1. System keychain (via keyring) — primary storage
        2. Environment variable / .env file — fallback/override

        Args:
            env_var_name: Environment variable name to check.
            provider_name: Human-readable provider name for error messages.

        Returns:
            The API key string.

        Raises:
            MissingAPIKeyError: If the API key is not found.
        """
        import os

        # First check system keychain (primary storage)
        try:
            from hunknote.global_config import get_credential
            api_key = get_credential(env_var_name)
            if api_key:
                return api_key
        except Exception:
            pass

        # Then check environment variable / .env fallback
        api_key = os.getenv(env_var_name)
        if api_key:
            return api_key

        # Not found anywhere
        raise MissingAPIKeyError(
            f"{provider_name} API key not found. Set it using:\n"
            f"  1. Run: hunknote config set-key {provider_name.lower()}\n"
            f"  2. Environment variable: export {env_var_name}=your_key_here"
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
