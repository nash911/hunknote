"""Ticket-prefixed style renderer for hunknote.
Format (prefix):
    <KEY-6767> <subject>
    - <bullet>
Format (prefix with scope):
    <KEY-6767> (<scope>) <subject>
Format (suffix):
    <subject> (<KEY-6767>)
"""
from typing import Optional
from hunknote.styles.models import ExtendedCommitJSON, StyleConfig
from hunknote.styles.renderers.base import sanitize_subject, wrap_text
def render_ticket(
    data: ExtendedCommitJSON,
    config: StyleConfig,
    override_ticket: Optional[str] = None,
    override_scope: Optional[str] = None,
) -> str:
    """Render commit message in ticket-first style.
    Format (prefix):
        <KEY-6767> <subject>
        - <bullet>
    Format (prefix with scope):
        <KEY-6767> (<scope>) <subject>
    Format (suffix):
        <subject> (<KEY-6767>)
    Args:
        data: The structured commit data.
        config: Style configuration.
        override_ticket: Force a specific ticket key.
        override_scope: Force a specific scope.
    Returns:
        Formatted commit message.
    """
    ticket = override_ticket or data.ticket
    scope = override_scope or data.get_scope()
    subject = data.get_subject()
    # Build header based on placement
    if ticket:
        if config.ticket_placement == "prefix":
            if scope:
                header_prefix = f"{ticket} ({scope}) "
            else:
                header_prefix = f"{ticket} "
            max_subject_len = config.wrap_width - len(header_prefix)
            subject = sanitize_subject(subject, max_subject_len)
            header = f"{header_prefix}{subject}"
        else:  # suffix
            suffix = f" ({ticket})"
            max_subject_len = config.wrap_width - len(suffix)
            subject = sanitize_subject(subject, max_subject_len)
            header = f"{subject}{suffix}"
    else:
        # No ticket, fall back to default-like format
        header = sanitize_subject(subject, config.wrap_width)
    parts = [header]
    # Add body bullets
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
