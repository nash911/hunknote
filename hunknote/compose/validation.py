"""Plan validation for hunknote compose module.

Contains:
- PlanValidationError: Exception for validation errors
- validate_plan: Validate a compose plan against the hunk inventory
"""

from hunknote.compose.models import ComposePlan, HunkRef


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

