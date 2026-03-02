"""CLI command for composing multi-commit stacks."""

import json
import os
import subprocess
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from hunknote.cache import compute_context_hash
from hunknote.git_ctx import GitError, get_repo_root, get_branch
from hunknote.git.diff import _should_exclude_file
from hunknote.git.status import _get_staged_files_list
from hunknote.user_config import get_ignore_patterns
from hunknote.llm import LLMError, MissingAPIKeyError
from hunknote.llm.base import parse_json_response, JSONParseError
from hunknote.styles import StyleProfile
from hunknote.cli.utils import (
    get_effective_style_config,
    colorize_diff,
    show_in_pager,
)
from hunknote.compose.relationships import detect_file_relationships, format_relationships_for_llm
from hunknote.cache import (
    save_compose_agent_trace,
    save_compose_hunk_graph,
    save_compose_hunk_symbols,
    load_compose_agent_trace,
    load_compose_hunk_graph,
)


def compose_command(
    max_commits: int = typer.Option(
        6,
        "--max-commits",
        help="Maximum number of commits in the plan",
    ),
    style: Optional[str] = typer.Option(
        None,
        "--style",
        help="Override commit style profile (default, blueprint, conventional, ticket, kernel)",
    ),
    do_commit: bool = typer.Option(
        False,
        "--commit",
        "-c",
        help="Execute the plan: stage hunks and create commits",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt in commit mode",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Force plan-only even if --commit is present",
    ),
    regenerate: bool = typer.Option(
        False,
        "--regenerate",
        "-r",
        help="Force regenerate the compose plan, ignoring cache",
    ),
    show_json: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Show the cached compose plan JSON for debugging",
    ),
    from_plan: Optional[Path] = typer.Option(
        None,
        "--from-plan",
        help="Load plan JSON from file instead of calling LLM",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Print diagnostics (inventory stats, patch paths, git apply output)",
    ),
    show: Optional[str] = typer.Option(
        None,
        "--show",
        help="Show the full diff for a compose commit ID (e.g., --show C1)",
    ),
    agent: Optional[bool] = typer.Option(
        None,
        "--agent/--no-agent",
        help="Force agent mode (hunk-level grouping) on or off. Default: auto-detect.",
    ),
    show_graph: bool = typer.Option(
        False,
        "--graph",
        help="Render the hunk dependency graph on the terminal.",
    ),
    show_trace: bool = typer.Option(
        False,
        "--trace",
        help="Render the agent/sub-agent tracing logs on the terminal.",
    ),
) -> None:
    """Split staged changes into a clean commit stack.

    Analyzes staged changes and proposes splitting them into multiple
    atomic commits. By default, only shows the plan without
    modifying git state.

    Use --commit to execute the plan and create the commits.
    """
    # Fixed retry count - not exposed to user
    max_retries = 2

    from hunknote.config import load_config
    from hunknote.cache import (
        is_compose_cache_valid,
        save_compose_cache,
        save_compose_hunk_ids,
        load_compose_plan,
        load_compose_metadata,
        invalidate_compose_cache,
    )
    from hunknote.compose import (
        parse_unified_diff,
        build_hunk_inventory,
        validate_plan,
        try_correct_hunk_ids,
        build_commit_patch,
        build_compose_prompt,
        build_compose_retry_prompt,
        create_snapshot,
        restore_from_snapshot,
        execute_commit,
        cleanup_temp_files,
        ComposePlan,
        ComposeExecutionError,
        COMPOSE_SYSTEM_PROMPT,
        COMPOSE_RETRY_SYSTEM_PROMPT,
    )
    from hunknote.styles import (
        ExtendedCommitJSON,
        BlueprintSection as StyleBlueprintSection,
        render_commit_message_styled,
    )

    load_config()

    # Validate style if provided
    override_style = None
    if style:
        try:
            override_style = StyleProfile(style.lower())
        except ValueError:
            typer.echo(f"Invalid style: {style}", err=True)
            typer.echo("Valid styles: default, blueprint, conventional, ticket, kernel")
            raise typer.Exit(1)

    # Handle dry-run flag
    should_commit = do_commit and not dry_run

    try:
        repo_root = get_repo_root()
        pid = os.getpid()

        # If --json flag is used alone, just show cached plan
        if show_json and not regenerate and not do_commit:
            cached_plan = load_compose_plan(repo_root)
            cached_metadata = load_compose_metadata(repo_root)
            if cached_plan:
                typer.echo("")
                typer.echo("[CACHED COMPOSE PLAN]")
                # Pretty print the JSON
                try:
                    plan_obj = json.loads(cached_plan)
                    typer.echo(json.dumps(plan_obj, indent=2))
                except json.JSONDecodeError:
                    typer.echo(cached_plan)
                if cached_metadata:
                    typer.echo("")
                    typer.echo(f"Generated: {cached_metadata.generated_at}", err=True)
                    typer.echo(f"Model: {cached_metadata.model}", err=True)
                    typer.echo(f"Commits: {cached_metadata.num_commits}", err=True)
                raise typer.Exit(0)
            else:
                typer.echo("No cached compose plan found.", err=True)
                typer.echo("Run 'hunknote compose' first to generate a plan.", err=True)
                raise typer.Exit(1)

        # Handle --show <COMPOSE_ID>: show full diff for a specific commit
        if show is not None:
            _compose_show_diff(repo_root, show)
            raise typer.Exit(0)

        # Handle --graph standalone: render cached graph and exit
        if show_graph and not regenerate and not do_commit and not debug:
            _render_graph(repo_root)
            if not show_trace:
                raise typer.Exit(0)

        # Handle --trace standalone: render cached trace and exit
        if show_trace and not regenerate and not do_commit and not debug:
            _render_trace(repo_root)
            raise typer.Exit(0)

        # Get branch and recent commits for context
        branch = get_branch()
        recent_commits_result = subprocess.run(
            ["git", "log", "-n", "5", "--pretty=%s"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        recent_commits = recent_commits_result.stdout.strip().split("\n") if recent_commits_result.returncode == 0 else []

        # Get list of staged files and filter out ignored files
        staged_files = _get_staged_files_list()
        if not staged_files:
            typer.echo("No staged changes to compose.", err=True)
            typer.echo("Stage your changes first with: git add <files>", err=True)
            raise typer.Exit(0)

        # Get ignore patterns from config
        ignore_patterns = get_ignore_patterns(repo_root)

        # Filter out files matching ignore patterns
        files_to_include = [
            f for f in staged_files
            if not _should_exclude_file(f, ignore_patterns)
        ]

        if not files_to_include:
            typer.echo("No staged changes to compose (all staged files are in ignore list).", err=True)
            typer.echo("Check your .hunknote/config.yaml ignore patterns.", err=True)
            raise typer.Exit(0)

        # Get diff of staged changes only for non-ignored files
        diff_result = subprocess.run(
            ["git", "diff", "--cached", "--patch", "--"] + files_to_include,
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if diff_result.returncode != 0:
            typer.echo(f"Failed to get diff: {diff_result.stderr}", err=True)
            raise typer.Exit(1)

        diff_output = diff_result.stdout

        if not diff_output.strip():
            typer.echo("No staged changes to compose.", err=True)
            typer.echo("Stage your changes first with: git add <files>", err=True)
            raise typer.Exit(0)

        # Parse diff
        file_diffs, parse_warnings = parse_unified_diff(diff_output)

        if not file_diffs:
            typer.echo("No parseable changes found.", err=True)
            raise typer.Exit(0)

        # Build hunk inventory
        inventory = build_hunk_inventory(file_diffs)

        # Get effective style for caching
        style_config = get_effective_style_config()
        effective_profile = override_style or style_config.profile

        # Compute cache hash from diff + style + max_commits
        cache_input = f"{diff_output}|style={effective_profile.value}|max_commits={max_commits}"
        current_hash = compute_context_hash(cache_input)

        # Get or load plan
        plan: Optional[ComposePlan] = None
        plan_from_cache = False
        llm_model = ""
        llm_input_tokens = 0
        llm_output_tokens = 0
        llm_thinking_tokens = 0
        cached_metadata = None
        file_relationships_text = ""

        if from_plan:
            # Load plan from external JSON file
            if not from_plan.exists():
                typer.echo(f"Plan file not found: {from_plan}", err=True)
                raise typer.Exit(1)

            try:
                plan_data = json.loads(from_plan.read_text())
                plan = ComposePlan(**plan_data)
                typer.echo(f"Loaded plan from {from_plan}", err=True)
            except Exception as e:
                typer.echo(f"Failed to load plan: {e}", err=True)
                raise typer.Exit(1)

        elif not regenerate and is_compose_cache_valid(repo_root, current_hash):
            # Use cached plan
            typer.echo("Using cached compose plan...", err=True)
            cached_plan_json = load_compose_plan(repo_root)
            cached_metadata = load_compose_metadata(repo_root)

            if cached_plan_json:
                try:
                    plan_data = json.loads(cached_plan_json)
                    plan = ComposePlan(**plan_data)
                    plan_from_cache = True
                    if cached_metadata:
                        llm_model = cached_metadata.model
                        llm_input_tokens = cached_metadata.input_tokens
                        llm_output_tokens = cached_metadata.output_tokens
                        llm_thinking_tokens = getattr(cached_metadata, 'thinking_tokens', 0)
                        file_relationships_text = cached_metadata.file_relationships_text or ""
                except Exception as e:
                    typer.echo(f"Failed to load cached plan: {e}", err=True)
                    typer.echo("Regenerating...", err=True)
                    plan = None

        if plan is None:
            # Generate plan via LLM
            typer.echo("Generating compose plan...", err=True)

            # Detect file relationships for coherent commit grouping
            file_relationships = detect_file_relationships(file_diffs, repo_root)
            file_relationships_text = format_relationships_for_llm(file_relationships)

            # Determine whether to use compose agent (hunk-level grouping)
            from hunknote.compose.agent import run_compose_agent
            from hunknote.compose.grouping import should_use_agent as _should_use_agent

            use_agent = False
            if agent is True:
                use_agent = True
            elif agent is False:
                use_agent = False
            else:
                # Auto-detect: use agent for complex diffs
                use_agent = _should_use_agent(inventory, file_diffs)

            if use_agent:
                # ── Agent Path: Programmatic grouping + LLM messaging ──
                try:
                    from hunknote.llm import get_provider
                    provider = get_provider()

                    agent_result = run_compose_agent(
                        file_diffs=file_diffs,
                        inventory=inventory,
                        style=effective_profile.value,
                        max_commits=max_commits,
                        branch=branch,
                        recent_commits=recent_commits,
                        force_agent=True,
                        provider=provider,
                    )

                    if agent_result.used_agent and len(agent_result.plan.commits) > 0:
                        plan = agent_result.plan
                        llm_model = agent_result.llm_model
                        llm_input_tokens = agent_result.input_tokens
                        llm_output_tokens = agent_result.output_tokens
                        llm_thinking_tokens = agent_result.thinking_tokens

                        # Build agent metadata for cache
                        agent_meta = _build_agent_metadata(agent_result)

                        if debug:
                            typer.echo("", err=True)
                            typer.echo("Agent Mode: ON (hunk-level grouping)", err=True)
                            typer.echo(f"  Symbols extracted: {len(agent_result.symbol_analyses)}", err=True)
                            typer.echo(f"  Graph edges: {sum(len(v) for v in agent_result.graph.values())}", err=True)
                            typer.echo(f"  Groups formed: {len(agent_result.groups)}", err=True)
                            typer.echo(f"  Renames detected: {len(agent_result.renames)}", err=True)
                            typer.echo(f"  Large hunk annotations: {len(agent_result.large_hunk_annotations)}", err=True)
                            # Checkpoint validation results
                            for commit_id, cp_result in agent_result.checkpoint_results:
                                status = "VALID" if cp_result.valid else f"INVALID ({len(cp_result.violations)} violations)"
                                typer.echo(f"  Checkpoint {commit_id}: {status}", err=True)
                            typer.echo("", err=True)

                        # Save graph JSON
                        graph_data = _build_graph_data(agent_result)
                        save_compose_hunk_graph(repo_root, graph_data)

                        # Save symbols JSON
                        symbols_data = _build_symbols_data(agent_result)
                        save_compose_hunk_symbols(repo_root, symbols_data)

                        # Save agent trace JSON
                        trace_data = _build_trace_data(agent_result)
                        save_compose_agent_trace(repo_root, trace_data)

                        # Save to cache
                        changed_files = [f.file_path for f in file_diffs if not f.is_binary]
                        save_compose_cache(
                            repo_root=repo_root,
                            context_hash=current_hash,
                            plan_json=json.dumps(plan.model_dump(), indent=2),
                            model=llm_model,
                            input_tokens=llm_input_tokens,
                            output_tokens=llm_output_tokens,
                            changed_files=changed_files,
                            total_hunks=len(inventory),
                            num_commits=len(plan.commits),
                            style=effective_profile.value,
                            max_commits=max_commits,
                            file_relationships_text=file_relationships_text or None,
                            thinking_tokens=llm_thinking_tokens,
                            agent_metadata=agent_meta,
                        )
                        hunk_ids_data = _build_hunk_ids_data(inventory, file_diffs, plan)
                        save_compose_hunk_ids(repo_root, hunk_ids_data)
                    else:
                        # Agent didn't produce results; fall through to single-shot
                        plan = None
                        if debug:
                            typer.echo("Agent Mode: skipped (threshold not met)", err=True)

                except Exception as e:
                    # Agent failed; fall through to single-shot
                    plan = None
                    if debug:
                        typer.echo(f"Agent Mode: failed ({e}), falling back to single-shot LLM", err=True)

        if plan is None:
            # ── Single-shot LLM Path (fallback or default for small diffs) ──
            if not file_relationships_text:
                file_relationships = detect_file_relationships(file_diffs, repo_root)
                file_relationships_text = format_relationships_for_llm(file_relationships)
            else:
                # file_relationships already computed by agent path
                file_relationships = detect_file_relationships(file_diffs, repo_root)

            prompt = build_compose_prompt(
                file_diffs=file_diffs,
                branch=branch,
                recent_commits=recent_commits,
                style=effective_profile.value,
                max_commits=max_commits,
                file_relationships=file_relationships,
            )

            if debug:
                typer.echo("LLM Prompt:", err=True)
                typer.echo("-" * 40, err=True)
                # Show truncated prompt
                if len(prompt) > 2000:
                    typer.echo(prompt[:1000] + "\n...[truncated]...\n" + prompt[-500:], err=True)
                else:
                    typer.echo(prompt, err=True)
                typer.echo("-" * 40, err=True)
                typer.echo("", err=True)

            # Call LLM
            try:
                from hunknote.llm import get_provider
                provider = get_provider()

                # Use the compose-specific prompt
                result = provider.generate_raw(
                    system_prompt=COMPOSE_SYSTEM_PROMPT,
                    user_prompt=prompt,
                )

                llm_model = result.model
                llm_input_tokens = result.input_tokens
                llm_output_tokens = result.output_tokens
                llm_thinking_tokens = result.thinking_tokens

                if debug:
                    typer.echo(f"LLM Response ({result.input_tokens} in, {result.output_tokens} out):", err=True)
                    typer.echo(result.raw_response[:500] if len(result.raw_response) > 500 else result.raw_response, err=True)
                    typer.echo("", err=True)

                # Parse response
                plan_data = parse_json_response(result.raw_response)
                plan = ComposePlan(**plan_data)

                # Save to cache
                changed_files = [f.file_path for f in file_diffs if not f.is_binary]
                save_compose_cache(
                    repo_root=repo_root,
                    context_hash=current_hash,
                    plan_json=json.dumps(plan.model_dump(), indent=2),
                    model=llm_model,
                    input_tokens=llm_input_tokens,
                    output_tokens=llm_output_tokens,
                    changed_files=changed_files,
                    total_hunks=len(inventory),
                    num_commits=len(plan.commits),
                    style=effective_profile.value,
                    max_commits=max_commits,
                    file_relationships_text=file_relationships_text or None,
                    thinking_tokens=llm_thinking_tokens,
                )

                # Build and save hunk IDs file
                hunk_ids_data = _build_hunk_ids_data(inventory, file_diffs, plan)
                save_compose_hunk_ids(repo_root, hunk_ids_data)

            except MissingAPIKeyError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)
            except JSONParseError as e:
                typer.echo(f"Failed to parse LLM response: {e}", err=True)
                raise typer.Exit(1)
            except Exception as e:
                typer.echo(f"Error generating plan: {e}", err=True)
                raise typer.Exit(1)

        # If --json flag with other operations, show the plan JSON
        if show_json:
            typer.echo("")
            typer.echo("[COMPOSE PLAN JSON]")
            typer.echo(json.dumps(plan.model_dump(), indent=2))
            typer.echo("")

        # Print comprehensive debug info (after plan is loaded)
        if debug:
            typer.echo("", err=True)
            typer.echo("=" * 60, err=True)
            typer.echo("              COMPOSE DEBUG INFO", err=True)
            typer.echo("=" * 60, err=True)
            typer.echo("", err=True)

            # Cache status
            cache_status_str = "VALID (using cached plan)" if plan_from_cache else "NEW (generated from LLM)"
            typer.echo(f"Cache Status: {cache_status_str}", err=True)
            typer.echo(f"Cache Key: {current_hash[:16]}...", err=True)

            # Metadata info (if available from cache)
            if cached_metadata:
                try:
                    generated_dt = datetime.fromisoformat(cached_metadata.generated_at)
                    formatted_time = generated_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                except (ValueError, AttributeError):
                    formatted_time = cached_metadata.generated_at
                typer.echo(f"Generated At: {formatted_time}", err=True)

            typer.echo(f"LLM Model: {llm_model or 'N/A'}", err=True)
            typer.echo("", err=True)

            # Usage statistics
            typer.echo("Usage Statistics:", err=True)
            if llm_input_tokens > 0 or llm_output_tokens > 0:
                typer.echo(f"  Tokens: {llm_input_tokens:,} input / {llm_output_tokens:,} output", err=True)
                if llm_thinking_tokens > 0:
                    typer.echo(f"  Thinking: {llm_thinking_tokens:,} tokens (internal reasoning)", err=True)
            else:
                typer.echo("  Tokens: N/A (loaded from file)", err=True)
            typer.echo("", err=True)

            # Style and settings
            typer.echo("Settings:", err=True)
            typer.echo(f"  Style: {effective_profile.value}", err=True)
            typer.echo(f"  Max Commits: {max_commits}", err=True)
            typer.echo("", err=True)

            # Diff statistics
            typer.echo("Diff Statistics:", err=True)
            typer.echo(f"  Files with changes: {len(file_diffs)}", err=True)
            typer.echo(f"  Total hunks: {len(inventory)}", err=True)
            binary_count = len([f for f in file_diffs if f.is_binary])
            if binary_count > 0:
                typer.echo(f"  Binary files skipped: {binary_count}", err=True)
            new_files = len([f for f in file_diffs if f.is_new_file])
            if new_files > 0:
                typer.echo(f"  New files: {new_files}", err=True)
            deleted_files = len([f for f in file_diffs if f.is_deleted_file])
            if deleted_files > 0:
                typer.echo(f"  Deleted files: {deleted_files}", err=True)
            typer.echo("", err=True)

            # Changed files list with hunk IDs
            typer.echo("Changed Files:", err=True)
            for f in file_diffs[:15]:  # Show first 15
                status = ""
                if f.is_new_file:
                    status = " (new)"
                elif f.is_deleted_file:
                    status = " (deleted)"
                elif f.is_binary:
                    status = " (binary, skipped)"

                # Get hunk IDs for this file
                hunk_ids = [h.id for h in f.hunks]
                if hunk_ids:
                    # Show short hunk IDs (just the H# part for brevity)
                    short_ids = [hid.split("_")[0] for hid in hunk_ids]
                    hunk_str = f" [{', '.join(short_ids)}]"
                else:
                    hunk_str = ""

                typer.echo(f"  - {f.file_path}{status}{hunk_str}", err=True)
            if len(file_diffs) > 15:
                typer.echo(f"  ... and {len(file_diffs) - 15} more files", err=True)
            typer.echo("", err=True)

            # File relationships (Strategy 2)
            typer.echo("File Relationships:", err=True)
            if file_relationships_text:
                # Skip the [FILE RELATIONSHIPS] header line and the description line
                for line in file_relationships_text.split("\n"):
                    if line.startswith("[FILE RELATIONSHIPS]"):
                        continue
                    if line.startswith("Detected import dependencies"):
                        continue
                    if line.strip():
                        typer.echo(f"  {line.strip()}", err=True)
            else:
                typer.echo("  No relationships detected.", err=True)
            typer.echo("", err=True)

            # Warnings
            if parse_warnings:
                typer.echo("Warnings:", err=True)
                for warning in parse_warnings:
                    typer.echo(f"  - {warning}", err=True)
                typer.echo("", err=True)

            # Plan summary
            typer.echo("Plan Summary:", err=True)
            typer.echo(f"  Commits in plan: {len(plan.commits)}", err=True)
            total_hunks_in_plan = sum(len(c.hunks) for c in plan.commits)
            typer.echo(f"  Hunks assigned: {total_hunks_in_plan}/{len(inventory)}", err=True)
            typer.echo("", err=True)

            # Agent info (from cached metadata or live result)
            agent_meta: dict | None = None
            if cached_metadata and isinstance(cached_metadata.agent, dict):
                agent_meta = cached_metadata.agent

            if agent_meta:
                typer.echo("Agent Info:", err=True)
                typer.echo(f"  Mode: {agent_meta.get('mode', 'N/A')}", err=True)
                typer.echo(f"  Symbols extracted: {agent_meta.get('symbols_extracted', 'N/A')}", err=True)
                typer.echo(f"  Graph edges: {agent_meta.get('graph_edges', 'N/A')}", err=True)
                typer.echo(f"  Renames detected: {agent_meta.get('renames_detected', 'N/A')}", err=True)
                typer.echo(f"  Groups formed: {agent_meta.get('groups_formed', 'N/A')}", err=True)
                typer.echo(f"  Large hunks: {agent_meta.get('large_hunks', 'N/A')}", err=True)
                langs = agent_meta.get("languages", [])
                if langs:
                    typer.echo(f"  Languages: {', '.join(langs)}", err=True)
                cp_summary = agent_meta.get("checkpoints", {})
                if cp_summary:
                    typer.echo(f"  Checkpoints: {cp_summary.get('total', 0)} checked, "
                               f"{cp_summary.get('valid', 0)} valid, "
                               f"{cp_summary.get('invalid', 0)} invalid", err=True)
                duration = agent_meta.get("total_duration_s")
                if duration:
                    typer.echo(f"  Agent duration: {duration}s", err=True)
                typer.echo("", err=True)

            typer.echo("=" * 60, err=True)
            typer.echo("", err=True)

        # ── --graph: Render the hunk dependency graph ──
        if show_graph:
            _render_graph(repo_root)

        # ── --trace: Render the agent trace logs ──
        if show_trace:
            _render_trace(repo_root)

        # If --graph or --trace was the only purpose, exit early
        if (show_graph or show_trace) and not do_commit and not debug and not show_json and not show:
            raise typer.Exit()

        # Try to auto-correct hallucinated hunk IDs before validation
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

        # If corrections were made and this is a freshly generated plan,
        # re-save the cache and hunk IDs with the corrected plan
        if corrections_made > 0 and not plan_from_cache and not from_plan:
            changed_files = [f.file_path for f in file_diffs if not f.is_binary]
            save_compose_cache(
                repo_root=repo_root,
                context_hash=current_hash,
                plan_json=json.dumps(plan.model_dump(), indent=2),
                model=llm_model,
                input_tokens=llm_input_tokens,
                output_tokens=llm_output_tokens,
                changed_files=changed_files,
                total_hunks=len(inventory),
                num_commits=len(plan.commits),
                style=effective_profile.value,
                max_commits=max_commits,
                file_relationships_text=file_relationships_text or None,
                thinking_tokens=llm_thinking_tokens,
            )
            hunk_ids_data = _build_hunk_ids_data(inventory, file_diffs, plan)
            save_compose_hunk_ids(repo_root, hunk_ids_data)

        # Validate plan with silent retry logic
        validation_errors = validate_plan(plan, inventory, max_commits)
        retry_count = 0
        retry_stats: list[dict] = []

        # Silent retry loop: if validation fails and we haven't exhausted retries
        while validation_errors and retry_count < max_retries and not plan_from_cache and not from_plan:
            retry_count += 1

            try:
                from hunknote.llm import get_provider
                provider = get_provider()

                # Build retry prompt with validation errors
                valid_hunk_ids = sorted(inventory.keys())
                retry_prompt = build_compose_retry_prompt(
                    file_diffs=file_diffs,
                    previous_plan=plan,
                    validation_errors=validation_errors,
                    valid_hunk_ids=valid_hunk_ids,
                    max_commits=max_commits,
                )

                # Call LLM with retry prompt
                result = provider.generate_raw(
                    system_prompt=COMPOSE_RETRY_SYSTEM_PROMPT,
                    user_prompt=retry_prompt,
                )

                # Record retry stats silently
                retry_stat = {
                    "retry_number": retry_count,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "thinking_tokens": result.thinking_tokens,
                    "errors_before": validation_errors.copy(),
                    "success": False,  # Will be updated if successful
                }

                llm_input_tokens += result.input_tokens
                llm_output_tokens += result.output_tokens
                llm_thinking_tokens += result.thinking_tokens

                # Parse the new plan
                plan_data = parse_json_response(result.raw_response)
                plan = ComposePlan(**plan_data)

                # Try fuzzy correction on the new plan
                corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)

                # Re-validate
                validation_errors = validate_plan(plan, inventory, max_commits)

                if not validation_errors:
                    retry_stat["success"] = True
                    retry_stats.append(retry_stat)

                    # Update cache with the corrected plan (including retry stats)
                    changed_files = [f.file_path for f in file_diffs if not f.is_binary]
                    save_compose_cache(
                        repo_root=repo_root,
                        context_hash=current_hash,
                        plan_json=json.dumps(plan.model_dump(), indent=2),
                        model=llm_model,
                        input_tokens=llm_input_tokens,
                        output_tokens=llm_output_tokens,
                        changed_files=changed_files,
                        total_hunks=len(inventory),
                        num_commits=len(plan.commits),
                        style=effective_profile.value,
                        max_commits=max_commits,
                        file_relationships_text=file_relationships_text or None,
                        retry_count=retry_count,
                        retry_stats=retry_stats,
                        thinking_tokens=llm_thinking_tokens,
                    )

                    # Update hunk IDs cache
                    hunk_ids_data = _build_hunk_ids_data(inventory, file_diffs, plan)
                    save_compose_hunk_ids(repo_root, hunk_ids_data)
                else:
                    retry_stats.append(retry_stat)

            except JSONParseError:
                # Silently record failed retry
                retry_stats.append({
                    "retry_number": retry_count,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "errors_before": validation_errors.copy(),
                    "success": False,
                    "error": "JSON parse error",
                })
            except Exception:
                # Silently record failed retry
                retry_stats.append({
                    "retry_number": retry_count,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "errors_before": validation_errors.copy(),
                    "success": False,
                    "error": "Unknown error",
                })

        # Final validation check after all retries
        if validation_errors:
            typer.echo("Plan validation failed:", err=True)
            for error in validation_errors:
                typer.echo(f"  - {error}", err=True)
            if plan_from_cache:
                typer.echo("", err=True)
                typer.echo("Note: Using cached plan. Try --regenerate to generate a new plan.", err=True)
            elif from_plan:
                typer.echo("", err=True)
                typer.echo("Note: Using plan from file. The provided plan has invalid hunk IDs.", err=True)
            raise typer.Exit(1)

        # Print plan
        typer.echo("")
        typer.echo("=" * 60)
        cache_status = "(cached)" if plan_from_cache else "(new)"
        typer.echo(f"Proposed commit stack ({len(plan.commits)} commits) {cache_status}")
        typer.echo("=" * 60)

        # Print warnings
        for warning in plan.warnings + parse_warnings:
            typer.echo(f"Warning: {warning}", err=True)

        # Print commit summaries
        typer.echo("")
        for i, planned_commit in enumerate(plan.commits, 1):
            title = planned_commit.title
            if planned_commit.type:
                if planned_commit.scope:
                    prefix = f"{planned_commit.type}({planned_commit.scope}): "
                else:
                    prefix = f"{planned_commit.type}: "
                typer.echo(f"  {i}. {prefix}{title}")
            else:
                typer.echo(f"  {i}. {title}")
            # Count unique files in this commit
            commit_files = set()
            for hid in planned_commit.hunks:
                hunk_ref = inventory.get(hid)
                if hunk_ref:
                    commit_files.add(hunk_ref.file_path)
            num_files = len(commit_files)
            file_label = "file" if num_files == 1 else "files"
            typer.echo(f"     ({len(planned_commit.hunks)} hunks, {num_files} {file_label})")

        # Print detailed previews
        typer.echo("")
        typer.echo("-" * 60)
        typer.echo("Commit Message Previews")
        typer.echo("-" * 60)

        style_config = get_effective_style_config()
        effective_profile = override_style or style_config.profile

        # Use a wider wrap width for preview rendering so titles are not truncated
        from dataclasses import replace as dc_replace
        preview_config = dc_replace(style_config, wrap_width=200)

        for planned_commit in plan.commits:
            # Convert to ExtendedCommitJSON for rendering
            sections = None
            if planned_commit.sections:
                sections = [
                    StyleBlueprintSection(title=s.title, bullets=s.bullets)
                    for s in planned_commit.sections
                ]

            extended_json = ExtendedCommitJSON(
                type=planned_commit.type,
                scope=planned_commit.scope,
                title=planned_commit.title,
                subject=planned_commit.title,
                body_bullets=planned_commit.bullets or [],
                summary=planned_commit.summary,
                sections=sections,
                ticket=planned_commit.ticket,
            )

            # Render message (using wider wrap width for preview)
            rendered = render_commit_message_styled(
                extended_json,
                preview_config,
                override_style=effective_profile,
            )

            typer.echo("")
            typer.echo(f"[{planned_commit.id}]")
            typer.echo(rendered)

        typer.echo("")
        typer.echo("=" * 60)

        # If not committing, we're done
        if not should_commit:
            typer.echo("")
            typer.echo("Plan only - no changes made to git state.", err=True)
            typer.echo("Run with --commit to execute this plan.", err=True)
            raise typer.Exit(0)

        # Confirm before committing
        if not yes:
            typer.echo("")
            confirm = typer.prompt(
                "Execute this plan and create commits? [y/N]",
                default="n",
                show_default=False,
            )
            if confirm.lower() not in ("y", "yes"):
                typer.echo("Cancelled.", err=True)
                raise typer.Exit(0)

        # Execute the plan
        typer.echo("")
        typer.echo("Executing compose plan...", err=True)

        # Create snapshot for recovery
        snapshot = create_snapshot(repo_root, pid)
        commits_created = 0

        try:
            # First, reset index to clean state (unstage everything)
            subprocess.run(
                ["git", "reset"],
                capture_output=True,
                text=True,
                cwd=repo_root,
            )

            for i, planned_commit in enumerate(plan.commits):
                # Delay between commits so each gets a distinct timestamp
                if i > 0:
                    time.sleep(1)

                typer.echo(f"  Creating commit {planned_commit.id}: {planned_commit.title[:50]}...", err=True)

                # Build patch for this commit
                patch_content = build_commit_patch(planned_commit, inventory, file_diffs)

                if not patch_content.strip():
                    raise ComposeExecutionError(f"Empty patch for commit {planned_commit.id}")

                # Convert to ExtendedCommitJSON for rendering
                sections = None
                if planned_commit.sections:
                    sections = [
                        StyleBlueprintSection(title=s.title, bullets=s.bullets)
                        for s in planned_commit.sections
                    ]

                extended_json = ExtendedCommitJSON(
                    type=planned_commit.type,
                    scope=planned_commit.scope,
                    title=planned_commit.title,
                    subject=planned_commit.title,
                    body_bullets=planned_commit.bullets or [],
                    summary=planned_commit.summary,
                    sections=sections,
                    ticket=planned_commit.ticket,
                )

                # Render message
                message = render_commit_message_styled(
                    extended_json,
                    style_config,
                    override_style=effective_profile,
                )

                # Execute commit
                execute_commit(repo_root, planned_commit, patch_content, message, pid, debug)
                commits_created += 1

            typer.echo("")
            typer.echo(f"Successfully created {commits_created} commit(s)!", err=True)

            # Show git log of new commits
            log_result = subprocess.run(
                ["git", "log", f"-n{commits_created}", "--oneline"],
                capture_output=True,
                text=True,
                cwd=repo_root,
            )
            if log_result.returncode == 0:
                typer.echo("")
                typer.echo("New commits:", err=True)
                typer.echo(log_result.stdout, err=True)

            # Cleanup temp files and invalidate compose cache
            cleanup_temp_files(repo_root, pid)
            invalidate_compose_cache(repo_root)

        except ComposeExecutionError as e:
            typer.echo(f"\nError during execution: {e}", err=True)
            typer.echo("\nAttempting to restore previous state...", err=True)

            success, restore_msg = restore_from_snapshot(repo_root, snapshot, commits_created)
            typer.echo(restore_msg, err=True)

            if not success:
                typer.echo("\nAutomatic restore failed. Manual recovery may be needed.", err=True)

            raise typer.Exit(1)

    except GitError as e:
        typer.echo(f"Git error: {e}", err=True)
        raise typer.Exit(1)
    except MissingAPIKeyError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"LLM error: {e}", err=True)
        raise typer.Exit(1)


