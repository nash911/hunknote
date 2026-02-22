"""LLM prompt templates for commit message generation.

This package contains all prompt templates for different commit message styles:
- system: The shared system prompt for all styles
- default: Simple title + body bullets format
- conventional: Conventional Commits format with type, scope, subject
- blueprint: Detailed format with sections (Changes, Implementation, Testing, etc.)
- ticket: Ticket-prefixed format for issue tracking
- kernel: Linux kernel style with subsystem prefix
"""

from hunknote.llm.prompts.system import SYSTEM_PROMPT
from hunknote.llm.prompts.default import (
    USER_PROMPT_TEMPLATE_DEFAULT,
    USER_PROMPT_TEMPLATE,  # Backward compatibility alias
)
from hunknote.llm.prompts.conventional import (
    USER_PROMPT_TEMPLATE_CONVENTIONAL,
    USER_PROMPT_TEMPLATE_STYLED,  # Backward compatibility alias
)
from hunknote.llm.prompts.blueprint import USER_PROMPT_TEMPLATE_BLUEPRINT
from hunknote.llm.prompts.ticket import USER_PROMPT_TEMPLATE_TICKET
from hunknote.llm.prompts.kernel import USER_PROMPT_TEMPLATE_KERNEL


__all__ = [
    # System prompt
    "SYSTEM_PROMPT",
    # Style-specific prompts
    "USER_PROMPT_TEMPLATE_DEFAULT",
    "USER_PROMPT_TEMPLATE_CONVENTIONAL",
    "USER_PROMPT_TEMPLATE_BLUEPRINT",
    "USER_PROMPT_TEMPLATE_TICKET",
    "USER_PROMPT_TEMPLATE_KERNEL",
    # Backward compatibility aliases
    "USER_PROMPT_TEMPLATE",
    "USER_PROMPT_TEMPLATE_STYLED",
]

