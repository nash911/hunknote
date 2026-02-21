"""Default style renderer for hunknote.

Format:
    <Title>

    - <bullet>
    - <bullet>
"""

from hunknote.styles.models import ExtendedCommitJSON, StyleConfig
from hunknote.styles.renderers.base import sanitize_subject, wrap_text


def render_default(data: ExtendedCommitJSON, config: StyleConfig) -> str:
    """Render commit message in default style.

    Format:
        <Title>

        - <bullet>
        - <bullet>

    Args:
        data: The structured commit data.
        config: Style configuration.

    Returns:
        Formatted commit message.
    """
    subject = sanitize_subject(data.get_subject(), config.wrap_width)
    bullets = data.get_bullets(config.max_bullets if config.include_body else 0)

    if not bullets or not config.include_body:
        return subject

    # Format bullets with wrapping
    bullet_lines = []
    for bullet in bullets:
        wrapped = wrap_text(
            bullet,
            width=config.wrap_width,
            initial_indent="- ",
            subsequent_indent="  ",
        )
        bullet_lines.append(wrapped)

    return f"{subject}\n\n" + "\n".join(bullet_lines)