def _compose_show_diff(repo_root: Path, compose_id: str) -> None:
    """Show the full diff for a specific compose commit ID in a scrollable pager.

    Args:
        repo_root: Repository root path.
        compose_id: The compose commit ID (e.g., 'C1', '1', 'c3').
    """
    from hunknote.cache import (
        load_compose_plan,
        load_compose_hunk_ids,
    )

    # Normalize the compose ID: accept 'C1', 'c1', or just '1'
    cid = compose_id.strip().upper()
    if not cid.startswith("C"):
        cid = f"C{cid}"

    # Load cached plan
    cached_plan_json = load_compose_plan(repo_root)
    if not cached_plan_json:
        typer.echo("No cached compose plan found.", err=True)
        typer.echo("Run 'hunknote compose' first to generate a plan.", err=True)
        raise typer.Exit(1)

    try:
        plan_data = json.loads(cached_plan_json)
    except json.JSONDecodeError:
        typer.echo("Failed to parse cached compose plan.", err=True)
        raise typer.Exit(1)

    # Find the target commit
    target_commit = None
    for entry in plan_data.get("commits", []):
        if entry.get("id", "").upper() == cid:
            target_commit = entry
            break

    if not target_commit:
        available = [c.get("id", "?") for c in plan_data.get("commits", [])]
        typer.echo(f"Compose commit '{cid}' not found in cached plan.", err=True)
        typer.echo(f"Available IDs: {', '.join(available)}", err=True)
        raise typer.Exit(1)

    commit_hunks = target_commit.get("hunks", [])
    if not commit_hunks:
        typer.echo(f"Commit {cid} has no hunks assigned.", err=True)
        raise typer.Exit(1)

    # Load cached hunk IDs data
    hunk_ids_data = load_compose_hunk_ids(repo_root)
    if not hunk_ids_data:
        typer.echo("No cached hunk data found.", err=True)
        typer.echo("Run 'hunknote compose' first to generate a plan.", err=True)
        raise typer.Exit(1)

    # Build lookup: hunk_id -> hunk data
    hunk_lookup = {h["hunk_id"]: h for h in hunk_ids_data}

    # Collect hunks for this commit, grouped by file
    hunks_by_file: OrderedDict[str, list[dict]] = OrderedDict()
    missing_hunks = []
    for hid in commit_hunks:
        hunk_data = hunk_lookup.get(hid)
        if hunk_data:
            fpath = hunk_data["file"]
            if fpath not in hunks_by_file:
                hunks_by_file[fpath] = []
            hunks_by_file[fpath].append(hunk_data)
        else:
            missing_hunks.append(hid)

    if missing_hunks:
        typer.echo(f"Warning: {len(missing_hunks)} hunk(s) not found in cache: {', '.join(missing_hunks)}", err=True)

    if not hunks_by_file:
        typer.echo(f"No diff content available for {cid}.", err=True)
        raise typer.Exit(1)

    # Build the diff output
    title = target_commit.get("title", "")

    lines = [
        f"Compose {cid}: {title}",
        f"Hunks: {len(commit_hunks)} across {len(hunks_by_file)} file(s)",
        "=" * 72,
        "",
    ]

    for fpath, file_hunks in hunks_by_file.items():
        lines.append(f"diff --git a/{fpath} b/{fpath}")
        lines.append(f"--- a/{fpath}")
        lines.append(f"+++ b/{fpath}")
        for hunk_data in file_hunks:
            diff_content = hunk_data.get("diff", "")
            if diff_content:
                lines.append(diff_content)
            lines.append("")

    diff_text = "\n".join(lines)

    # Colorize diff output
    diff_text = colorize_diff(diff_text)

    # Display in a scrollable pager
    show_in_pager(diff_text)


