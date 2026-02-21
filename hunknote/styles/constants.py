"""Constants for hunknote styles module.

Contains:
- CONVENTIONAL_TYPES: Valid conventional commit types
- BLUEPRINT_SECTION_TITLES: Allowed section titles for blueprint style
- PROFILE_DESCRIPTIONS: Descriptions for each style profile (for help/display)
"""

from enum import Enum


class StyleProfile(Enum):
    """Available commit style profiles."""

    DEFAULT = "default"
    BLUEPRINT = "blueprint"
    CONVENTIONAL = "conventional"
    TICKET = "ticket"
    KERNEL = "kernel"


# Valid conventional commit types
CONVENTIONAL_TYPES = [
    "feat",
    "fix",
    "docs",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "style",
    "revert",
    "merge",
]

# Allowed section titles for blueprint style (in preferred order)
BLUEPRINT_SECTION_TITLES = [
    "Changes",
    "Implementation",
    "Testing",
    "Documentation",
    "Notes",
    "Performance",
    "Security",
    "Config",
    "API",
]


# Profile descriptions for help/display (ordered for style list display)
PROFILE_DESCRIPTIONS = {
    StyleProfile.DEFAULT: {
        "name": "default",
        "description": "Standard Hunknote format with title and bullet points",
        "format": "<Title>\n\n- <bullet>\n- <bullet>",
        "example": "Add user authentication feature\n\n- Implement login endpoint\n- Add session management",
    },
    StyleProfile.BLUEPRINT: {
        "name": "blueprint",
        "description": "Structured sections with summary (Changes, Implementation, Testing, etc.)",
        "format": "<type>(<scope>): <title>\n\n<summary paragraph>\n\nChanges:\n- <bullet>\n\nImplementation:\n- <bullet>",
        "example": "feat(auth): Add user authentication\n\nImplement secure user authentication with JWT tokens\nand session management for the API.\n\nChanges:\n- Add login and logout endpoints\n- Implement JWT token validation\n\nImplementation:\n- Create auth middleware\n- Add user session storage\n\nTesting:\n- Add unit tests for auth flow",
    },
    StyleProfile.CONVENTIONAL: {
        "name": "conventional",
        "description": "Conventional Commits format (type(scope): subject)",
        "format": "<type>(<scope>): <subject>\n\n- <bullet>\n\nBREAKING CHANGE: ...\nRefs: ...",
        "example": "feat(auth): Add user authentication\n\n- Implement login endpoint\n- Add session management\n\nRefs: PROJ-123",
    },
    StyleProfile.TICKET: {
        "name": "ticket",
        "description": "Ticket-prefixed format (PROJ-123 subject)",
        "format": "<KEY-123> <subject>\n\n- <bullet>",
        "example": "PROJ-123 Add user authentication\n\n- Implement login endpoint\n- Add session management",
    },
    StyleProfile.KERNEL: {
        "name": "kernel",
        "description": "Linux kernel style (subsystem: subject)",
        "format": "<subsystem>: <subject>\n\n- <bullet> (optional)",
        "example": "auth: Add user authentication\n\n- Implement login endpoint",
    },
}

