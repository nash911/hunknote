"""Compose feature for Hunknote - split changes into atomic commits."""

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, model_validator


# ============================================================================
# Data Models
# ============================================================================

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


# ============================================================================
# Diff Parser
# ============================================================================


def parse_unified_diff(diff_output: str) -> tuple[list[FileDiff], list[str]]:
    """Parse unified diff output from 'git diff HEAD --patch'.

    Args:
        diff_output: Raw output from git diff

    Returns:
        Tuple of (list of FileDiff objects, list of warning messages)
    """
    files: list[FileDiff] = []
    warnings: list[str] = []
    hunk_counter = 0

    if not diff_output.strip():
        return files, warnings

    # Split by file blocks
    # Each file starts with 'diff --git a/... b/...'
    file_blocks = re.split(r"(?=^diff --git )", diff_output, flags=re.MULTILINE)

    for block in file_blocks:
        if not block.strip():
            continue

        if not block.startswith("diff --git"):
            continue

        lines = block.split("\n")
        file_diff = _parse_file_block(lines, hunk_counter, warnings)
        if file_diff:
            hunk_counter += len(file_diff.hunks)
            files.append(file_diff)

    return files, warnings


def _parse_file_block(
    lines: list[str], hunk_start_id: int, warnings: list[str]
) -> Optional[FileDiff]:
    """Parse a single file block from the diff.

    Args:
        lines: Lines of the file block
        hunk_start_id: Starting ID for hunks in this file
        warnings: List to append warnings to

    Returns:
        FileDiff object or None if binary/invalid
    """
    if not lines or not lines[0].startswith("diff --git"):
        return None

    # Extract file path from diff --git line
    # Format: diff --git a/path b/path
    match = re.match(r"diff --git a/(.*) b/(.*)", lines[0])
    if not match:
        return None

    old_path = match.group(1)
    new_path = match.group(2)
    file_path = new_path

    # Collect header lines until first @@ or end
    header_lines = []
    hunk_start_idx = 0
    is_binary = False
    is_new_file = False
    is_deleted_file = False
    is_renamed = old_path != new_path

    for i, line in enumerate(lines):
        if line.startswith("@@"):
            hunk_start_idx = i
            break
        header_lines.append(line)

        # Check for binary
        if "GIT binary patch" in line or "Binary files" in line:
            is_binary = True
            warnings.append(f"Binary file skipped: {file_path}")
            return FileDiff(
                file_path=file_path,
                diff_header_lines=header_lines,
                hunks=[],
                is_binary=True,
                old_path=old_path if is_renamed else None,
            )

        # Check for new/deleted file
        if line.startswith("new file mode"):
            is_new_file = True
        if line.startswith("deleted file mode"):
            is_deleted_file = True
    else:
        # No hunks found (could be mode change only)
        return FileDiff(
            file_path=file_path,
            diff_header_lines=header_lines,
            hunks=[],
            is_new_file=is_new_file,
            is_deleted_file=is_deleted_file,
            is_renamed=is_renamed,
            old_path=old_path if is_renamed else None,
        )

    # Parse hunks
    hunks = _parse_hunks(lines[hunk_start_idx:], file_path, hunk_start_id)

    return FileDiff(
        file_path=file_path,
        diff_header_lines=header_lines,
        hunks=hunks,
        is_binary=is_binary,
        is_new_file=is_new_file,
        is_deleted_file=is_deleted_file,
        is_renamed=is_renamed,
        old_path=old_path if is_renamed else None,
    )