def _build_hunk_ids_data(
    inventory: dict,
    _file_diffs: list,
    plan,
) -> list[dict]:
    """Build hunk IDs data for the hunknote_hunk_ids.json file.

    Args:
        inventory: Dictionary mapping hunk ID to HunkRef.
        _file_diffs: List of FileDiff objects.
        plan: The ComposePlan object.

    Returns:
        List of hunk data dictionaries sorted by hunk ID.
    """
    # Build mapping of hunk ID to commit ID
    hunk_to_commit: dict[str, str] = {}
    for planned in plan.commits:
        for h_id in planned.hunks:
            hunk_to_commit[h_id] = planned.id

    # Build hunk data list
    hunk_ids_data = []
    for hunk_id, hunk in inventory.items():
        # Get the diff content (the lines of the hunk)
        diff_lines = "\n".join(hunk.lines)

        hunk_data = {
            "hunk_id": hunk_id,
            "file": hunk.file_path,
            "commit_id": hunk_to_commit.get(hunk_id, "unassigned"),
            "header": hunk.header,
            "diff": diff_lines,
        }
        hunk_ids_data.append(hunk_data)

    # Sort by hunk ID (extract numeric part for proper sorting)
    def sort_key(h):
        # Extract numeric part from hunk ID like "H1_abc123" -> 1
        h_id_str = h["hunk_id"]
        try:
            num_part = int(h_id_str.split("_")[0][1:])  # "H1_abc" -> 1
            return num_part
        except (ValueError, IndexError):
            return 0

    hunk_ids_data.sort(key=sort_key)

    return hunk_ids_data


