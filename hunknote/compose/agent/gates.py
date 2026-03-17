"""Output validation gates for the Compose Agent pipeline.

Every LLM output is validated by a deterministic gate before the orchestrator
acts on it. Gates check structural invariants like frozen hunk references,
nonexistent hunk IDs, duplicate assignments, etc.
"""

from dataclasses import dataclass

from hunknote.compose.inventory import hunk_sort_key


@dataclass
class GateViolation:
    violation_type: str   # "frozen_hunk_referenced", "nonexistent_hunk", etc.
    hunk_id: str
    detail: str


def validate_clustering_output(
    groups: list[dict],
    mutable_hunk_ids: set[str],
    frozen_hunk_ids: set[str],
    max_commits: int,
) -> tuple[bool, list[GateViolation]]:
    """Validate Phase 3 output.

    Checks: no frozen hunks, no nonexistent hunks, no duplicates,
    no unassigned, no empty groups, count ≤ max.
    """
    violations: list[GateViolation] = []
    all_assigned: list[str] = []

    for group in groups:
        hunk_ids = group.get("hunks", [])
        if len(hunk_ids) == 0:
            violations.append(GateViolation(
                "empty_group", "",
                f"Group {group.get('id', '?')} has no hunks",
            ))

        for hid in hunk_ids:
            if hid in frozen_hunk_ids:
                violations.append(GateViolation(
                    "frozen_hunk_referenced", hid,
                    f"Hunk {hid} is frozen in a validated commit and cannot be moved",
                ))
            elif hid not in mutable_hunk_ids:
                violations.append(GateViolation(
                    "nonexistent_hunk", hid,
                    f"Hunk {hid} does not exist in the inventory",
                ))
            if hid in all_assigned:
                violations.append(GateViolation(
                    "duplicate_assignment", hid,
                    f"Hunk {hid} assigned to multiple groups",
                ))
            all_assigned.append(hid)

    assigned_set = set(all_assigned)
    for hid in mutable_hunk_ids:
        if hid not in assigned_set:
            violations.append(GateViolation(
                "mutable_hunk_unassigned", hid,
                f"Hunk {hid} was not assigned to any group",
            ))

    if len(groups) > max_commits:
        violations.append(GateViolation(
            "too_many_groups", "",
            f"Plan has {len(groups)} groups, exceeds max of {max_commits}",
        ))

    return (len(violations) == 0, violations)


def validate_dependency_output(
    edges: list[dict],
    inventory_hunk_ids: set[str],
) -> tuple[bool, list[GateViolation]]:
    """Validate Phase 2 dependency graph output.

    Checks: all hunk IDs exist, no self-dependencies, valid edge types.
    """
    violations: list[GateViolation] = []
    valid_types = {"directional", "bidirectional"}

    for edge in edges:
        from_id = edge.get("from", "")
        to_id = edge.get("to", "")

        if from_id not in inventory_hunk_ids:
            violations.append(GateViolation(
                "nonexistent_hunk_in_edge", from_id,
                f"Edge 'from' references nonexistent hunk {from_id}",
            ))
        if to_id not in inventory_hunk_ids:
            violations.append(GateViolation(
                "nonexistent_hunk_in_edge", to_id,
                f"Edge 'to' references nonexistent hunk {to_id}",
            ))
        if from_id == to_id:
            violations.append(GateViolation(
                "self_dependency", from_id,
                f"Self-referential dependency edge on {from_id}",
            ))
        if edge.get("type", "") not in valid_types:
            violations.append(GateViolation(
                "invalid_edge_type", "",
                f"Edge type '{edge.get('type', '')}' is not valid",
            ))

    return (len(violations) == 0, violations)


def validate_remediation_output(
    remediation: dict,
    mutable_hunk_ids: set[str],
    frozen_hunk_ids: set[str],
    inventory_hunk_ids: set[str],
) -> tuple[bool, list[GateViolation]]:
    """Validate Phase 5b remediation output.

    Checks: valid hunk IDs, no frozen hunks in non-unlock actions,
    no self-dependencies.
    """
    violations: list[GateViolation] = []
    action = remediation.get("action", "")
    mods = remediation.get("modifications", {})

    for group in mods.get("merge_hunks_into_same_commit", []):
        for hid in group:
            if hid not in inventory_hunk_ids:
                violations.append(GateViolation(
                    "nonexistent_hunk_in_remediation", hid,
                    f"Hunk {hid} does not exist",
                ))
            elif hid in frozen_hunk_ids and action != "unlock_and_recluster":
                violations.append(GateViolation(
                    "frozen_hunk_in_remediation", hid,
                    f"Hunk {hid} is frozen — use unlock_and_recluster to modify frozen commits",
                ))

    for edge in mods.get("add_dependency_edges", []):
        for key in ("from", "to"):
            hid = edge.get(key, "")
            if hid and hid not in inventory_hunk_ids:
                violations.append(GateViolation(
                    "nonexistent_hunk_in_edge", hid,
                    f"Edge references nonexistent hunk {hid}",
                ))
        if edge.get("from") and edge.get("from") == edge.get("to"):
            violations.append(GateViolation(
                "self_dependency", edge["from"],
                f"Self-referential dependency edge on {edge['from']}",
            ))

    return (len(violations) == 0, violations)


def build_correction_prompt(
    violations: list[GateViolation],
    mutable_hunk_ids: set[str],
) -> str:
    """Build a reprompt with specific violations and valid hunk ID list."""
    lines = [
        "Your previous output was invalid. The following violations were detected:",
        "",
    ]
    for i, v in enumerate(violations, 1):
        lines.append(f"VIOLATION {i}: [{v.violation_type}] {v.detail}")
    lines.append("")
    lines.append("VALID HUNK IDs you may use:")
    sorted_ids = sorted(
        mutable_hunk_ids,
        key=hunk_sort_key,
    )
    lines.append(", ".join(sorted_ids))
    lines.append("")
    lines.append("Please provide a corrected output.")
    return "\n".join(lines)