def _parse_hunks(lines: list[str], file_path: str, start_id: int) -> list[HunkRef]:
    """Parse hunks from the hunk portion of a file diff.

    Args:
        lines: Lines starting from first @@
        file_path: Path to the file
        start_id: Starting ID number for hunks

    Returns:
        List of HunkRef objects
    """
    hunks: list[HunkRef] = []
    current_hunk_lines: list[str] = []
    current_header: Optional[str] = None
    hunk_id = start_id

    for line in lines:
        if line.startswith("@@"):
            # Save previous hunk if exists
            if current_header is not None:
                hunk = _create_hunk_ref(
                    hunk_id, file_path, current_header, current_hunk_lines
                )
                if hunk:
                    hunks.append(hunk)
                    hunk_id += 1

            # Start new hunk
            current_header = line
            current_hunk_lines = [line]
        elif current_header is not None:
            # Continue current hunk
            current_hunk_lines.append(line)

    # Save last hunk
    if current_header is not None:
        hunk = _create_hunk_ref(hunk_id, file_path, current_header, current_hunk_lines)
        if hunk:
            hunks.append(hunk)

    return hunks


def _create_hunk_ref(
    hunk_id: int, file_path: str, header: str, lines: list[str]
) -> Optional[HunkRef]:
    """Create a HunkRef from parsed hunk data.

    Args:
        hunk_id: Numeric ID for the hunk
        file_path: Path to the file
        header: The @@ header line
        lines: All lines of the hunk including header

    Returns:
        HunkRef object or None if invalid
    """
    # Parse @@ -a,b +c,d @@ header
    # Format: @@ -old_start,old_len +new_start,new_len @@ optional context
    match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
    if not match:
        return None

    old_start = int(match.group(1))
    old_len = int(match.group(2)) if match.group(2) else 1
    new_start = int(match.group(3))
    new_len = int(match.group(4)) if match.group(4) else 1

    # Generate stable ID with hash suffix for uniqueness
    content_hash = hashlib.md5(
        "".join(lines).encode(), usedforsecurity=False
    ).hexdigest()[:6]
    stable_id = f"H{hunk_id + 1}_{content_hash}"

    return HunkRef(
        id=stable_id,
        file_path=file_path,
        header=header,
        old_start=old_start,
        old_len=old_len,
        new_start=new_start,
        new_len=new_len,
        lines=lines,
    )


# ============================================================================
# Hunk Inventory
# ============================================================================


def build_hunk_inventory(file_diffs: list[FileDiff]) -> dict[str, HunkRef]:
    """Build a mapping of hunk IDs to HunkRef objects.

    Args:
        file_diffs: List of FileDiff objects

    Returns:
        Dictionary mapping hunk ID to HunkRef
    """
    inventory: dict[str, HunkRef] = {}
    for file_diff in file_diffs:
        for hunk in file_diff.hunks:
            inventory[hunk.id] = hunk
    return inventory


def format_inventory_for_llm(
    file_diffs: list[FileDiff], max_snippet_lines: int = 5
) -> str:
    """Format the hunk inventory for inclusion in LLM prompt.

    Args:
        file_diffs: List of FileDiff objects
        max_snippet_lines: Maximum lines to show per hunk snippet

    Returns:
        Formatted string for LLM prompt
    """
    lines = ["[HUNK INVENTORY]"]

    for file_diff in file_diffs:
        if file_diff.is_binary:
            continue

        lines.append(f"\nFile: {file_diff.file_path}")
        if file_diff.is_new_file:
            lines.append("  (new file)")
        elif file_diff.is_deleted_file:
            lines.append("  (deleted file)")
        elif file_diff.is_renamed:
            lines.append(f"  (renamed from {file_diff.old_path})")

        for hunk in file_diff.hunks:
            lines.append(f"\n  Hunk {hunk.id}:")
            lines.append(f"    {hunk.header}")
            snippet = hunk.snippet(max_snippet_lines)
            for snippet_line in snippet.split("\n"):
                lines.append(f"    {snippet_line}")

    return "\n".join(lines)


# ============================================================================
# Plan Validation
# ============================================================================


class PlanValidationError(Exception):
    """Error during plan validation."""

    pass


