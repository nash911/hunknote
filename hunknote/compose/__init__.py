"""Compose feature for Hunknote - split changes into atomic commits.

This package provides modular compose handling with:
- models: HunkRef, FileDiff, PlannedCommit, ComposePlan, BlueprintSection,
          HunkSymbols, LargeHunkAnnotation, Rename, CheckpointResult,
          Violation, CommitGroup
- parser: parse_unified_diff and related functions
- inventory: build_hunk_inventory, format_inventory_for_llm
- validation: validate_plan, PlanValidationError
- patch: build_commit_patch
- prompt: COMPOSE_SYSTEM_PROMPT, build_compose_prompt
- relationships: detect_file_relationships, FileRelationship, format_relationships_for_llm
- executor: ComposeSnapshot, ComposeExecutionError, create_snapshot,
            restore_from_snapshot, execute_commit
- cleanup: cleanup_temp_files
- extractors: Language-specific symbol extractors (agent)
- symbols: extract_symbols_from_hunk, extract_all_symbols, annotate_large_hunks (agent)
- graph: build_hunk_dependency_graph, compute_connected_components (agent)
- checkpoint: validate_commit_checkpoint, validate_plan_checkpoints (agent)
- grouping: should_use_agent, group_hunks_programmatic (agent)
- messenger: build_message_prompt, COMPOSE_MESSAGE_SYSTEM_PROMPT (agent)
- agent: run_compose_agent, ComposeAgentResult (agent orchestrator)
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
    try_correct_hunk_ids,
)

# Patch builder
from hunknote.compose.patch import (
    build_commit_patch,
)

# Prompt
from hunknote.compose.prompt import (
    COMPOSE_SYSTEM_PROMPT,
    COMPOSE_RETRY_SYSTEM_PROMPT,
    build_compose_prompt,
    build_compose_retry_prompt,
)

# Relationships (file dependency detection)
from hunknote.compose.relationships import (
    FileRelationship,
    detect_file_relationships,
    format_relationships_for_llm,
    trace_reexports,
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

# Agent: Symbol Extraction
from hunknote.compose.symbols import (
    extract_all_symbols,
    extract_symbols_from_hunk,
    annotate_large_hunks,
)

# Agent: Models
from hunknote.compose.models import (
    HunkSymbols,
    LargeHunkAnnotation,
    Rename,
    CheckpointResult,
    Violation,
    CommitGroup,
    SymbolSet,
)

# Agent: Dependency Graph
from hunknote.compose.graph import (
    build_hunk_dependency_graph,
    compute_connected_components,
    detect_renames,
    find_related_hunks,
    topological_sort_groups,
)

# Agent: Checkpoint Validation
from hunknote.compose.checkpoint import (
    validate_commit_checkpoint,
    validate_plan_checkpoints,
)

# Agent: Grouping
from hunknote.compose.grouping import (
    group_hunks_programmatic,
    should_use_agent,
)

# Agent: Messenger
from hunknote.compose.messenger import (
    COMPOSE_MESSAGE_SYSTEM_PROMPT,
    build_message_prompt,
    create_plan_from_groups,
)

# Agent: Orchestrator
from hunknote.compose.agent import (
    ComposeAgentResult,
    run_compose_agent,
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
    "COMPOSE_RETRY_SYSTEM_PROMPT",
    "build_compose_prompt",
    "build_compose_retry_prompt",
    # Relationships
    "FileRelationship",
    "detect_file_relationships",
    "format_relationships_for_llm",
    "trace_reexports",
    # Executor
    "ComposeSnapshot",
    "ComposeExecutionError",
    "create_snapshot",
    "restore_from_snapshot",
    "execute_commit",
    # Cleanup
    "cleanup_temp_files",
    # Agent: Models
    "HunkSymbols",
    "LargeHunkAnnotation",
    "Rename",
    "CheckpointResult",
    "Violation",
    "CommitGroup",
    "SymbolSet",
    # Agent: Symbols
    "extract_symbols_from_hunk",
    "extract_all_symbols",
    "annotate_large_hunks",
    # Agent: Graph
    "build_hunk_dependency_graph",
    "compute_connected_components",
    "detect_renames",
    "find_related_hunks",
    "topological_sort_groups",
    # Agent: Checkpoint
    "validate_commit_checkpoint",
    "validate_plan_checkpoints",
    # Agent: Grouping
    "group_hunks_programmatic",
    "should_use_agent",
    # Agent: Messenger
    "COMPOSE_MESSAGE_SYSTEM_PROMPT",
    "build_message_prompt",
    "create_plan_from_groups",
    # Agent: Orchestrator
    "ComposeAgentResult",
    "run_compose_agent",
]
