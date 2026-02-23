"""Backward compatibility shim for hunknote.compose.

This module re-exports all symbols from the new hunknote.compose package
to maintain backward compatibility with existing imports.

The compose module has been refactored into a package with the following structure:
- hunknote/compose/models.py: HunkRef, FileDiff, PlannedCommit, ComposePlan, BlueprintSection
- hunknote/compose/parser.py: parse_unified_diff and related functions
- hunknote/compose/inventory.py: build_hunk_inventory, format_inventory_for_llm
- hunknote/compose/validation.py: validate_plan, PlanValidationError
- hunknote/compose/patch.py: build_commit_patch
- hunknote/compose/prompt.py: COMPOSE_SYSTEM_PROMPT, build_compose_prompt
- hunknote/compose/executor.py: ComposeSnapshot, ComposeExecutionError, create_snapshot,
                                restore_from_snapshot, execute_commit
- hunknote/compose/cleanup.py: cleanup_temp_files
"""

# Re-export everything from the new package
from hunknote.compose import (
    # Models
    BlueprintSection,
    ComposePlan,
    FileDiff,
    HunkRef,
    PlannedCommit,
    # Parser
    parse_unified_diff,
    # Inventory
    build_hunk_inventory,
    format_inventory_for_llm,
    # Validation
    PlanValidationError,
    validate_plan,
    try_correct_hunk_ids,
    # Patch
    build_commit_patch,
    # Prompt
    COMPOSE_SYSTEM_PROMPT,
    build_compose_prompt,
    # Executor
    ComposeExecutionError,
    ComposeSnapshot,
    create_snapshot,
    execute_commit,
    restore_from_snapshot,
    # Cleanup
    cleanup_temp_files,
)

__all__ = [
    # Models
    "HunkRef",
    "FileDiff",
    "BlueprintSection",
    "PlannedCommit",
    "ComposePlan",
    # Parser
    "parse_unified_diff",
    # Inventory
    "build_hunk_inventory",
    "format_inventory_for_llm",
    # Validation
    "PlanValidationError",
    "validate_plan",
    "try_correct_hunk_ids",
    # Patch
    "build_commit_patch",
    # Prompt
    "COMPOSE_SYSTEM_PROMPT",
    "build_compose_prompt",
    # Executor
    "ComposeSnapshot",
    "ComposeExecutionError",
    "create_snapshot",
    "restore_from_snapshot",
    "execute_commit",
    # Cleanup
    "cleanup_temp_files",
]