def validate_plan(
    plan: ComposePlan, inventory: dict[str, HunkRef], max_commits: int
) -> list[str]:
    """Validate a compose plan against the hunk inventory.

    Args:
        plan: The compose plan to validate
        inventory: Dictionary of hunk ID to HunkRef
        max_commits: Maximum allowed commits

    Returns:
        List of validation errors (empty if valid)

    Raises:
        PlanValidationError: If critical validation fails
    """
    errors: list[str] = []

    # Check commit count
    if len(plan.commits) > max_commits:
        errors.append(
            f"Plan has {len(plan.commits)} commits, exceeds max of {max_commits}"
        )

    if len(plan.commits) == 0:
        errors.append("Plan has no commits")

    # Track used hunks to detect duplicates
    used_hunks: set[str] = set()

    for commit in plan.commits:
        # Check for empty commits
        if not commit.hunks:
            errors.append(f"Commit {commit.id} has no hunks")
            continue

        # Check for unknown hunk IDs
        for hunk_id in commit.hunks:
            if hunk_id not in inventory:
                errors.append(f"Commit {commit.id} references unknown hunk: {hunk_id}")
            elif hunk_id in used_hunks:
                errors.append(f"Hunk {hunk_id} is used in multiple commits")
            else:
                used_hunks.add(hunk_id)

        # Check for missing title
        if not commit.title or not commit.title.strip():
            errors.append(f"Commit {commit.id} has no title")

    # Check that all hunks are assigned
    unassigned = set(inventory.keys()) - used_hunks
    if unassigned:
        # This is a warning, not an error
        plan.warnings.append(
            f"Unassigned hunks: {', '.join(sorted(unassigned)[:5])}"
            + (f" and {len(unassigned) - 5} more" if len(unassigned) > 5 else "")
        )

    return errors


# ============================================================================
# Patch Builder
# ============================================================================


def build_commit_patch(
    commit: PlannedCommit,
    inventory: dict[str, HunkRef],
    file_diffs: list[FileDiff],
) -> str:
    """Build a patch file for a single commit.

    Args:
        commit: The planned commit
        inventory: Dictionary of hunk ID to HunkRef
        file_diffs: Original file diffs for header information

    Returns:
        Patch content as string
    """
    # Group hunks by file
    hunks_by_file: dict[str, list[HunkRef]] = {}
    for hunk_id in commit.hunks:
        hunk = inventory.get(hunk_id)
        if hunk:
            if hunk.file_path not in hunks_by_file:
                hunks_by_file[hunk.file_path] = []
            hunks_by_file[hunk.file_path].append(hunk)

    # Build patch preserving original file order
    patch_lines: list[str] = []

    for file_diff in file_diffs:
        if file_diff.file_path not in hunks_by_file:
            continue

        # Add file header
        patch_lines.extend(file_diff.diff_header_lines)

        # Add hunks in original order
        file_hunks = hunks_by_file[file_diff.file_path]
        # Sort by original order (old_start)
        file_hunks.sort(key=lambda h: h.old_start)

        for hunk in file_hunks:
            patch_lines.extend(hunk.lines)

    # git apply requires the patch to end with a newline
    return "\n".join(patch_lines) + "\n"


# ============================================================================
# Compose Prompt
# ============================================================================


COMPOSE_SYSTEM_PROMPT = """You are an expert software engineer creating a clean commit stack from a set of changes.

Your task is to split the given changes (hunks) into logical, atomic commits following best practices:
- Each commit should be cohesive and focused on one logical change
- Separate features, refactors, tests, docs, and config changes
- Order commits logically (infrastructure before features, etc.)
- Do not split hunks from the same new file across commits
- Reference ONLY the hunk IDs provided in the inventory

Output ONLY valid JSON matching the required schema. No markdown fences or commentary."""


