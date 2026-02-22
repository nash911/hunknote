"""Data models for hunknote compose module.

Contains:
- HunkRef: Reference to a single hunk in a diff
- FileDiff: Diff for a single file containing multiple hunks
- BlueprintSection: Section in a blueprint-style commit message
- PlannedCommit: A single commit in the compose plan
- ComposePlan: The full compose plan containing multiple commits
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, model_validator


# Regex to match conventional commit prefix: type(scope): or type:
_CONVENTIONAL_PREFIX_RE = re.compile(
    r"^(?P<type>[a-zA-Z]+)"          # type (e.g., feat, fix, refactor)
    r"(?:\((?P<scope>[^)]*)\))?"     # optional (scope)
    r":\s*"                           # colon + optional space
)


@dataclass
class HunkRef:
    """Reference to a single hunk in a diff."""

    id: str
    file_path: str
    header: str  # The @@ ... @@ line
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list[str]  # Raw hunk lines including +/- and context

    def snippet(self, max_lines: int = 5) -> str:
        """Get a snippet of the hunk content for display."""
        content_lines = [ln for ln in self.lines if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
        if len(content_lines) <= max_lines:
            return "\n".join(content_lines)
        return "\n".join(content_lines[:max_lines]) + f"\n... ({len(content_lines) - max_lines} more lines)"


@dataclass
class FileDiff:
    """Diff for a single file containing multiple hunks."""

    file_path: str
    diff_header_lines: list[str]  # From 'diff --git' up to first @@
    hunks: list[HunkRef] = field(default_factory=list)
    is_binary: bool = False
    is_new_file: bool = False
    is_deleted_file: bool = False
    is_renamed: bool = False
    old_path: Optional[str] = None  # For renames


class BlueprintSection(BaseModel):
    """Section in a blueprint-style commit message."""

    title: str
    bullets: list[str]


class PlannedCommit(BaseModel):
    """A single commit in the compose plan."""

    id: str  # e.g., "C1", "C2"
    type: Optional[str] = None  # Conventional commit type
    scope: Optional[str] = None
    ticket: Optional[str] = None
    title: str
    bullets: Optional[list[str]] = None  # For default/conventional styles
    summary: Optional[str] = None  # For blueprint style
    sections: Optional[list[BlueprintSection]] = None  # For blueprint style
    hunks: list[str]  # Hunk IDs (e.g., ["H1", "H7"])

    @model_validator(mode="after")
    def strip_conventional_prefix_from_title(self) -> "PlannedCommit":
        """Strip the conventional commit prefix from the title if it duplicates the type/scope fields.

        LLMs sometimes return titles like "feat(env): Allow EnvMaster ..." even though
        type and scope are separate JSON fields. This validator removes the redundant prefix.
        """
        if self.type and self.title:
            match = _CONVENTIONAL_PREFIX_RE.match(self.title)
            if match and match.group("type").lower() == self.type.lower():
                self.title = self.title[match.end():]
        return self


class ComposePlan(BaseModel):
    """The full compose plan containing multiple commits."""

    version: str = "1"
    warnings: list[str] = []
    commits: list[PlannedCommit] = []

