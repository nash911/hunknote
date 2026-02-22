"""Compose feature for Hunknote - split changes into atomic commits.

This package provides modular compose handling with:
- models: HunkRef, FileDiff, PlannedCommit, ComposePlan, BlueprintSection
- parser: parse_unified_diff and related functions
- inventory: build_hunk_inventory, format_inventory_for_llm
- validation: validate_plan, PlanValidationError
- patch: build_commit_patch
- prompt: COMPOSE_SYSTEM_PROMPT, build_compose_prompt
- executor: ComposeSnapshot, ComposeExecutionError, create_snapshot,
            restore_from_snapshot, execute_commit
- cleanup: cleanup_temp_files
"""

# Models
from hunknote.compose.models import (
    BlueprintSection,
    ComposePlan,
    FileDiff,
    HunkRef,
    PlannedCommit,
)

# Parser
from hunknote.compose.parser import (
    parse_unified_diff,
)

# Inventory
from hunknote.compose.inventory import (
    build_hunk_inventory,
    format_inventory_for_llm,
)

# Validation
from hunknote.compose.validation import (
    PlanValidationError,
    validate_plan,
)

# Patch builder
from hunknote.compose.patch import (
    build_commit_patch,
)

# Prompt
from hunknote.compose.prompt import (
    COMPOSE_SYSTEM_PROMPT,
    build_compose_prompt,
)

# Executor
from hunknote.compose.executor import (
    ComposeExecutionError,
    ComposeSnapshot,
    create_snapshot,
    execute_commit,
    restore_from_snapshot,
)

# Cleanup
from hunknote.compose.cleanup import (
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