def build_compose_prompt(
    file_diffs: list[FileDiff],
    branch: str,
    recent_commits: list[str],
    style: str,
    max_commits: int,
) -> str:
    """Build the user prompt for compose planning.

    Args:
        file_diffs: Parsed file diffs with hunks
        branch: Current branch name
        recent_commits: Last N commit subjects
        style: Style profile name
        max_commits: Maximum number of commits

    Returns:
        User prompt string
    """
    inventory_text = format_inventory_for_llm(file_diffs)

    # Count stats
    total_files = len([f for f in file_diffs if not f.is_binary])
    total_hunks = sum(len(f.hunks) for f in file_diffs)

    prompt = f"""Split the following changes into a clean commit stack.

[CONTEXT]
Branch: {branch}
Recent commits: {', '.join(recent_commits[:5]) if recent_commits else 'None'}
Style: {style}
Max commits: {max_commits}

[STATS]
Files with changes: {total_files}
Total hunks: {total_hunks}

{inventory_text}

[OUTPUT SCHEMA]
Return a JSON object with this exact structure:
{{
  "version": "1",
  "warnings": [],
  "commits": [
    {{
      "id": "C1",
      "type": "<feat|fix|docs|refactor|test|chore|build|ci|perf|style>",
      "scope": "<optional scope>",
      "ticket": null,
      "title": "<short description in imperative mood, max 72 chars, WITHOUT type/scope prefix>",
      "bullets": ["<change 1>", "<change 2>"],
      "summary": null,
      "sections": null,
      "hunks": ["<hunk_id_1>", "<hunk_id_2>"]
    }}
  ]
}}

IMPORTANT: The "title" field must contain ONLY the description, NOT the conventional commit prefix.
The type and scope are already separate JSON fields — do NOT repeat them inside the title.
  Correct:   "type": "feat", "scope": "api", "title": "Add pagination support to list endpoints"
  WRONG:     "type": "feat", "scope": "api", "title": "feat(api): Add pagination support to list endpoints"

  Correct:   "type": "fix", "title": "Prevent null pointer on empty input"
  WRONG:     "type": "fix", "title": "fix: Prevent null pointer on empty input"

  Correct:   "type": "refactor", "scope": "cache", "title": "Replace dict lookup with constant-time set"
  WRONG:     "type": "refactor", "scope": "cache", "title": "refactor(cache): Replace dict lookup with constant-time set"

[RULES]
1. Reference ONLY hunk IDs from the inventory above
2. Each hunk must appear in exactly ONE commit
3. Maximum {max_commits} commits
4. Keep new file hunks together in one commit
5. Order: infrastructure → features → tests → docs
6. Use appropriate commit type based on changes

Output ONLY the JSON object:"""

    return prompt


# ============================================================================
# Executor (Commit Mode)
# ============================================================================


class ComposeExecutionError(Exception):
    """Error during compose execution."""

    pass


@dataclass
class ComposeSnapshot:
    """Snapshot of git state before compose execution."""

    pre_head: str
    pre_staged_patch: str
    patch_file: Optional[Path] = None
    head_file: Optional[Path] = None