def _build_agent_metadata(agent_result) -> dict:
    """Build agent metadata dict for ComposeCacheMetadata.

    Args:
        agent_result: ComposeAgentResult from the agent pipeline.

    Returns:
        Dictionary with agent info for the metadata JSON.
    """
    total_edges = sum(len(v) for v in agent_result.graph.values())
    languages = list(set(
        s.language for s in agent_result.symbol_analyses.values()
    ))

    cp_valid = sum(1 for _, r in agent_result.checkpoint_results if r.valid)
    cp_invalid = sum(1 for _, r in agent_result.checkpoint_results if not r.valid)

    # Find total duration from trace log
    total_duration = None
    for entry in reversed(agent_result.trace_log):
        if entry.get("phase") == "agent_complete":
            total_duration = entry.get("duration_s")
            break

    return {
        "mode": "agent",
        "symbols_extracted": len(agent_result.symbol_analyses),
        "graph_edges": total_edges,
        "renames_detected": len(agent_result.renames),
        "groups_formed": len(agent_result.groups),
        "large_hunks": len(agent_result.large_hunk_annotations),
        "languages": languages,
        "checkpoints": {
            "total": len(agent_result.checkpoint_results),
            "valid": cp_valid,
            "invalid": cp_invalid,
        },
        "total_duration_s": total_duration,
    }


