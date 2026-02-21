"""Blueprint style renderer for hunknote.

Format:
    <type>(<scope>): <title>

    <summary paragraph wrapped to wrap_width>

    <Section Title>:
    - bullet
    - bullet
"""

from typing import Optional

from hunknote.styles.models import ExtendedCommitJSON, StyleConfig
from hunknote.styles.renderers.base import sanitize_subject, strip_type_prefix, wrap_text


def render_blueprint(
    data: ExtendedCommitJSON,
    config: StyleConfig,
    override_scope: Optional[str] = None,
    no_scope: bool = False,
) -> str:
    """Render commit message in blueprint style.

    Format:
        <type>(<scope>): <title>

        <summary paragraph wrapped to wrap_width>

        <Section Title>:
        - bullet
        - bullet

    Args:
        data: The structured commit data.
        config: Style configuration.
        override_scope: Force a specific scope.
        no_scope: Disable scope even if provided.

    Returns:
        Formatted commit message.
    """
    commit_type = data.get_type("feat")

    # Validate type
    if commit_type not in config.conventional_types:
        commit_type = "chore"

    # Determine scope
    scope = None
    if not no_scope:
        scope = override_scope or data.get_scope()

    # Build header (conventional format)
    subject = data.get_subject()

    # Strip any existing type prefix from subject (e.g., "feat: Add feature" -> "Add feature")
    # This prevents double type prefixes like "feat: feat: Add feature"
    subject = strip_type_prefix(subject, config.conventional_types)

    header_prefix_len = len(commit_type) + 2  # "type: "
    if scope:
        header_prefix_len += len(scope) + 2  # "(scope)"

    max_subject_len = config.wrap_width - header_prefix_len
    subject = sanitize_subject(subject, max_subject_len)

    if scope:
        header = f"{commit_type}({scope}): {subject}"
    else:
        header = f"{commit_type}: {subject}"

    parts = [header]

    # Add summary paragraph
    summary = data.get_summary()
    if summary:
        wrapped_summary = wrap_text(summary, width=config.wrap_width)
        parts.append("")  # Blank line after header
        parts.append(wrapped_summary)

    # Add sections
    sections = data.get_sections(config.blueprint_section_titles)
    if sections:
        for section in sections:
            if section.bullets:
                parts.append("")  # Blank line before section
                parts.append(f"{section.title}:")
                for bullet in section.bullets:
                    wrapped = wrap_text(
                        bullet,
                        width=config.wrap_width,
                        initial_indent="- ",
                        subsequent_indent="  ",
                    )
                    parts.append(wrapped)

    # Fallback: if no sections but has body_bullets, render as "Changes" section
    if not sections and config.include_body:
        bullets = data.get_bullets(config.max_bullets)
        if bullets:
            parts.append("")
            parts.append("Changes:")
            for bullet in bullets:
                wrapped = wrap_text(
                    bullet,
                    width=config.wrap_width,
                    initial_indent="- ",
                    subsequent_indent="  ",
                )
                parts.append(wrapped)

    return "\n".join(parts)