def create_snapshot(repo_root: Path, pid: int) -> ComposeSnapshot:
    """Create a snapshot of current git state.

    Args:
        repo_root: Repository root path
        pid: Process ID for unique filenames

    Returns:
        ComposeSnapshot with saved state
    """
    tmp_dir = repo_root / ".tmp"
    tmp_dir.mkdir(exist_ok=True)

    # Get current HEAD
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    pre_head = result.stdout.strip() if result.returncode == 0 else ""

    # Get current staged changes
    result = subprocess.run(
        ["git", "diff", "--cached"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    pre_staged_patch = result.stdout if result.returncode == 0 else ""

    # Save to files
    head_file = tmp_dir / f"hunknote_compose_pre_head_{pid}.txt"
    patch_file = tmp_dir / f"hunknote_compose_pre_staged_{pid}.patch"

    head_file.write_text(pre_head)
    if pre_staged_patch:
        patch_file.write_text(pre_staged_patch)

    return ComposeSnapshot(
        pre_head=pre_head,
        pre_staged_patch=pre_staged_patch,
        patch_file=patch_file if pre_staged_patch else None,
        head_file=head_file,
    )


def restore_from_snapshot(
    repo_root: Path, snapshot: ComposeSnapshot, commits_created: int
) -> tuple[bool, str]:
    """Attempt to restore git state from snapshot.

    Args:
        repo_root: Repository root path
        snapshot: The snapshot to restore from
        commits_created: Number of commits already created

    Returns:
        Tuple of (success, message)
    """
    messages = []

    # Reset index to HEAD
    result = subprocess.run(
        ["git", "reset"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        return False, f"Failed to reset index: {result.stderr}"

    messages.append("Reset index to HEAD")

    # Re-apply pre-staged changes if any
    if snapshot.patch_file and snapshot.patch_file.exists():
        result = subprocess.run(
            ["git", "apply", "--cached", str(snapshot.patch_file)],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if result.returncode == 0:
            messages.append("Restored pre-staged changes")
        else:
            messages.append(f"Warning: Could not restore staged changes: {result.stderr}")

    # Provide manual recovery instructions if commits were created
    if commits_created > 0:
        messages.append("")
        messages.append("MANUAL RECOVERY (if needed):")
        messages.append(f"  To undo the {commits_created} commit(s) created:")
        messages.append(f"  git reset --soft {snapshot.pre_head}")

    return True, "\n".join(messages)


def execute_commit(
    repo_root: Path,
    commit: PlannedCommit,
    patch_content: str,
    message: str,
    pid: int,
    debug: bool = False,
) -> None:
    """Execute a single commit in the plan.

    Args:
        repo_root: Repository root path
        commit: The planned commit
        patch_content: Patch content to apply
        message: Rendered commit message
        pid: Process ID for unique filenames
        debug: Whether to print debug output

    Raises:
        ComposeExecutionError: If commit fails
    """
    tmp_dir = repo_root / ".tmp"
    tmp_dir.mkdir(exist_ok=True)

    # Write patch file
    patch_file = tmp_dir / f"hunknote_compose_patch_{commit.id}_{pid}.patch"
    patch_file.write_text(patch_content)

    if debug:
        print(f"  Patch file: {patch_file}")
        print(f"  Patch size: {len(patch_content)} chars")

    # Apply patch to index
    result = subprocess.run(
        ["git", "apply", "--cached", str(patch_file)],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        raise ComposeExecutionError(
            f"Failed to apply patch for {commit.id}: {result.stderr}"
        )

    # Verify something is staged
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if not result.stdout.strip():
        raise ComposeExecutionError(f"No changes staged after applying {commit.id}")

    if debug:
        staged_files = result.stdout.strip().split("\n")
        print(f"  Staged files: {len(staged_files)}")

    # Write message file
    msg_file = tmp_dir / f"hunknote_compose_msg_{commit.id}_{pid}.txt"
    msg_file.write_text(message)

    # Commit
    result = subprocess.run(
        ["git", "commit", "-F", str(msg_file)],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        raise ComposeExecutionError(
            f"Failed to commit {commit.id}: {result.stderr}"
        )

    if debug:
        print(f"  Commit created: {commit.id}")


# ============================================================================
# Cleanup
# ============================================================================


def cleanup_temp_files(repo_root: Path, pid: int) -> None:
    """Clean up temporary files created during compose.

    Args:
        repo_root: Repository root path
        pid: Process ID used in filenames
    """
    tmp_dir = repo_root / ".tmp"
    if not tmp_dir.exists():
        return

    patterns = [
        f"hunknote_compose_*_{pid}.*",
    ]

    import glob

    for pattern in patterns:
        for filepath in glob.glob(str(tmp_dir / pattern)):
            try:
                Path(filepath).unlink()
            except OSError:
                pass

