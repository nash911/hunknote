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
from hunknote.llm import LLMError, MissingAPIKeyError
from hunknote.llm.base import parse_json_response, JSONParseError
from hunknote.styles import StyleProfile
from hunknote.cli.utils import (
    get_effective_style_config,
    colorize_diff,
    show_in_pager,
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
) -> None:
    """Split staged changes into a clean commit stack.

    Analyzes staged changes and proposes splitting them into multiple
    atomic commits. By default, only shows the plan without
    modifying git state.

    Use --commit to execute the plan and create the commits.
    """
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
        create_snapshot,
        restore_from_snapshot,
        execute_commit,
        cleanup_temp_files,
        ComposePlan,
        ComposeExecutionError,
        COMPOSE_SYSTEM_PROMPT,
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

        # Get branch and recent commits for context
        branch = get_branch()
        recent_commits_result = subprocess.run(
            ["git", "log", "-n", "5", "--pretty=%s"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        recent_commits = recent_commits_result.stdout.strip().split("\n") if recent_commits_result.returncode == 0 else []


        # Get diff of staged changes only (like the main hunknote command)
        diff_result = subprocess.run(
            ["git", "diff", "--cached", "--patch"],
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
        cached_metadata = None

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
                except Exception as e:
                    typer.echo(f"Failed to load cached plan: {e}", err=True)
                    typer.echo("Regenerating...", err=True)
                    plan = None

        if plan is None:
            # Generate plan via LLM
            typer.echo("Generating compose plan...", err=True)

            # Build prompt
            prompt = build_compose_prompt(
                file_diffs=file_diffs,
                branch=branch,
                recent_commits=recent_commits,
                style=effective_profile.value,
                max_commits=max_commits,
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

            typer.echo("=" * 60, err=True)
            typer.echo("", err=True)

        # Try to auto-correct hallucinated hunk IDs before validation
        corrections_made, corrections_log = try_correct_hunk_ids(plan, inventory)
        if corrections_made:
            typer.echo("Auto-corrected LLM hunk ID errors:", err=True)
            for correction in corrections_log:
                typer.echo(f"  - {correction}", err=True)
            typer.echo("", err=True)

        # Validate plan
        validation_errors = validate_plan(plan, inventory, max_commits)
        if validation_errors:
            typer.echo("Plan validation failed:", err=True)
            for error in validation_errors:
                typer.echo(f"  - {error}", err=True)
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
            typer.echo(f"     ({len(planned_commit.hunks)} hunks)")

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