def _build_graph_data(agent_result) -> dict:
    """Build graph data dict for hunknote_hunk_graph.json.

    Args:
        agent_result: ComposeAgentResult from the agent pipeline.

    Returns:
        Dictionary with graph edges, components, and renames.
    """
    # Edges: convert set values to sorted lists for JSON
    edges = {}
    for source, targets in agent_result.graph.items():
        edges[source] = sorted(targets)

    # Build nodes with file info
    nodes = {}
    for hunk_id, symbols in agent_result.symbol_analyses.items():
        nodes[hunk_id] = {
            "file": symbols.file_path,
            "language": symbols.language,
            "defines": sorted(symbols.defines),
            "references": sorted(symbols.references),
        }

    # Groups (connected components after merge)
    groups = []
    for i, g in enumerate(agent_result.groups):
        groups.append({
            "group_id": i + 1,
            "hunks": g.hunk_ids,
            "files": g.files,
        })

    # Renames
    renames = [
        {"old": r.old_name, "new": r.new_name, "hunk": r.defining_hunk}
        for r in agent_result.renames
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "groups": groups,
        "renames": renames,
        "total_edges": sum(len(v) for v in agent_result.graph.values()),
        "total_nodes": len(nodes),
    }


def _build_symbols_data(agent_result) -> dict:
    """Build symbols data dict for hunknote_hunk_symbols.json.

    Args:
        agent_result: ComposeAgentResult from the agent pipeline.

    Returns:
        Dictionary mapping hunk ID to symbol details.
    """
    symbols = {}
    for hunk_id, s in agent_result.symbol_analyses.items():
        symbols[hunk_id] = {
            "file_path": s.file_path,
            "language": s.language,
            "defines": sorted(s.defines),
            "removes": sorted(s.removes),
            "modifies": sorted(s.modifies),
            "references": sorted(s.references),
            "imports_added": sorted(s.imports_added),
            "imports_removed": sorted(s.imports_removed),
            "exports_added": sorted(s.exports_added),
            "exports_removed": sorted(s.exports_removed),
        }

    # Add large hunk annotations
    large_hunks = {}
    for hunk_id, ann in agent_result.large_hunk_annotations.items():
        large_hunks[hunk_id] = {
            "is_new_file": ann.is_new_file,
            "is_large_hunk": ann.is_large_hunk,
            "line_count": ann.line_count,
            "definitions_count": ann.definitions_count,
            "definitions": ann.definitions,
            "has_multiple_logical_sections": ann.has_multiple_logical_sections,
            "estimated_sections": ann.estimated_sections,
        }

    return {
        "symbols": symbols,
        "large_hunks": large_hunks,
    }


