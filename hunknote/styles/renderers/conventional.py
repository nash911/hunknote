"""Conventional Commits style renderer for hunknote.

Format:
    <type>(<scope>): <subject>

    - <bullet>
    - <bullet>

    BREAKING CHANGE: <description>
    Refs: <ticket>
"""

from typing import Optional

from hunknote.styles.models import ExtendedCommitJSON, StyleConfig
from hunknote.styles.renderers.base import sanitize_subject, strip_type_prefix, wrap_text


def render_conventional(
    data: ExtendedCommitJSON,
    config: StyleConfig,
    override_scope: Optional[str] = None,
    no_scope: bool = False,
) -> str:
    """Render commit message in Conventional Commits style.

    Format:
        <type>(<scope>): <subject>

        - <bullet>
        - <bullet>

        BREAKING CHANGE: <description>
        Refs: <ticket>

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
        # Fall back to closest match or 'chore'
        commit_type = "chore"

    # Determine scope
    scope = None
    if not no_scope:
        scope = override_scope or data.get_scope()

    # Build header
    subject = data.get_subject()

    # Strip any existing type prefix from subject (e.g., "feat: Add feature" -> "Add feature")
    # This prevents double type prefixes like "feat: feat: Add feature"
    subject = strip_type_prefix(subject, config.conventional_types)

    # Account for type, scope, colon, and space in max length
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

    # Add footers
    footers_to_add = []

    if data.breaking_change and config.breaking_footer:
        footers_to_add.append("BREAKING CHANGE: This commit introduces breaking changes")

    if data.footers:
        footers_to_add.extend(data.footers)

    if data.ticket and f"Refs: {data.ticket}" not in footers_to_add:
        footers_to_add.append(f"Refs: {data.ticket}")

    if footers_to_add:
        parts.append("")  # Blank line before footers
        parts.extend(footers_to_add)

    return "\n".join(parts)

