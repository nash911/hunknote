"""Commit style profiles and rendering for hunknote.

Supports multiple commit message formats:
- default: Title + bullet points (current Hunknote format)
- blueprint: Structured sections with summary (Changes, Implementation, Testing, etc.)
- conventional: Conventional Commits (type(scope): subject)
- ticket: Ticket-prefixed commits (PROJ-123 subject)
- kernel: Linux kernel style (subsystem: subject)
"""

import re
import textwrap
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel, field_validator


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


def wrap_text(text: str, width: int = 72, initial_indent: str = "", subsequent_indent: str = "") -> str:
    """Wrap text to specified width.

    Args:
        text: Text to wrap.
        width: Maximum line width.
        initial_indent: Indent for first line.
        subsequent_indent: Indent for subsequent lines.

    Returns:
        Wrapped text.
    """
    return textwrap.fill(
        text,
        width=width,
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        break_long_words=False,
        break_on_hyphens=False,
    )


def sanitize_subject(subject: str, max_length: int = 72) -> str:
    """Sanitize and truncate the subject line.

    Args:
        subject: The raw subject string.
        max_length: Maximum allowed length.

    Returns:
        A sanitized single-line subject, truncated if necessary.
    """
    # Strip whitespace and take only the first line
    subject = subject.strip().split("\n")[0].strip()

    if len(subject) > max_length:
        # Truncate and add ellipsis
        subject = subject[: max_length - 3].rstrip() + "..."

    return subject


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


def extract_ticket_from_branch(branch: str, pattern: str = r"([A-Z][A-Z0-9]+-\d+)") -> Optional[str]:
    """Extract ticket key from branch name.

    Args:
        branch: The branch name.
        pattern: Regex pattern for ticket extraction.

    Returns:
        The extracted ticket key or None.
    """
    match = re.search(pattern, branch)
    if match:
        return match.group(1)
    return None


def infer_commit_type(staged_files: list[str]) -> Optional[str]:
    """Infer conventional commit type from staged files.

    Args:
        staged_files: List of staged file paths.

    Returns:
        Inferred commit type or None if cannot determine.
    """
    if not staged_files:
        return None

    # Check for docs-only changes
    doc_extensions = {".md", ".rst", ".txt", ".adoc"}
    doc_dirs = {"docs", "doc", "documentation"}

    all_docs = all(
        any(f.endswith(ext) for ext in doc_extensions) or
        any(d in f.lower() for d in doc_dirs)
        for f in staged_files
    )
    if all_docs:
        return "docs"

    # Check for test-only changes
    test_patterns = {"test_", "_test.", ".test.", "tests/", "test/", "spec/", "__tests__/"}
    all_tests = all(
        any(p in f.lower() for p in test_patterns)
        for f in staged_files
    )
    if all_tests:
        return "test"

    # Check for CI changes (BEFORE build, since CI files often match build patterns)
    ci_patterns = {".github/workflows/", ".github/workflows", ".gitlab-ci", "Jenkinsfile", ".circleci/", ".travis", ".circleci"}
    all_ci = all(
        any(p in f for p in ci_patterns)
        for f in staged_files
    )
    if all_ci:
        return "ci"

    # Check for config/build changes (excluding CI files)
    build_files = {
        "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "pyproject.toml", "poetry.lock", "setup.py", "setup.cfg", "requirements.txt",
        "Makefile", "CMakeLists.txt", "Cargo.toml", "Cargo.lock",
        "go.mod", "go.sum", "Gemfile", "Gemfile.lock",
        "Dockerfile", "docker-compose",
    }
    all_build = all(
        any(bf in f for bf in build_files)
        for f in staged_files
    )
    if all_build:
        return "build"


    return None


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