def _build_trace_data(agent_result) -> dict:
    """Build trace data dict for hunknote_agent_trace.json.

    Args:
        agent_result: ComposeAgentResult from the agent pipeline.

    Returns:
        Dictionary with the full agent execution trace.
    """
    return {
        "agent": "compose_agent",
        "used_agent": agent_result.used_agent,
        "phases": agent_result.trace_log,
    }


def _render_graph(repo_root: Path) -> None:
    """Render the hunk dependency graph on the terminal.

    Reads from .hunknote/hunknote_hunk_graph.json and renders an
    ASCII-art graph with nodes, edges, and groups.

    Args:
        repo_root: The root directory of the git repository.
    """
    graph_data = load_compose_hunk_graph(repo_root)
    if not graph_data:
        typer.echo("\nNo hunk dependency graph found.", err=True)
        typer.echo("Run 'hunknote compose --agent' to generate it.\n", err=True)
        return

    nodes = graph_data.get("nodes", {})
    edges = graph_data.get("edges", {})
    groups = graph_data.get("groups", [])
    renames = graph_data.get("renames", [])
    total_edges = graph_data.get("total_edges", 0)

    typer.echo("")
    typer.echo("=" * 64)
    typer.echo("              HUNK DEPENDENCY GRAPH")
    typer.echo("=" * 64)
    typer.echo("")

    # Summary
    typer.echo(f"  Nodes: {len(nodes)}    Edges: {total_edges}    "
               f"Groups: {len(groups)}    Renames: {len(renames)}")
    typer.echo("")

    # Render groups with their hunks and dependencies
    for group in groups:
        gid = group.get("group_id", "?")
        g_hunks = group.get("hunks", [])
        g_files = group.get("files", [])

        typer.echo(f"  ┌─ Group {gid}  ({len(g_hunks)} hunks, {len(g_files)} files)")

        for hid in g_hunks:
            node = nodes.get(hid, {})
            file_path = node.get("file", "?")
            lang = node.get("language", "?")
            defines = node.get("defines", [])
            refs = node.get("references", [])

            # Node line
            deps = edges.get(hid, [])
            dep_str = ""
            if deps:
                dep_str = f"  → {', '.join(deps)}"

            defs_str = ""
            if defines:
                defs_str = f"  [def: {', '.join(defines[:3])}{'...' if len(defines) > 3 else ''}]"

            typer.echo(f"  │  {hid}  {file_path} ({lang}){defs_str}{dep_str}")

        typer.echo(f"  │  Files: {', '.join(g_files)}")
        typer.echo(f"  └{'─' * 60}")
        typer.echo("")

    # Renames
    if renames:
        typer.echo("  Renames detected:")
        for r in renames:
            typer.echo(f"    {r.get('old', '?')} → {r.get('new', '?')}  (in {r.get('hunk', '?')})")
        typer.echo("")

    # Edge list (compact)
    if edges:
        typer.echo("  Dependency edges:")
        for source, targets in sorted(edges.items()):
            for target in targets:
                src_file = nodes.get(source, {}).get("file", "?")
                tgt_file = nodes.get(target, {}).get("file", "?")
                typer.echo(f"    {source} ({src_file})  →  {target} ({tgt_file})")
        typer.echo("")

    typer.echo("=" * 64)
    typer.echo("")


