"""Linux kernel style renderer for hunknote.

Format:
    <subsystem>: <subject>

    <body> (optional)
"""

from typing import Optional

from hunknote.styles.models import ExtendedCommitJSON, StyleConfig
from hunknote.styles.renderers.base import sanitize_subject, strip_type_prefix, wrap_text


def render_kernel(
    data: ExtendedCommitJSON,
    config: StyleConfig,
    override_scope: Optional[str] = None,
) -> str:
    """Render commit message in Linux kernel style.

    Format:
        <subsystem>: <subject>

        <body> (optional)

    Args:
        data: The structured commit data.
        config: Style configuration.
        override_scope: Force a specific subsystem/scope.

    Returns:
        Formatted commit message.
    """
    scope = override_scope or data.get_scope()
    subject = data.get_subject()

    # Strip any existing type prefix from subject
    # (e.g., "feat: Add feature" -> "Add feature")
    subject = strip_type_prefix(subject, config.conventional_types)

    # Build header
    if scope and config.subsystem_from_scope:
        header_prefix = f"{scope}: "
        max_subject_len = config.wrap_width - len(header_prefix)
        subject = sanitize_subject(subject, max_subject_len)
        header = f"{header_prefix}{subject}"
    else:
        header = sanitize_subject(subject, config.wrap_width)

    parts = [header]

    # Kernel style often omits body, but allow via config
    if config.include_body:
        bullets = data.get_bullets(config.max_bullets)
        if bullets:
            bullet_lines = []
            for bullet in bullets:
                wrapped = wrap_text(
                    bullet,
                    width=config.wrap_width,
                    initial_indent="- ",
                    subsequent_indent="  ",
                )
                bullet_lines.append(wrapped)
            parts.append("")  # Blank line
            parts.extend(bullet_lines)

    return "\n".join(parts)

