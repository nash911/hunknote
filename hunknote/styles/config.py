"""Configuration utilities for hunknote styles.

Contains functions for:
- Loading StyleConfig from a configuration dictionary
- Converting StyleConfig to a dictionary for saving
"""

from hunknote.styles.constants import (
    BLUEPRINT_SECTION_TITLES,
    CONVENTIONAL_TYPES,
    StyleProfile,
)
from hunknote.styles.models import StyleConfig


def load_style_config_from_dict(config_dict: dict) -> StyleConfig:
    """Load StyleConfig from a configuration dictionary.

    Args:
        config_dict: Dictionary with style configuration.

    Returns:
        StyleConfig instance.
    """
    style_section = config_dict.get("style", {})

    # Get profile
    profile_str = style_section.get("profile", "default")
    try:
        profile = StyleProfile(profile_str)
    except ValueError:
        profile = StyleProfile.DEFAULT

    # Get conventional config
    conv_section = style_section.get("conventional", {})
    conventional_types = conv_section.get("types", CONVENTIONAL_TYPES.copy())

    # Get ticket config
    ticket_section = style_section.get("ticket", {})

    # Get kernel config
    kernel_section = style_section.get("kernel", {})

    # Get blueprint config
    blueprint_section = style_section.get("blueprint", {})

    return StyleConfig(
        profile=profile,
        include_body=style_section.get("include_body", True),
        max_bullets=style_section.get("max_bullets", 6),
        wrap_width=style_section.get("wrap_width", 72),
        conventional_types=conventional_types,
        breaking_footer=conv_section.get("breaking_footer", True),
        ticket_key_regex=ticket_section.get("key_regex", r"([A-Z][A-Z0-9]+-\d+)"),
        ticket_placement=ticket_section.get("placement", "prefix"),
        subsystem_from_scope=kernel_section.get("subsystem_from_scope", True),
        blueprint_section_titles=blueprint_section.get("section_titles", BLUEPRINT_SECTION_TITLES.copy()),
    )


def style_config_to_dict(config: StyleConfig) -> dict:
    """Convert StyleConfig to a dictionary for saving.

    Args:
        config: StyleConfig instance.

    Returns:
        Dictionary representation.
    """
    return {
        "style": {
            "profile": config.profile.value,
            "include_body": config.include_body,
            "max_bullets": config.max_bullets,
            "wrap_width": config.wrap_width,
            "conventional": {
                "types": config.conventional_types,
                "breaking_footer": config.breaking_footer,
            },
            "ticket": {
                "key_regex": config.ticket_key_regex,
                "placement": config.ticket_placement,
            },
            "kernel": {
                "subsystem_from_scope": config.subsystem_from_scope,
            },
            "blueprint": {
                "section_titles": config.blueprint_section_titles,
            },
        }
    }

