"""Commit style profiles and rendering for hunknote.

Supports multiple commit message formats:
- default: Title + bullet points (current Hunknote format)
- blueprint: Structured sections with summary (Changes, Implementation, Testing, etc.)
- conventional: Conventional Commits (type(scope): subject)
- ticket: Ticket-prefixed commits (PROJ-123 subject)
- kernel: Linux kernel style (subsystem: subject)

This package provides modular style handling with:
- constants: StyleProfile enum, CONVENTIONAL_TYPES, BLUEPRINT_SECTION_TITLES, PROFILE_DESCRIPTIONS
- models: StyleConfig, BlueprintSection, ExtendedCommitJSON
- renderers: Individual render functions for each style
- inference: extract_ticket_from_branch, infer_commit_type
- config: load_style_config_from_dict, style_config_to_dict
"""

# Constants
from hunknote.styles.constants import (
    BLUEPRINT_SECTION_TITLES,
    CONVENTIONAL_TYPES,
    PROFILE_DESCRIPTIONS,
    StyleProfile,
)

# Models
from hunknote.styles.models import (
    BlueprintSection,
    ExtendedCommitJSON,
    StyleConfig,
)

# Renderers
from hunknote.styles.renderers import (
    render_blueprint,
    render_commit_message_styled,
    render_conventional,
    render_default,
    render_kernel,
    render_ticket,
    sanitize_subject,
    strip_type_prefix,
    wrap_text,
)

# Inference utilities
from hunknote.styles.inference import (
    extract_ticket_from_branch,
    infer_commit_type,
)

# Configuration utilities
from hunknote.styles.config import (
    load_style_config_from_dict,
    style_config_to_dict,
)


__all__ = [
    # Constants
    "StyleProfile",
    "CONVENTIONAL_TYPES",
    "BLUEPRINT_SECTION_TITLES",
    "PROFILE_DESCRIPTIONS",
    # Models
    "StyleConfig",
    "BlueprintSection",
    "ExtendedCommitJSON",
    # Renderers
    "render_default",
    "render_conventional",
    "render_blueprint",
    "render_ticket",
    "render_kernel",
    "render_commit_message_styled",
    # Utilities
    "wrap_text",
    "sanitize_subject",
    "strip_type_prefix",
    # Inference
    "extract_ticket_from_branch",
    "infer_commit_type",
    # Configuration
    "load_style_config_from_dict",
    "style_config_to_dict",
]

