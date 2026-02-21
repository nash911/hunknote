"""Data models for hunknote styles module.

Contains:
- StyleConfig: Configuration dataclass for commit style rendering
- BlueprintSection: Pydantic model for blueprint sections
- ExtendedCommitJSON: Pydantic model for structured commit message data
"""

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, field_validator

from hunknote.styles.constants import (
    BLUEPRINT_SECTION_TITLES,
    CONVENTIONAL_TYPES,
    StyleProfile,
)


@dataclass
class StyleConfig:
    """Configuration for commit style rendering."""

    profile: StyleProfile = StyleProfile.DEFAULT
    include_body: bool = True
    max_bullets: int = 6
    wrap_width: int = 72

    # Conventional commits config
    conventional_types: list[str] = field(
        default_factory=lambda: CONVENTIONAL_TYPES.copy())
    breaking_footer: bool = True

    # Ticket config
    ticket_key_regex: str = r"([A-Z][A-Z0-9]+-\d+)"
    ticket_placement: str = "prefix"  # prefix | suffix

    # Kernel config
    subsystem_from_scope: bool = True

    # Blueprint config
    blueprint_section_titles: list[str] = field(
        default_factory=lambda: BLUEPRINT_SECTION_TITLES.copy())


class BlueprintSection(BaseModel):
    """A section in a blueprint-style commit message.

    Attributes:
        title: Section title (e.g., "Changes", "Implementation").
        bullets: List of bullet points for this section.
    """

    title: str
    bullets: list[str] = []

    @field_validator("bullets", mode="before")
    @classmethod
    def ensure_bullets_list(cls, v):
        """Ensure bullets is a list."""
        if v is None:
            return []
        return v


class ExtendedCommitJSON(BaseModel):
    """Extended Pydantic model for structured commit message data.

    Supports both the original schema (title + body_bullets) and the
    extended schema with type, scope, subject for style profiles.

    Attributes:
        title: Legacy field - commit title (used if subject is not provided).
        body_bullets: List of bullet points describing changes.
        type: Conventional commit type (feat, fix, docs, etc.).
        scope: Scope of the change (api, ui, core, etc.).
        subject: The commit subject line (preferred over title).
        breaking_change: Whether this is a breaking change.
        footers: Additional footer lines (Refs, Co-authored-by, etc.).
        ticket: Ticket/issue key (e.g., PROJ-123).
        summary: Blueprint-style summary paragraph (1-3 sentences).
        sections: Blueprint-style sections with title and bullets.
    """

    # Legacy fields (backward compatible)
    title: Optional[str] = None
    body_bullets: list[str] = []

    # Extended fields for style profiles
    type: Optional[str] = None
    scope: Optional[str] = None
    subject: Optional[str] = None
    breaking_change: bool = False
    footers: list[str] = []
    ticket: Optional[str] = None

    # Blueprint-specific fields
    summary: Optional[str] = None
    sections: list[BlueprintSection] = []

    @field_validator("body_bullets", mode="before")
    @classmethod
    def ensure_bullets_list(cls, v):
        """Ensure body_bullets is a list."""
        if v is None:
            return []
        return v

    @field_validator("footers", mode="before")
    @classmethod
    def ensure_footers_list(cls, v):
        """Ensure footers is a list."""
        if v is None:
            return []
        return v

    @field_validator("sections", mode="before")
    @classmethod
    def ensure_sections_list(cls, v):
        """Ensure sections is a list of BlueprintSection objects."""
        if v is None:
            return []
        # Convert dicts to BlueprintSection if needed
        result = []
        for item in v:
            if isinstance(item, dict):
                result.append(BlueprintSection(**item))
            elif isinstance(item, BlueprintSection):
                result.append(item)
        return result

    def get_subject(self) -> str:
        """Get the subject line, preferring 'subject' over 'title'.

        Returns:
            The subject string.

        Raises:
            ValueError: If neither subject nor title is provided.
        """
        if self.subject and self.subject.strip():
            return self.subject.strip()
        if self.title and self.title.strip():
            return self.title.strip()
        raise ValueError("Either 'subject' or 'title' must be provided")

    def get_type(self, default: str = "feat") -> str:
        """Get the commit type, with fallback.

        Args:
            default: Default type if not specified.

        Returns:
            The commit type.
        """
        if self.type and self.type.strip():
            return self.type.strip().lower()
        return default

    def get_scope(self) -> Optional[str]:
        """Get the scope if provided.

        Returns:
            The scope or None.
        """
        if self.scope and self.scope.strip():
            return self.scope.strip()
        return None

    def get_bullets(self, max_bullets: Optional[int] = None) -> list[str]:
        """Get bullet points, optionally limited.

        Args:
            max_bullets: Maximum number of bullets to return.

        Returns:
            List of bullet strings.
        """
        bullets = [b.strip() for b in self.body_bullets if b and b.strip()]
        if max_bullets and len(bullets) > max_bullets:
            return bullets[:max_bullets]
        return bullets

    def get_summary(self) -> Optional[str]:
        """Get the summary paragraph for blueprint style.

        Returns:
            The summary string or None.
        """
        if self.summary and self.summary.strip():
            return self.summary.strip()
        return None

    def get_sections(self, allowed_titles: Optional[list[str]] = None) -> list[BlueprintSection]:
        """Get sections, optionally filtered by allowed titles.

        Args:
            allowed_titles: List of allowed section titles (in preferred order).

        Returns:
            List of BlueprintSection objects.
        """
        if not self.sections:
            return []

        if allowed_titles is None:
            return self.sections

        # Filter and order by allowed_titles
        title_to_section = {s.title: s for s in self.sections}
        result = []
        for title in allowed_titles:
            if title in title_to_section:
                result.append(title_to_section[title])
        return result