def _render_trace(repo_root: Path) -> None:
    """Render the agent trace logs on the terminal.

    Reads from .hunknote/hunknote_agent_trace.json and renders a
    user-friendly timeline of agent execution phases.

    Args:
        repo_root: The root directory of the git repository.
    """
    trace_data = load_compose_agent_trace(repo_root)
    if not trace_data:
        typer.echo("\nNo agent trace found.", err=True)
        typer.echo("Run 'hunknote compose --agent' to generate it.\n", err=True)
        return

    phases = trace_data.get("phases", [])
    if not phases:
        typer.echo("\nAgent trace is empty.\n", err=True)
        return

    typer.echo("")
    typer.echo("=" * 64)
    typer.echo("              AGENT EXECUTION TRACE")
    typer.echo("=" * 64)
    typer.echo("")

    # Status icons
    status_icons = {
        "completed": "✓",
        "skipped": "○",
        "activated": "●",
        "fallback": "⚠",
    }

    for i, entry in enumerate(phases):
        phase = entry.get("phase", "unknown")
        status = entry.get("status", "unknown")
        duration = entry.get("duration_s", 0)
        timestamp = entry.get("timestamp", "")
        details = entry.get("details", {})

        icon = status_icons.get(status, "?")
        phase_label = phase.replace("_", " ").title()

        # Duration display
        dur_str = f"  ({duration:.3f}s)" if duration > 0 else ""

        # Phase header
        typer.echo(f"  {icon}  {phase_label}  [{status}]{dur_str}")

        # Phase details (indented)
        if details:
            for key, value in details.items():
                if isinstance(value, list):
                    if len(value) <= 5:
                        typer.echo(f"     │  {key}: {value}")
                    else:
                        typer.echo(f"     │  {key}: [{len(value)} items]")
                elif isinstance(value, dict):
                    typer.echo(f"     │  {key}:")
                    for k2, v2 in value.items():
                        typer.echo(f"     │    {k2}: {v2}")
                else:
                    typer.echo(f"     │  {key}: {value}")

        # Separator between phases (except last)
        if i < len(phases) - 1:
            typer.echo(f"     │")

    typer.echo("")
    typer.echo("=" * 64)
    typer.echo("")


