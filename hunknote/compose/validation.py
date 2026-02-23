"""Plan validation for hunknote compose module.

Contains:
- PlanValidationError: Exception for validation errors
- validate_plan: Validate a compose plan against the hunk inventory
- try_correct_hunk_ids: Attempt to correct hallucinated hunk IDs
"""

import re
from typing import Optional

from hunknote.compose.models import ComposePlan, HunkRef


class PlanValidationError(Exception):
    """Error during plan validation."""

    pass


def _extract_hunk_number(hunk_id: str) -> Optional[int]:
    """Extract the numeric part from a hunk ID like H1_abc123.

    Args:
        hunk_id: Hunk ID string (e.g., "H1_abc123")

    Returns:
        The numeric part (e.g., 1) or None if not matching expected format
    """
    match = re.match(r"H(\d+)_", hunk_id)
    if match:
        return int(match.group(1))
    return None


def _find_similar_hunk(
    invalid_id: str, inventory: dict[str, HunkRef], used_hunks: set[str]
) -> Optional[str]:
    """Try to find a similar valid hunk ID for an invalid one.

    This handles common LLM mistakes like:
    - H2_e43c95 when the correct ID is H2_e4f347 (same H# prefix, wrong hash)
    - Looking for hunks with same numeric prefix that haven't been used

    Args:
        invalid_id: The invalid hunk ID from LLM
        inventory: Dictionary of valid hunk IDs
        used_hunks: Set of already-used hunk IDs

    Returns:
        A valid hunk ID if a unique match is found, None otherwise
    """
    invalid_num = _extract_hunk_number(invalid_id)
    if invalid_num is None:
        return None

    # Find all inventory hunks with the same H# prefix that are not yet used
    candidates = []
    for valid_id in inventory.keys():
        if valid_id in used_hunks:
            continue
        valid_num = _extract_hunk_number(valid_id)
        if valid_num == invalid_num:
            candidates.append(valid_id)

    # Only return if there's exactly one match (unambiguous correction)
    if len(candidates) == 1:
        return candidates[0]

    return None


def try_correct_hunk_ids(
    plan: ComposePlan, inventory: dict[str, HunkRef]
) -> tuple[bool, list[str]]:
    """Attempt to automatically correct hallucinated hunk IDs.

    LLMs sometimes generate incorrect hunk IDs by mixing up similar-looking
    hashes. This function tries to find and correct such mistakes.

    Args:
        plan: The compose plan to correct (modified in place)
        inventory: Dictionary of hunk ID to HunkRef

    Returns:
        Tuple of (corrections_made: bool, corrections_log: list[str])
    """
    corrections_made = False
    corrections_log: list[str] = []

    # Track used hunks to avoid creating duplicates during correction
    used_hunks: set[str] = set()

    # First pass: collect all valid hunks that are already used
    for commit in plan.commits:
        for hunk_id in commit.hunks:
            if hunk_id in inventory:
                used_hunks.add(hunk_id)

    # Second pass: try to correct invalid hunks
    for commit in plan.commits:
        corrected_hunks: list[str] = []
        for hunk_id in commit.hunks:
            if hunk_id in inventory:
                corrected_hunks.append(hunk_id)
            else:
                # Try to find a similar valid hunk
                similar = _find_similar_hunk(hunk_id, inventory, used_hunks)
                if similar:
                    corrected_hunks.append(similar)
                    used_hunks.add(similar)
                    corrections_log.append(
                        f"Corrected {hunk_id} -> {similar} in commit {commit.id}"
                    )
                    corrections_made = True
                else:
                    # Keep the invalid ID; it will be caught by validation
                    corrected_hunks.append(hunk_id)

        commit.hunks = corrected_hunks

    return corrections_made, corrections_log


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

