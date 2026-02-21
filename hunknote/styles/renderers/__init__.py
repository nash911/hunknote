"""Renderers package for hunknote styles.

Re-exports all renderer functions and the main render_commit_message_styled function.
"""

from typing import Optional

from hunknote.styles.constants import StyleProfile
from hunknote.styles.models import ExtendedCommitJSON, StyleConfig
from hunknote.styles.renderers.base import sanitize_subject, strip_type_prefix, wrap_text
from hunknote.styles.renderers.blueprint import render_blueprint
from hunknote.styles.renderers.conventional import render_conventional
from hunknote.styles.renderers.default import render_default
from hunknote.styles.renderers.kernel import render_kernel
from hunknote.styles.renderers.ticket import render_ticket


def render_commit_message_styled(
    data: ExtendedCommitJSON,
    config: StyleConfig,
    override_style: Optional[StyleProfile] = None,
    override_scope: Optional[str] = None,
    override_ticket: Optional[str] = None,
    no_scope: bool = False,
) -> str:
    """Render commit message using the specified style profile.

    Args:
        data: The structured commit data.
        config: Style configuration.
        override_style: Override the profile from config.
        override_scope: Force a specific scope.
        override_ticket: Force a specific ticket.
        no_scope: Disable scope even if provided.

    Returns:
        Formatted commit message string.
    """
    profile = override_style or config.profile

    if profile == StyleProfile.BLUEPRINT:
        return render_blueprint(data, config, override_scope, no_scope)
    elif profile == StyleProfile.CONVENTIONAL:
        return render_conventional(data, config, override_scope, no_scope)
    elif profile == StyleProfile.TICKET:
        return render_ticket(data, config, override_ticket, override_scope)
    elif profile == StyleProfile.KERNEL:
        return render_kernel(data, config, override_scope)
    else:  # DEFAULT
        return render_default(data, config)


__all__ = [
    # Main function
    "render_commit_message_styled",
    # Individual renderers
    "render_default",
    "render_conventional",
    "render_blueprint",
    "render_ticket",
    "render_kernel",
    # Utilities
    "wrap_text",
    "sanitize_subject",
    "strip_type_prefix",
]

