"""Compose Agent — Orchestrator for hunk-level commit planning.

The agent decomposes commit planning into programmatic phases:
1. Symbol extraction (per-hunk, language-aware)
2. Hunk dependency graph construction
3. Connected component grouping
4. Checkpoint validation with iterative merging
5. Topological ordering
6. LLM-based message generation

For small diffs (≤10 hunks), falls back to the existing single-shot LLM.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any

from hunknote.compose.checkpoint import (
    validate_plan_checkpoints,
)
from hunknote.compose.graph import (
    build_hunk_dependency_graph,
    detect_renames,
)
from hunknote.compose.grouping import group_hunks_programmatic, should_use_agent
from hunknote.compose.messenger import (
    COMPOSE_MESSAGE_SYSTEM_PROMPT,
    build_message_prompt,
    create_plan_from_groups,
)
from hunknote.compose.models import (
    CheckpointResult,
    CommitGroup,
    ComposePlan,
    FileDiff,
    HunkRef,
    HunkSymbols,
    LargeHunkAnnotation,
    Rename,
)
from hunknote.compose.symbols import (
    annotate_large_hunks,
    extract_all_symbols,
)

logger = logging.getLogger(__name__)


class ComposeAgentResult:
    """Result from the compose agent pipeline."""

    def __init__(
        self,
        plan: ComposePlan,
        used_agent: bool,
        symbol_analyses: dict[str, HunkSymbols],
        graph: dict[str, set[str]],
        renames: list[Rename],
        groups: list[CommitGroup],
        large_hunk_annotations: dict[str, LargeHunkAnnotation],
        checkpoint_results: list[tuple[str, CheckpointResult]],
        llm_model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        thinking_tokens: int = 0,
        trace_log: list[dict] | None = None,
    ):
        self.plan = plan
        self.used_agent = used_agent
        self.symbol_analyses = symbol_analyses
        self.graph = graph
        self.renames = renames
        self.groups = groups
        self.large_hunk_annotations = large_hunk_annotations
        self.checkpoint_results = checkpoint_results
        self.llm_model = llm_model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.thinking_tokens = thinking_tokens
        self.trace_log = trace_log or []


def run_compose_agent(
    file_diffs: list[FileDiff],
    inventory: dict[str, HunkRef],
    style: str,
    max_commits: int,
    branch: str = "",
    recent_commits: list[str] | None = None,
    force_agent: bool = False,
    provider: Any = None,
    use_react: bool = True,
    stream: bool = False,
) -> ComposeAgentResult:
    """Run the compose agent pipeline.

    When use_react=True (default), delegates to the ReAct orchestrator
    which uses LLM sub-agents for dependency analysis, grouping, ordering,
    and validation. Falls back to the programmatic pipeline on failure.

    When use_react=False, uses the existing programmatic pipeline with
    LLM only for message generation.

    Args:
        file_diffs: Parsed file diffs.
        inventory: Dictionary mapping hunk ID to HunkRef.
        style: Style profile name.
        max_commits: Maximum number of commits.
        branch: Current branch name.
        recent_commits: Recent commit subjects.
        force_agent: Force agent mode regardless of threshold.
        provider: LLM provider for message generation (legacy path).
        use_react: Use the ReAct orchestrator (default: True).
        stream: Stream status updates to stderr.

    Returns:
        ComposeAgentResult with the plan and metadata.
    """
    all_hunk_ids = set(inventory.keys())
    trace_log: list[dict] = []
    agent_start = time.monotonic()

    def _trace(phase: str, status: str, details: dict | None = None, duration: float = 0.0):
        entry: dict[str, Any] = {
            "phase": phase,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_s": round(duration, 4),
        }
        if details:
            entry["details"] = details
        trace_log.append(entry)

    # Check whether to use agent mode
    if not force_agent and not should_use_agent(inventory, file_diffs):
        _trace("threshold_check", "skipped", {"reason": "below threshold", "hunks": len(all_hunk_ids)})
        return ComposeAgentResult(
            plan=ComposePlan(),
            used_agent=False,
            symbol_analyses={},
            graph={},
            renames=[],
            groups=[],
            large_hunk_annotations={},
            checkpoint_results=[],
            trace_log=trace_log,
        )

    _trace("threshold_check", "activated", {
        "reason": "force_agent" if force_agent else "auto-detected",
        "hunks": len(all_hunk_ids),
        "files": len(file_diffs),
    })

    # ── ReAct Agent Path ──
    if use_react and provider is not None:
        try:
            # Determine provider name and model name from provider object
            provider_name = _get_provider_name(provider)
            model_name = getattr(provider, "model", "gemini-2.5-flash")

            from hunknote.compose.react_agent import run_react_agent

            agent_state = run_react_agent(
                provider_name=provider_name,
                model_name=model_name,
                file_diffs=file_diffs,
                inventory=inventory,
                style=style,
                max_commits=max_commits,
                branch=branch,
                recent_commits=recent_commits,
                stream=stream,
            )

            if agent_state.plan and len(agent_state.plan.commits) > 0:
                # Build a programmatic graph for ComposeAgentResult compat
                symbol_analyses = extract_all_symbols(inventory)
                renames = detect_renames(symbol_analyses)
                prog_graph = build_hunk_dependency_graph(symbol_analyses, renames)
                large_hunk_annotations = annotate_large_hunks(
                    inventory, file_diffs, symbol_analyses,
                )

                return ComposeAgentResult(
                    plan=agent_state.plan,
                    used_agent=True,
                    symbol_analyses=symbol_analyses,
                    graph=prog_graph,
                    renames=renames,
                    groups=agent_state.ordered_groups or agent_state.commit_groups or [],
                    large_hunk_annotations=large_hunk_annotations,
                    checkpoint_results=[],
                    llm_model=agent_state.llm_model,
                    input_tokens=agent_state.total_input_tokens,
                    output_tokens=agent_state.total_output_tokens,
                    thinking_tokens=agent_state.total_thinking_tokens,
                    trace_log=agent_state.trace_log,
                )
            else:
                logger.info("ReAct agent produced empty plan, falling back to programmatic pipeline")

        except Exception as e:
            logger.warning("ReAct agent failed: %s, falling back to programmatic pipeline", e)
            _trace("react_fallback", "failed", {"error": str(e)})

    # ── Phase 1: Symbol Extraction ──
    logger.debug("Agent Phase 1: Extracting symbols from %d hunks", len(inventory))
    t0 = time.monotonic()
    symbol_analyses = extract_all_symbols(inventory)
    large_hunk_annotations = annotate_large_hunks(
        inventory, file_diffs, symbol_analyses,
    )
    t1 = time.monotonic()

    total_defs = sum(len(s.defines) for s in symbol_analyses.values())
    total_refs = sum(len(s.references) for s in symbol_analyses.values())
    total_imports = sum(len(s.imports_added) for s in symbol_analyses.values())
    languages = list(set(s.language for s in symbol_analyses.values()))

    _trace("phase_1_symbol_extraction", "completed", {
        "hunks_analysed": len(symbol_analyses),
        "total_definitions": total_defs,
        "total_references": total_refs,
        "total_imports_added": total_imports,
        "large_hunks": len(large_hunk_annotations),
        "languages": languages,
    }, t1 - t0)

    # ── Phase 2: Build Hunk Dependency Graph ──
    logger.debug("Agent Phase 2: Building hunk dependency graph")
    t0 = time.monotonic()
    renames = detect_renames(symbol_analyses)
    graph = build_hunk_dependency_graph(symbol_analyses, renames)
    t1 = time.monotonic()

    total_edges = sum(len(v) for v in graph.values())
    logger.debug("Graph: %d edges across %d hunks", total_edges, len(all_hunk_ids))

    _trace("phase_2_dependency_graph", "completed", {
        "total_edges": total_edges,
        "hunks_with_deps": len(graph),
        "renames_detected": len(renames),
        "rename_pairs": [{"old": r.old_name, "new": r.new_name, "hunk": r.defining_hunk} for r in renames],
    }, t1 - t0)

    # ── Phase 3: Grouping ──
    logger.debug("Agent Phase 3: Grouping hunks")
    t0 = time.monotonic()
    groups = group_hunks_programmatic(symbol_analyses, all_hunk_ids, graph)
    initial_group_count = len(groups)
    t1 = time.monotonic()

    _trace("phase_3_grouping", "completed", {
        "initial_groups": initial_group_count,
        "groups": [{"hunks": g.hunk_ids, "files": g.files} for g in groups],
    }, t1 - t0)

    logger.debug("Initial groups: %d", initial_group_count)

    # ── Phase 4: Respect max_commits ──
    merged = False
    if len(groups) > max_commits:
        t0 = time.monotonic()
        groups = _merge_to_max_commits(groups, max_commits)
        t1 = time.monotonic()
        merged = True
        _trace("phase_4_merge", "completed", {
            "groups_before": initial_group_count,
            "groups_after": len(groups),
            "max_commits": max_commits,
        }, t1 - t0)

    if not merged:
        _trace("phase_4_merge", "skipped", {
            "reason": f"groups ({len(groups)}) <= max_commits ({max_commits})",
        })

    # ── Phase 5: Message Generation via LLM ──
    plan = ComposePlan()
    llm_model = ""
    input_tokens = 0
    output_tokens = 0
    thinking_tokens = 0

    if provider is not None:
        logger.debug("Agent Phase 5: Generating commit messages via LLM")
        t0 = time.monotonic()
        prompt = build_message_prompt(
            groups=groups,
            inventory=inventory,
            file_diffs=file_diffs,
            style=style,
            branch=branch,
            recent_commits=recent_commits,
        )

        try:
            result = provider.generate_raw(
                system_prompt=COMPOSE_MESSAGE_SYSTEM_PROMPT,
                user_prompt=prompt,
            )
            llm_model = result.model
            input_tokens = result.input_tokens
            output_tokens = result.output_tokens
            thinking_tokens = result.thinking_tokens

            from hunknote.llm.base import parse_json_response
            plan_data = parse_json_response(result.raw_response)
            plan = create_plan_from_groups(groups, plan_data)
            t1 = time.monotonic()

            _trace("phase_5_llm_messaging", "completed", {
                "model": llm_model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "thinking_tokens": thinking_tokens,
                "commits_generated": len(plan.commits),
            }, t1 - t0)

        except Exception as e:
            t1 = time.monotonic()
            logger.warning("LLM message generation failed: %s. Using placeholder messages.", e)
            plan = create_plan_from_groups(groups)
            _trace("phase_5_llm_messaging", "fallback", {
                "error": str(e),
                "used_placeholder": True,
            }, t1 - t0)
    else:
        plan = create_plan_from_groups(groups)
        _trace("phase_5_llm_messaging", "skipped", {"reason": "no provider"})

    # ── Phase 6: Validate final plan checkpoints ──
    t0 = time.monotonic()
    checkpoint_results = validate_plan_checkpoints(
        plan, graph, symbol_analyses, all_hunk_ids,
    )
    t1 = time.monotonic()

    cp_details = []
    for commit_id, cp_result in checkpoint_results:
        cp_entry: dict[str, Any] = {"commit": commit_id, "valid": cp_result.valid}
        if not cp_result.valid:
            cp_entry["violations"] = [
                {"hunk": v.hunk, "issue": v.issue}
                for v in cp_result.violations
            ]
        cp_details.append(cp_entry)

    _trace("phase_6_checkpoint_validation", "completed", {
        "checkpoints_checked": len(checkpoint_results),
        "all_valid": all(r.valid for _, r in checkpoint_results),
        "checkpoints": cp_details,
    }, t1 - t0)

    agent_duration = time.monotonic() - agent_start
    _trace("agent_complete", "completed", {
        "total_duration_s": round(agent_duration, 4),
        "used_agent": True,
        "final_groups": len(groups),
        "final_commits": len(plan.commits),
    }, agent_duration)

    return ComposeAgentResult(
        plan=plan,
        used_agent=True,
        symbol_analyses=symbol_analyses,
        graph=graph,
        renames=renames,
        groups=groups,
        large_hunk_annotations=large_hunk_annotations,
        checkpoint_results=checkpoint_results,
        llm_model=llm_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thinking_tokens=thinking_tokens,
        trace_log=trace_log,
    )


def _merge_to_max_commits(
    groups: list[CommitGroup],
    max_commits: int,
) -> list[CommitGroup]:
    """Merge groups until we have at most max_commits.

    Merges the smallest adjacent groups first.

    Args:
        groups: List of CommitGroup objects.
        max_commits: Maximum allowed groups.

    Returns:
        Merged list of CommitGroup objects.
    """
    while len(groups) > max_commits:
        # Find the two smallest adjacent groups
        min_size = float("inf")
        min_idx = 0
        for i in range(len(groups) - 1):
            combined_size = len(groups[i].hunk_ids) + len(groups[i + 1].hunk_ids)
            if combined_size < min_size:
                min_size = combined_size
                min_idx = i

        # Merge groups[min_idx] and groups[min_idx + 1]
        merged = CommitGroup(
            hunk_ids=sorted(set(groups[min_idx].hunk_ids + groups[min_idx + 1].hunk_ids)),
            files=sorted(set(groups[min_idx].files + groups[min_idx + 1].files)),
            reason=f"Merged to meet max_commits={max_commits}",
        )
        groups = groups[:min_idx] + [merged] + groups[min_idx + 2:]

    return groups


def _get_provider_name(provider: Any) -> str:
    """Extract the provider name from a provider object.

    Args:
        provider: An LLM provider instance.

    Returns:
        Provider name string (e.g., "google", "anthropic").
    """
    class_name = type(provider).__name__.lower()
    # Match by substring to handle subclasses and wrappers
    for keyword, name in [
        ("google", "google"),
        ("anthropic", "anthropic"),
        ("openai", "openai"),
        ("mistral", "mistral"),
        ("cohere", "cohere"),
        ("groq", "groq"),
        ("openrouter", "openrouter"),
    ]:
        if keyword in class_name:
            return name
    return "google"

