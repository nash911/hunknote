"""CLI entry point for hunknote."""

import difflib
import hashlib
import json
import os
import shutil
import subprocess
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from hunknote.cache import (
    CacheMetadata,
    compute_context_hash,
    extract_staged_files,
    get_diff_preview,
    get_message_file,
    invalidate_cache,
    is_cache_valid,
    load_cache_metadata,
    load_cached_message,
    load_raw_json_response,
    save_cache,
    update_message_cache,
    update_metadata_overrides,
)
from hunknote.git_ctx import (
    GitError,
    NoStagedChangesError,
    build_context_bundle,
    get_repo_root,
    get_staged_diff,
    get_status,
    get_branch,
)
from hunknote.llm import LLMError, MissingAPIKeyError, generate_commit_json
from hunknote.llm.base import parse_json_response, JSONParseError, validate_commit_json
from hunknote.user_config import (
    add_ignore_pattern,
    get_ignore_patterns,
    remove_ignore_pattern,
    get_repo_style_config,
    set_repo_style_profile,
)
from hunknote.styles import (
    StyleProfile,
    StyleConfig,
    PROFILE_DESCRIPTIONS,
    load_style_config_from_dict,
    render_commit_message_styled,
    extract_ticket_from_branch,
    infer_commit_type,
)
from hunknote.scope import (
    ScopeStrategy,
    ScopeConfig,
    infer_scope,
    load_scope_config_from_dict,
)
from hunknote import global_config
from hunknote.config import LLMProvider, AVAILABLE_MODELS, API_KEY_ENV_VARS

app = typer.Typer(
    name="hunknote",
    help="AI-powered git commit message generator using LLMs",
    add_completion=False,
)

# Subcommand group for ignore pattern management
ignore_app = typer.Typer(
    name="ignore",
    help="Manage ignore patterns in .hunknote/config.yaml",
    add_completion=False,
)
app.add_typer(ignore_app, name="ignore")

# Subcommand group for configuration management
config_app = typer.Typer(
    name="config",
    help="Manage global hunknote configuration in ~/.hunknote/",
    add_completion=False,
)
app.add_typer(config_app, name="config")

# Subcommand group for style profile management
style_app = typer.Typer(
    name="style",
    help="Manage commit message style profiles",
    add_completion=False,
)
app.add_typer(style_app, name="style")


@app.command()
def commit(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Bypass confirmation prompt and commit immediately",
    ),
) -> None:
    """Commit staged changes using the generated message.

    Uses the cached commit message from the last 'hunknote' run.
    If no cached message exists, generates a new one first.
    """
    from hunknote.config import load_config
    load_config()

    try:
        repo_root = get_repo_root()

        # Check if we have a cached message
        metadata = load_cache_metadata(repo_root)
        message = load_cached_message(repo_root)
        message_file = get_message_file(repo_root)

        if metadata and message:
            # Use existing cached message
            typer.echo("Using cached commit message...", err=True)
            typer.echo("")
            typer.echo("=" * 60)
            typer.echo(message)
            typer.echo("=" * 60)

            # Ask for confirmation unless --yes flag is used
            if not yes:
                typer.echo("")
                confirm = typer.prompt(
                    "Commit with this message? [Y/n]",
                    default="y",
                    show_default=False,
                )
                if confirm.lower() not in ("y", "yes", ""):
                    typer.echo("Commit cancelled.", err=True)
                    raise typer.Exit(0)

            typer.echo("")
            typer.echo("Committing...", err=True)
            result = subprocess.run(
                ["git", "commit", "-F", str(message_file)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                typer.echo("Commit successful!", err=True)
                typer.echo(result.stdout)
                invalidate_cache(repo_root)
            else:
                typer.echo("Commit failed!", err=True)
                typer.echo(result.stderr, err=True)
                raise typer.Exit(1)
        else:
            # No cached message - prompt user to generate one first
            typer.echo("No cached commit message found.", err=True)
            typer.echo("Run 'hunknote' first to generate a commit message.", err=True)
            raise typer.Exit(1)

    except GitError as e:
        typer.echo(f"Git error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def compose(
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
        compute_context_hash,
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
        StyleProfile,
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

        # Check for untracked files and warn
        untracked_result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if untracked_result.stdout.strip():
            untracked_files = untracked_result.stdout.strip().split("\n")
            typer.echo(f"Warning: {len(untracked_files)} untracked file(s) not included.", err=True)
            typer.echo("Add them first with: git add -N <file> (or git add <file>)", err=True)
            typer.echo("", err=True)

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
        style_config = _get_effective_style_config()
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
            type_str = f"{planned_commit.type}: " if planned_commit.type else ""
            scope_str = f"({planned_commit.scope}) " if planned_commit.scope else ""
            typer.echo(f"  {i}. {type_str}{scope_str}{planned_commit.title}")
            typer.echo(f"     ({len(planned_commit.hunks)} hunks)")

        # Print detailed previews
        typer.echo("")
        typer.echo("-" * 60)
        typer.echo("Commit Message Previews")
        typer.echo("-" * 60)

        style_config = _get_effective_style_config()
        effective_profile = override_style or style_config.profile

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

            # Render message
            rendered = render_commit_message_styled(
                extended_json,
                style_config,
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


def _generate_message_diff(original: str, current: str) -> str:
    """Generate a git diff-style comparison between two messages.

    Args:
        original: The original AI-generated message.
        current: The current (possibly edited) message.

    Returns:
        A git diff-style string showing the differences.
    """
    original_lines = original.strip().splitlines(keepends=True)
    current_lines = current.strip().splitlines(keepends=True)

    # Add newlines if missing for proper diff output
    if original_lines and not original_lines[-1].endswith("\n"):
        original_lines[-1] += "\n"
    if current_lines and not current_lines[-1].endswith("\n"):
        current_lines[-1] += "\n"

    diff = difflib.unified_diff(
        original_lines,
        current_lines,
        fromfile="a/original_message",
        tofile="b/current_message",
        lineterm="",
    )

    return "".join(diff)


def _get_current_branch_safe() -> str:
    """Safely get the current branch name without raising errors.

    Returns:
        The branch name, or 'unknown' if it cannot be determined.
    """
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return "unknown"
    except Exception:
        return "unknown"



def _find_editor() -> list[str]:
    """Find an available text editor.

    Preference order:
    1. gedit --wait (if gedit is available)
    2. $EDITOR environment variable
    3. nano as fallback

    Returns:
        List of command parts to run the editor.
    """
    # Try gedit first
    if shutil.which("gedit"):
        return ["gedit", "--wait"]

    # Try $EDITOR
    editor = os.environ.get("EDITOR")
    if editor:
        return [editor]

    # Fallback to nano
    if shutil.which("nano"):
        return ["nano"]

    # Last resort: vi
    return ["vi"]


def _open_editor(file_path: Path) -> None:
    """Open the file in an editor and wait for it to close.

    Args:
        file_path: Path to the file to edit.
    """
    editor_cmd = _find_editor()

    typer.echo(f"Opening editor: {' '.join(editor_cmd)}")

    try:
        # Run the editor and wait for it to complete
        result = subprocess.run(
            editor_cmd + [str(file_path)],
            check=False,
        )

        if result.returncode != 0:
            typer.echo(f"Warning: Editor exited with code {result.returncode}", err=True)

    except FileNotFoundError:
        typer.echo(f"Error: Editor not found: {editor_cmd[0]}", err=True)
        raise typer.Exit(1)


def _process_intent_options(intent: Optional[str], intent_file: Optional[Path]) -> Optional[str]:
    """Process --intent and --intent-file options.

    Args:
        intent: Direct intent text from --intent option.
        intent_file: Path to file containing intent from --intent-file option.

    Returns:
        Combined intent content, or None if no intent provided.

    Raises:
        typer.Exit: If intent_file cannot be read.
    """
    parts = []

    # Add --intent content first
    if intent:
        trimmed = intent.strip()
        if trimmed:
            parts.append(trimmed)

    # Add --intent-file content
    if intent_file:
        if not intent_file.exists():
            typer.echo(f"Error: Intent file not found: {intent_file}", err=True)
            raise typer.Exit(1)
        try:
            file_content = intent_file.read_text().strip()
            if file_content:
                parts.append(file_content)
        except Exception as e:
            typer.echo(f"Error reading intent file: {e}", err=True)
            raise typer.Exit(1)

    # Combine with blank line if both provided
    if not parts:
        return None

    return "\n\n".join(parts)


def _compute_intent_fingerprint(intent_content: Optional[str]) -> Optional[str]:
    """Compute a fingerprint for intent content for cache keying.

    Args:
        intent_content: The intent content string.

    Returns:
        A 12-character hex fingerprint, or None if no intent.
    """
    if not intent_content:
        return None

    return hashlib.sha256(intent_content.encode("utf-8")).hexdigest()[:12]


def _inject_intent_into_context(context_bundle: str, intent_content: str) -> str:
    """Inject the [INTENT] block into the context bundle.

    The intent block is placed after [FILE_CHANGES] and before [LAST_5_COMMITS].

    Args:
        context_bundle: The original context bundle string.
        intent_content: The intent content to inject.

    Returns:
        The context bundle with the [INTENT] block inserted.
    """
    intent_block = f"\n[INTENT]\n{intent_content}\n"

    # Insert before [LAST_5_COMMITS] section
    if "[LAST_5_COMMITS]" in context_bundle:
        return context_bundle.replace(
            "[LAST_5_COMMITS]",
            f"{intent_block}\n[LAST_5_COMMITS]"
        )

    # Fallback: append before [STAGED_DIFF] if LAST_5_COMMITS not found
    if "[STAGED_DIFF]" in context_bundle:
        return context_bundle.replace(
            "[STAGED_DIFF]",
            f"{intent_block}\n[STAGED_DIFF]"
        )

    # Last resort: append at the end
    return context_bundle + intent_block


def _display_debug_info(
    _repo_root: Path,
    metadata: CacheMetadata,
    current_message: str,
    cache_valid: bool,
    intent_content: Optional[str] = None,
) -> None:
    """Display debug information about the cache.

    Args:
        _repo_root: The root directory of the git repository.
        metadata: The cache metadata.
        current_message: The current commit message (may be edited).
        cache_valid: Whether the cache is currently valid.
        intent_content: The intent content if provided.
    """
    typer.echo("=" * 60)
    typer.echo("                  HUNKNOTE DEBUG INFO")
    typer.echo("=" * 60)
    typer.echo()

    # Cache status
    status = "VALID (using cached message)" if cache_valid else "INVALID (will regenerate)"
    typer.echo(f"Cache Status: {status}")
    typer.echo(f"Cache Key: {metadata.context_hash[:16]}...")

    # Parse and format timestamp
    try:
        generated_dt = datetime.fromisoformat(metadata.generated_at)
        formatted_time = generated_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, AttributeError):
        formatted_time = metadata.generated_at

    typer.echo(f"Generated At: {formatted_time}")
    typer.echo(f"LLM Model: {metadata.model}")
    typer.echo()

    # Token and character counts
    typer.echo("Usage Statistics:")
    typer.echo(f"  Tokens:     {metadata.input_tokens:,} input / {metadata.output_tokens:,} output")
    if metadata.input_chars > 0 or metadata.prompt_chars > 0 or metadata.output_chars > 0:
        typer.echo(f"  Characters: {metadata.input_chars:,} context / {metadata.prompt_chars:,} prompt / {metadata.output_chars:,} output")
    typer.echo()

    # Staged files
    typer.echo("Staged Files:")
    for f in metadata.staged_files:
        typer.echo(f"  - {f}")
    typer.echo()

    # Intent info (if provided)
    if intent_content:
        # Show first ~80 chars plus total length (as per spec)
        preview = intent_content[:80]
        if len(intent_content) > 80:
            preview += "..."
        typer.echo(f"Intent: {preview} ({len(intent_content)} chars)")
        typer.echo()
    else:
        typer.echo("Intent: (not provided)")
        typer.echo()

    # Diff preview
    typer.echo("Diff Preview:")
    for line in metadata.diff_preview.split("\n")[:15]:
        typer.echo(f"  {line}")
    if len(metadata.diff_preview.split("\n")) > 15:
        typer.echo("  ...")
    typer.echo()

    # Message edit status
    if current_message.strip() != metadata.original_message.strip():
        typer.echo("Message Edit Status: MODIFIED")
        typer.echo()
        typer.echo("Message Diff:")
        diff_output = _generate_message_diff(metadata.original_message, current_message)
        if diff_output:
            for line in diff_output.splitlines():
                typer.echo(f"  {line}")
        else:
            typer.echo("  (no visible differences)")
    else:
        typer.echo("Message Edit Status: UNMODIFIED")
        typer.echo()
        typer.echo("Current Message:")
        for line in current_message.strip().split("\n"):
            typer.echo(f"  {line}")

    typer.echo()
    typer.echo("=" * 60)


# ============================================================
# Ignore pattern management subcommands
# ============================================================


@ignore_app.command("list")
def ignore_list() -> None:
    """Show all ignore patterns in .hunknote/config.yaml."""
    try:
        repo_root = get_repo_root()
        patterns = get_ignore_patterns(repo_root)

        typer.echo("Ignore patterns in .hunknote/config.yaml:")
        typer.echo()
        if patterns:
            for pattern in patterns:
                typer.echo(f"  - {pattern}")
            typer.echo()
            typer.echo(f"Total: {len(patterns)} pattern(s)")
        else:
            typer.echo("  (no patterns configured)")
        typer.echo()
        typer.echo("These files are excluded from the diff sent to the LLM.")

    except GitError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@ignore_app.command("add")
def ignore_add(
    pattern: str = typer.Argument(
        ...,
        help="File pattern to add (e.g., *.log, build/*, package-lock.json)",
    ),
) -> None:
    """Add a pattern to the ignore list."""
    try:
        repo_root = get_repo_root()

        # Check if pattern already exists
        patterns = get_ignore_patterns(repo_root)
        if pattern in patterns:
            typer.echo(f"Pattern already exists: {pattern}")
            raise typer.Exit(0)

        add_ignore_pattern(repo_root, pattern)
        typer.echo(f"Added ignore pattern: {pattern}")

    except GitError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@ignore_app.command("remove")
def ignore_remove(
    pattern: str = typer.Argument(
        ...,
        help="File pattern to remove from the ignore list",
    ),
) -> None:
    """Remove a pattern from the ignore list."""
    try:
        repo_root = get_repo_root()

        if remove_ignore_pattern(repo_root, pattern):
            typer.echo(f"Removed ignore pattern: {pattern}")
        else:
            typer.echo(f"Pattern not found: {pattern}", err=True)
            raise typer.Exit(1)

    except GitError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


# ============================================================
# Global configuration management subcommands
# ============================================================


@app.command("init")
def init_config() -> None:
    """Initialize hunknote global configuration interactively."""
    typer.echo("Welcome to hunknote! Let's set up your configuration.")
    typer.echo()

    # Check if already configured
    if global_config.is_configured():
        overwrite = typer.confirm(
            "Configuration already exists at ~/.hunknote/config.yaml. Overwrite?",
            default=False
        )
        if not overwrite:
            typer.echo("Keeping existing configuration.")
            raise typer.Exit(0)

    # Select provider
    typer.echo("Available LLM providers:")
    providers = list(LLMProvider)
    for i, provider in enumerate(providers, 1):
        typer.echo(f"  {i}. {provider.value}")

    provider_choice = typer.prompt(
        "Select a provider (1-7)",
        type=int,
        default=3  # Google is index 2 (0-indexed)
    )

    if provider_choice < 1 or provider_choice > len(providers):
        typer.echo("Invalid choice. Aborting.", err=True)
        raise typer.Exit(1)

    selected_provider = providers[provider_choice - 1]

    # Select model
    models = AVAILABLE_MODELS[selected_provider]
    typer.echo()
    typer.echo(f"Available models for {selected_provider.value}:")
    for i, model in enumerate(models, 1):
        typer.echo(f"  {i}. {model}")

    model_choice = typer.prompt(
        f"Select a model (1-{len(models)})",
        type=int,
        default=1
    )

    if model_choice < 1 or model_choice > len(models):
        typer.echo("Invalid choice. Aborting.", err=True)
        raise typer.Exit(1)

    selected_model = models[model_choice - 1]

    # Get API key
    typer.echo()
    env_var = API_KEY_ENV_VARS[selected_provider]
    api_key = typer.prompt(
        f"Enter your {selected_provider.value} API key",
        hide_input=True
    )

    # Save configuration
    try:
        global_config.set_provider_and_model(selected_provider, selected_model)
        global_config.save_credential(env_var, api_key)

        typer.echo()
        typer.echo("✓ Configuration saved to ~/.hunknote/")
        typer.echo(f"  Provider: {selected_provider.value}")
        typer.echo(f"  Model: {selected_model}")
        typer.echo()
        typer.echo("You can now use 'hunknote' in any git repository!")

    except Exception as e:
        typer.echo(f"Error saving configuration: {e}", err=True)
        raise typer.Exit(1)


@config_app.command("show")
def config_show() -> None:
    """Show current global configuration."""
    try:
        if not global_config.is_configured():
            typer.echo("No configuration found. Run 'hunknote init' to set up.")
            return

        config = global_config.load_global_config()

        typer.echo("Current hunknote configuration (~/.hunknote/config.yaml):")
        typer.echo()
        typer.echo(f"  Provider: {config.get('provider', 'not set')}")
        typer.echo(f"  Model: {config.get('model', 'not set')}")
        typer.echo(f"  Max Tokens: {config.get('max_tokens', 1500)}")
        typer.echo(f"  Temperature: {config.get('temperature', 0.3)}")

        editor = config.get('editor')
        if editor:
            typer.echo(f"  Editor: {editor}")

        default_ignore = config.get('default_ignore', [])
        if default_ignore:
            typer.echo()
            typer.echo("  Default Ignore Patterns:")
            for pattern in default_ignore:
                typer.echo(f"    - {pattern}")

        typer.echo()

        # Check for API key
        provider_str = config.get('provider')
        if provider_str:
            try:
                provider = LLMProvider(provider_str)
                env_var = API_KEY_ENV_VARS[provider]
                api_key = global_config.get_credential(env_var)

                if api_key:
                    masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
                    typer.echo(f"  API Key ({env_var}): {masked_key}")
                else:
                    typer.echo(f"  API Key ({env_var}): not set")
            except (ValueError, KeyError):
                pass

    except Exception as e:
        typer.echo(f"Error reading configuration: {e}", err=True)
        raise typer.Exit(1)


@config_app.command("set-key")
def config_set_key(
    provider: str = typer.Argument(
        ...,
        help="Provider name (anthropic, openai, google, mistral, cohere, groq, openrouter)"
    )
) -> None:
    """Set or update an API key for a provider."""
    try:
        # Validate provider
        try:
            llm_provider = LLMProvider(provider.lower())
        except ValueError:
            typer.echo(f"Invalid provider: {provider}", err=True)
            typer.echo("Valid providers: anthropic, openai, google, mistral, cohere, groq, openrouter")
            raise typer.Exit(1)

        env_var = API_KEY_ENV_VARS[llm_provider]

        typer.echo(f"Setting API key for {llm_provider.value}")
        api_key = typer.prompt(f"Enter your {llm_provider.value} API key", hide_input=True)

        global_config.ensure_global_config_dir()
        global_config.save_credential(env_var, api_key)

        typer.echo(f"✓ API key saved for {llm_provider.value}")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@config_app.command("set-provider")
def config_set_provider(
    provider: str = typer.Argument(
        ...,
        help="Provider name (anthropic, openai, google, mistral, cohere, groq, openrouter)"
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="Model name (optional, will prompt if not provided)"
    )
) -> None:
    """Set the active LLM provider and model."""
    try:
        # Validate provider
        try:
            llm_provider = LLMProvider(provider.lower())
        except ValueError:
            typer.echo(f"Invalid provider: {provider}", err=True)
            typer.echo("Valid providers: anthropic, openai, google, mistral, cohere, groq, openrouter")
            raise typer.Exit(1)

        # Get model
        if not model:
            models = AVAILABLE_MODELS[llm_provider]
            typer.echo(f"Available models for {llm_provider.value}:")
            for i, m in enumerate(models, 1):
                typer.echo(f"  {i}. {m}")

            model_choice = typer.prompt(f"Select a model (1-{len(models)})", type=int, default=1)
            if model_choice < 1 or model_choice > len(models):
                typer.echo("Invalid choice. Aborting.", err=True)
                raise typer.Exit(1)

            model = models[model_choice - 1]
        else:
            # Validate model
            if model not in AVAILABLE_MODELS[llm_provider]:
                typer.echo(f"Warning: {model} is not in the list of known models for {llm_provider.value}")
                proceed = typer.confirm("Continue anyway?", default=False)
                if not proceed:
                    raise typer.Exit(0)

        global_config.set_provider_and_model(llm_provider, model)

        typer.echo(f"✓ Provider set to: {llm_provider.value}")
        typer.echo(f"✓ Model set to: {model}")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@config_app.command("list-providers")
def config_list_providers() -> None:
    """List all available LLM providers."""
    typer.echo("Available LLM providers:")
    typer.echo()
    for provider in LLMProvider:
        typer.echo(f"  • {provider.value}")
    typer.echo()
    typer.echo("Use 'hunknote config list-models <provider>' to see available models.")


@config_app.command("list-models")
def config_list_models(
    provider: str = typer.Argument(
        None,
        help="Provider name (optional, shows all if not provided)"
    )
) -> None:
    """List available models for a provider (or all providers)."""
    if provider:
        # Show models for specific provider
        try:
            llm_provider = LLMProvider(provider.lower())
        except ValueError:
            typer.echo(f"Invalid provider: {provider}", err=True)
            typer.echo("Valid providers: anthropic, openai, google, mistral, cohere, groq, openrouter")
            raise typer.Exit(1)

        models = AVAILABLE_MODELS[llm_provider]
        typer.echo(f"Available models for {llm_provider.value}:")
        typer.echo()
        for model in models:
            typer.echo(f"  • {model}")
        typer.echo()
    else:
        # Show all providers and their models
        for llm_provider in LLMProvider:
            models = AVAILABLE_MODELS[llm_provider]
            typer.echo(f"{llm_provider.value}:")
            for model in models:
                typer.echo(f"  • {model}")
            typer.echo()


# ============================================================
# Style profile management subcommands
# ============================================================


@style_app.command("list")
def style_list() -> None:
    """List available style profiles and show the current active profile."""
    # Get current profile from config (repo > global > default)
    current_profile = "default"

    try:
        repo_root = get_repo_root()
        repo_style = get_repo_style_config(repo_root)
        if repo_style.get("profile"):
            current_profile = repo_style["profile"]
            source = "repo"
        else:
            global_style = global_config.get_style_config()
            if global_style.get("profile"):
                current_profile = global_style["profile"]
                source = "global"
            else:
                source = "default"
    except GitError:
        global_style = global_config.get_style_config()
        if global_style.get("profile"):
            current_profile = global_style["profile"]
            source = "global"
        else:
            source = "default"

    typer.echo("Available commit style profiles:")
    typer.echo()

    for profile in StyleProfile:
        desc = PROFILE_DESCRIPTIONS[profile]
        marker = " ← active" if profile.value == current_profile else ""
        typer.echo(f"  • {desc['name']}{marker}")
        typer.echo(f"    {desc['description']}")
        typer.echo()

    typer.echo(f"Current profile: {current_profile} (from {source} config)")
    typer.echo()
    typer.echo("Use 'hunknote style show <profile>' for details.")
    typer.echo("Use 'hunknote style set <profile>' to change.")


@style_app.command("show")
def style_show(
    profile: str = typer.Argument(
        None,
        help="Profile name to show (default, blueprint, conventional, ticket, kernel)"
    )
) -> None:
    """Show details about a style profile."""
    if not profile:
        # Show current profile
        try:
            repo_root = get_repo_root()
            repo_style = get_repo_style_config(repo_root)
            profile = repo_style.get("profile") or global_config.get_style_profile() or "default"
        except GitError:
            profile = global_config.get_style_profile() or "default"

    # Validate profile
    try:
        style_profile = StyleProfile(profile.lower())
    except ValueError:
        typer.echo(f"Invalid profile: {profile}", err=True)
        typer.echo("Valid profiles: default, blueprint, conventional, ticket, kernel")
        raise typer.Exit(1)

    desc = PROFILE_DESCRIPTIONS[style_profile]

    typer.echo(f"Style Profile: {desc['name']}")
    typer.echo("=" * 50)
    typer.echo()
    typer.echo(f"Description: {desc['description']}")
    typer.echo()
    typer.echo("Format:")
    typer.echo("  " + desc['format'].replace('\n', '\n  '))
    typer.echo()
    typer.echo("Example:")
    typer.echo("  " + desc['example'].replace('\n', '\n  '))
    typer.echo()

    # Show profile-specific options
    if style_profile == StyleProfile.BLUEPRINT:
        typer.echo("Options (in config.yaml):")
        typer.echo("  style.blueprint.section_titles: [Changes, Implementation, ...]")
        typer.echo()
        typer.echo("Allowed section titles:")
        typer.echo("  Changes, Implementation, Testing, Documentation, Notes,")
        typer.echo("  Performance, Security, Config, API")
    elif style_profile == StyleProfile.CONVENTIONAL:
        typer.echo("Options (in config.yaml):")
        typer.echo("  style.conventional.types: [feat, fix, docs, ...]")
        typer.echo("  style.conventional.breaking_footer: true")
    elif style_profile == StyleProfile.TICKET:
        typer.echo("Options (in config.yaml):")
        typer.echo("  style.ticket.key_regex: '([A-Z][A-Z0-9]+-\\d+)'")
        typer.echo("  style.ticket.placement: prefix | suffix")
    elif style_profile == StyleProfile.KERNEL:
        typer.echo("Options (in config.yaml):")
        typer.echo("  style.kernel.subsystem_from_scope: true")


@style_app.command("set")
def style_set(
    profile: str = typer.Argument(
        ...,
        help="Profile name (default, blueprint, conventional, ticket, kernel)"
    ),
    repo: bool = typer.Option(
        False,
        "--repo",
        help="Set in repository config instead of global"
    )
) -> None:
    """Set the active style profile."""
    # Validate profile
    try:
        style_profile = StyleProfile(profile.lower())
    except ValueError:
        typer.echo(f"Invalid profile: {profile}", err=True)
        typer.echo("Valid profiles: default, blueprint, conventional, ticket, kernel")
        raise typer.Exit(1)

    if repo:
        try:
            repo_root = get_repo_root()
            set_repo_style_profile(repo_root, style_profile.value)
            typer.echo(f"✓ Style profile set to '{style_profile.value}' in repo config")
        except GitError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
    else:
        global_config.set_style_profile(style_profile.value)
        typer.echo(f"✓ Style profile set to '{style_profile.value}' in global config")


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

    lines = []
    lines.append(f"Compose {cid}: {title}")
    lines.append(f"Hunks: {len(commit_hunks)} across {len(hunks_by_file)} file(s)")
    lines.append("=" * 72)
    lines.append("")

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
    diff_text = _colorize_diff(diff_text)

    # Display in a scrollable pager
    _show_in_pager(diff_text)


def _colorize_diff(text: str) -> str:
    """Add ANSI color codes to diff lines like git diff.

    - Red for removed lines (-)
    - Green for added lines (+)
    - Cyan for hunk headers (@@)
    - Bold for diff/file header lines

    Args:
        text: Raw diff text.

    Returns:
        Colorized diff text with ANSI escape codes.
    """
    RED = "\033[31m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    colorized = []
    for line in text.split("\n"):
        if line.startswith("@@"):
            colorized.append(f"{CYAN}{line}{RESET}")
        elif line.startswith("---") or line.startswith("+++"):
            colorized.append(f"{BOLD}{line}{RESET}")
        elif line.startswith("-"):
            colorized.append(f"{RED}{line}{RESET}")
        elif line.startswith("+"):
            colorized.append(f"{GREEN}{line}{RESET}")
        elif line.startswith("diff --git"):
            colorized.append(f"{BOLD}{line}{RESET}")
        else:
            colorized.append(line)
    return "\n".join(colorized)


def _show_in_pager(text: str) -> None:
    """Display text in a scrollable pager.

    Uses the system pager (less) which supports arrow-key scrolling
    and q/Q to quit. Falls back to direct output if pager is unavailable.

    Args:
        text: The text to display.
    """
    # Prefer 'less' with options for color and raw control chars
    # noinspection PyArgumentList
    less_path = shutil.which("less")
    if less_path:
        try:
            proc = subprocess.Popen(
                [less_path, "-R", "--quit-if-one-screen"],
                stdin=subprocess.PIPE,
                encoding="utf-8",
            )
            proc.communicate(input=text)
            return
        except (OSError, BrokenPipeError):
            pass

    # Fallback: try 'more'
    more_path = shutil.which("more")
    if more_path:
        try:
            proc = subprocess.Popen(
                [more_path],
                stdin=subprocess.PIPE,
                encoding="utf-8",
            )
            proc.communicate(input=text)
            return
        except (OSError, BrokenPipeError):
            pass

    # Final fallback: print directly
    typer.echo(text)


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


def _get_effective_style_config() -> StyleConfig:
    """Get the effective style configuration (repo overrides global)."""
    # Start with defaults
    config_dict = {"style": {"profile": "default"}}

    # Merge global config
    global_style = global_config.get_style_config()
    if global_style:
        config_dict["style"].update(global_style)

    # Merge repo config (overrides global)
    try:
        repo_root = get_repo_root()
        repo_style = get_repo_style_config(repo_root)
        if repo_style:
            config_dict["style"].update(repo_style)
    except GitError:
        pass  # Not in a repo, use global only

    return load_style_config_from_dict(config_dict)


def _get_effective_scope_config() -> ScopeConfig:
    """Get the effective scope configuration (repo overrides global)."""
    from hunknote.user_config import get_repo_scope_config

    # Start with defaults
    config_dict: dict = {"scope": {}}

    # Merge global config
    global_scope = global_config.get_scope_config()
    if global_scope:
        config_dict["scope"].update(global_scope)

    # Merge repo config (overrides global)
    try:
        repo_root = get_repo_root()
        repo_scope = get_repo_scope_config(repo_root)
        if repo_scope:
            config_dict["scope"].update(repo_scope)
    except GitError:
        pass  # Not in a repo, use global only

    return load_scope_config_from_dict(config_dict)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    max_diff_chars: int = typer.Option(
        50000,
        "--max-diff-chars",
        help="Maximum characters for the staged diff",
    ),
    regenerate: bool = typer.Option(
        False,
        "--regenerate",
        "-r",
        help="Force regenerate the commit message, ignoring cache",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        help="Show full metadata of the cached hunknote message",
    ),
    show_json: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Show the raw JSON response from the LLM for debugging",
    ),
    edit: bool = typer.Option(
        False,
        "--edit",
        "-e",
        help="Open the generated message file in an editor for manual edits",
    ),
    style: Optional[str] = typer.Option(
        None,
        "--style",
        help="Override commit style profile (default, blueprint, conventional, ticket, kernel)",
    ),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        help="Force a scope for the commit message (use 'auto' for inference)",
    ),
    no_scope: bool = typer.Option(
        False,
        "--no-scope",
        help="Disable scope even if profile supports it",
    ),
    scope_strategy: Optional[str] = typer.Option(
        None,
        "--scope-strategy",
        help="Scope inference strategy (auto, monorepo, path-prefix, mapping, none)",
    ),
    ticket: Optional[str] = typer.Option(
        None,
        "--ticket",
        help="Force a ticket key (e.g., PROJ-123) for ticket-style commits",
    ),
    intent: Optional[str] = typer.Option(
        None,
        "--intent",
        "-i",
        help="Provide explicit intent/motivation for the commit (influences why/motivation framing)",
    ),
    intent_file: Optional[Path] = typer.Option(
        None,
        "--intent-file",
        help="Load intent text from a file",
    ),
) -> None:
    """Generate an AI-powered git commit message from staged changes."""
    # If a subcommand is invoked, don't run the default behavior
    if ctx.invoked_subcommand is not None:
        return

    # Load global configuration
    from hunknote.config import load_config
    load_config()

    # Validate and parse style override if provided
    override_style = None
    if style:
        try:
            override_style = StyleProfile(style.lower())
        except ValueError:
            typer.echo(f"Invalid style: {style}", err=True)
            typer.echo("Valid styles: default, blueprint, conventional, ticket, kernel")
            raise typer.Exit(1)

    # Validate scope strategy if provided
    override_scope_strategy = None
    if scope_strategy:
        try:
            override_scope_strategy = ScopeStrategy(scope_strategy.lower())
        except ValueError:
            typer.echo(f"Invalid scope strategy: {scope_strategy}", err=True)
            typer.echo("Valid strategies: auto, monorepo, path-prefix, mapping, none")
            raise typer.Exit(1)

    # Process intent options
    intent_content = _process_intent_options(intent, intent_file)

    try:
        # Step 1: Get repo root
        repo_root = get_repo_root()

        # Early exit for --debug and --json flags: show existing cache without regenerating
        # These flags should never trigger commit message generation
        if debug or show_json:
            metadata = load_cache_metadata(repo_root)
            if metadata is None:
                typer.echo("No cached commit message found.", err=True)
                typer.echo("Run 'hunknote' first to generate a commit message.", err=True)
                raise typer.Exit(1)

            message = load_cached_message(repo_root)
            if not message:
                typer.echo("No cached commit message found.", err=True)
                typer.echo("Run 'hunknote' first to generate a commit message.", err=True)
                raise typer.Exit(1)

            if show_json:
                typer.echo("\n[RAW LLM RESPONSE]", err=True)
                stored_json = load_raw_json_response(repo_root)
                if stored_json:
                    typer.echo(stored_json, err=True)
                else:
                    typer.echo("(Raw JSON not available)", err=True)
                typer.echo("")
                raise typer.Exit(0)

            if debug:
                # Get scope inference info for debug display
                status_output = get_status()
                staged_files = extract_staged_files(status_output)
                scope_config = _get_effective_scope_config()
                scope_result = None
                if scope_config.enabled:
                    scope_result = infer_scope(staged_files, scope_config)

                # Get LLM suggested scope from raw response
                llm_suggested_scope = None
                llm_raw_response = load_raw_json_response(repo_root)
                if llm_raw_response:
                    try:
                        parsed_json = parse_json_response(llm_raw_response)
                        llm_suggested_scope = parsed_json.get("scope")
                    except (JSONParseError, AttributeError):
                        pass

                # Get effective scope from metadata
                effective_scope = metadata.scope_override
                cli_scope_override = metadata.scope_override

                _display_debug_info(repo_root, metadata, message, True, intent_content)
                # Show scope inference info
                typer.echo("\n[SCOPE INFERENCE]", err=True)
                if scope_result:
                    typer.echo(f"  Strategy: {scope_result.strategy_used.value if scope_result.strategy_used else 'N/A'}", err=True)
                    typer.echo(f"  Inferred scope (heuristics): {scope_result.scope or 'None'}", err=True)
                    typer.echo(f"  Confidence: {scope_result.confidence:.0%}", err=True)
                    typer.echo(f"  Reason: {scope_result.reason}", err=True)
                else:
                    typer.echo("  Inferred scope (heuristics): None (inference not run)", err=True)
                typer.echo(f"  LLM suggested scope: {llm_suggested_scope or 'None'}", err=True)
                typer.echo(f"  CLI override: {cli_scope_override or 'None'}", err=True)
                typer.echo(f"  Final scope used: {effective_scope or 'None'}", err=True)
                raise typer.Exit(0)

        # Step 2: Build context bundle
        typer.echo("Collecting git context...", err=True)
        context_bundle = build_context_bundle(max_chars=max_diff_chars)

        # Inject intent block into context bundle if provided
        # The intent block is placed after FILE_CHANGES and before LAST_5_COMMITS
        if intent_content:
            # Insert [INTENT] block into the context bundle
            context_bundle = _inject_intent_into_context(context_bundle, intent_content)

        # Step 3: Get configurations
        style_config = _get_effective_style_config()
        scope_config = _get_effective_scope_config()
        effective_profile = override_style or style_config.profile

        # Apply scope strategy override if provided
        if override_scope_strategy:
            scope_config.strategy = override_scope_strategy

        # Step 4: Extract staged files and diff preview for metadata
        status_output = get_status()
        staged_files = extract_staged_files(status_output)
        staged_diff = get_staged_diff(max_chars=max_diff_chars)
        diff_preview = get_diff_preview(staged_diff, max_chars=500)

        # Step 5: Load saved rendering overrides from metadata and merge with CLI flags
        # CLI flags take precedence over saved overrides
        # Don't use saved overrides if regenerating (they will be cleared)
        saved_metadata = None if regenerate else load_cache_metadata(repo_root)

        # Determine effective CLI scope override
        # Priority: CLI flag > saved override in metadata (if not regenerating)
        cli_scope_override = None
        effective_no_scope = no_scope
        effective_ticket = ticket

        if no_scope:
            # User explicitly disabled scope via CLI
            cli_scope_override = None
            effective_no_scope = True
        elif scope and scope.lower() != "auto":
            # User provided explicit scope via CLI
            cli_scope_override = scope
        elif saved_metadata:
            # Use saved overrides from metadata if no CLI flags provided (and not regenerating)
            if saved_metadata.no_scope_override:
                effective_no_scope = True
            elif saved_metadata.scope_override:
                cli_scope_override = saved_metadata.scope_override
            if saved_metadata.ticket_override and not ticket:
                effective_ticket = saved_metadata.ticket_override

        # Run heuristics for debug info (but don't use as primary source)
        scope_result = None
        if scope_config.enabled and not effective_no_scope:
            scope_result = infer_scope(staged_files, scope_config)
            if scope_result.scope and debug:
                typer.echo(f"Inferred scope: {scope_result.scope} ({scope_result.reason})", err=True)

        # Compute intent fingerprint for cache key
        intent_fingerprint = _compute_intent_fingerprint(intent_content)

        # For cache hash, we include style and intent (which affect the LLM prompt).
        # We do NOT include scope, ticket, or no_scope in the hash because these are
        # rendering overrides applied after the LLM response - they don't affect what
        # the LLM generates. This allows users to run:
        #   hunknote --scope cli  # generates with scope override
        #   hunknote -d           # uses cached message (same LLM response)
        #   hunknote -e -c        # uses cached message for editing/committing
        # Intent IS included because it changes what the LLM generates.
        hash_input = f"{context_bundle}|style={effective_profile.value}|intent={intent_fingerprint or ''}"
        current_hash = compute_context_hash(hash_input)

        # Step 7: Check cache validity (unless --regenerate)
        cache_valid = not regenerate and is_cache_valid(repo_root, current_hash)

        if cache_valid:
            # Use cached commit message
            typer.echo("Using cached commit message...", err=True)
            _metadata = load_cache_metadata(repo_root)

            # Check if user provided any override flags that require re-rendering
            # If no overrides, use the saved message file directly (user may have edited it)
            has_override_flags = scope or no_scope or ticket

            if has_override_flags:
                # User provided override flags - need to re-render from JSON
                # Load raw JSON response from stored file
                llm_raw_response = load_raw_json_response(repo_root)
                # llm_suggested_scope = None

                if llm_raw_response:
                    try:
                        # Parse the cached LLM response to get ExtendedCommitJSON
                        parsed_json = parse_json_response(llm_raw_response)
                        extended_data = validate_commit_json(parsed_json, llm_raw_response)
                        llm_suggested_scope = extended_data.scope

                        # Determine effective scope: CLI override > LLM suggested > Heuristics
                        if effective_no_scope:
                            effective_scope = None
                        elif cli_scope_override:
                            effective_scope = cli_scope_override
                        elif llm_suggested_scope:
                            effective_scope = llm_suggested_scope
                        elif scope_result and scope_result.scope:
                            effective_scope = scope_result.scope
                        else:
                            effective_scope = None

                        # Strip redundant scope (same logic as new generation path)
                        commit_type = extended_data.type or extended_data.get_type("feat")
                        if effective_scope and commit_type:
                            redundant_scopes = {
                                "docs": ["docs", "documentation", "doc"],
                                "test": ["test", "tests", "testing"],
                                "ci": ["ci", "pipeline", "workflows"],
                                "build": ["build", "deps", "dependencies"],
                            }
                            if commit_type.lower() in redundant_scopes:
                                if effective_scope.lower() in redundant_scopes[commit_type.lower()]:
                                    effective_scope = None

                        # Apply scope to extended_data
                        extended_data.scope = effective_scope

                        # Apply ticket override if provided
                        if effective_ticket:
                            extended_data.ticket = effective_ticket

                        # Try to extract ticket from branch if not provided and using ticket style
                        if not extended_data.ticket and effective_profile == StyleProfile.TICKET:
                            try:
                                branch = get_branch()
                                extracted_ticket = extract_ticket_from_branch(branch, style_config.ticket_key_regex)
                                if extracted_ticket:
                                    extended_data.ticket = extracted_ticket
                            except Exception:
                                pass

                        # Infer commit type if using conventional/blueprint style and not provided
                        if effective_profile in (StyleProfile.CONVENTIONAL, StyleProfile.BLUEPRINT) and not extended_data.type:
                            inferred_type = infer_commit_type(staged_files)
                            if inferred_type:
                                extended_data.type = inferred_type

                        # Re-render the commit message with current flags
                        message = render_commit_message_styled(
                            data=extended_data,
                            config=style_config,
                            override_style=override_style,
                            override_scope=effective_scope,
                            override_ticket=effective_ticket,
                            no_scope=effective_no_scope,
                        )

                        # Update the message file with the re-rendered message
                        update_message_cache(repo_root, message)

                    except (JSONParseError, AttributeError):
                        # Fallback to stored message if parsing fails
                        message = load_cached_message(repo_root)
                else:
                    # No raw response stored, use cached message as-is
                    message = load_cached_message(repo_root)
            else:
                # No override flags - use the saved message directly
                # This preserves any manual edits the user may have made
                message = load_cached_message(repo_root)
        else:
            # Generate new message via LLM with the appropriate style
            typer.echo("Generating commit message...", err=True)
            llm_result = generate_commit_json(context_bundle, style=effective_profile.value)

            # llm_result.commit_json is already an ExtendedCommitJSON with all style fields
            extended_data = llm_result.commit_json

            # Capture LLM-suggested scope
            llm_suggested_scope = extended_data.scope

            # Capture raw LLM response for debugging
            llm_raw_response = llm_result.raw_response

            # Note: Rendering overrides will be saved in metadata when we save_cache below
            # If user provides CLI flags, they are included; otherwise they're cleared

            # Determine effective scope: CLI override > LLM suggested > Heuristics
            if effective_no_scope:
                effective_scope = None
            elif cli_scope_override:
                effective_scope = cli_scope_override
            elif llm_suggested_scope:
                effective_scope = llm_suggested_scope
            elif scope_result and scope_result.scope:
                effective_scope = scope_result.scope
            else:
                effective_scope = None

            # Strip redundant scope: when type matches scope, scope should be null
            # e.g., type="docs" with scope="docs" -> scope=null
            # This prevents redundant headers like "docs(docs):"
            commit_type = extended_data.type or extended_data.get_type("feat")
            if effective_scope and commit_type:
                redundant_scopes = {
                    "docs": ["docs", "documentation", "doc"],
                    "test": ["test", "tests", "testing"],
                    "ci": ["ci", "pipeline", "workflows"],
                    "build": ["build", "deps", "dependencies"],
                }
                if commit_type.lower() in redundant_scopes:
                    if effective_scope.lower() in redundant_scopes[commit_type.lower()]:
                        effective_scope = None

            # Apply effective scope to extended_data
            extended_data.scope = effective_scope

            # Apply ticket override if provided
            if effective_ticket:
                extended_data.ticket = effective_ticket

            # Try to extract ticket from branch if not provided and using ticket style
            if not extended_data.ticket and effective_profile == StyleProfile.TICKET:
                try:
                    branch = get_branch()
                    extracted_ticket = extract_ticket_from_branch(branch, style_config.ticket_key_regex)
                    if extracted_ticket:
                        extended_data.ticket = extracted_ticket
                except Exception:
                    pass

            # Infer commit type if using conventional/blueprint style and not provided
            if effective_profile in (StyleProfile.CONVENTIONAL, StyleProfile.BLUEPRINT) and not extended_data.type:
                inferred_type = infer_commit_type(staged_files)
                if inferred_type:
                    extended_data.type = inferred_type

            # Render the commit message with style
            message = render_commit_message_styled(
                data=extended_data,
                config=style_config,
                override_style=override_style,
                override_scope=effective_scope,
                override_ticket=effective_ticket,
                no_scope=effective_no_scope,
            )

            # Determine what overrides to save (only save if user explicitly provided CLI flags)
            scope_to_save = scope if scope and scope.lower() != "auto" else None
            ticket_to_save = ticket if ticket else None
            no_scope_to_save = no_scope

            # Save to cache (including raw LLM response and rendering overrides)
            save_cache(
                repo_root=repo_root,
                context_hash=current_hash,
                message=message,
                model=llm_result.model,
                input_tokens=llm_result.input_tokens,
                output_tokens=llm_result.output_tokens,
                staged_files=staged_files,
                diff_preview=diff_preview,
                raw_response=llm_raw_response or "",
                input_chars=llm_result.input_chars,
                prompt_chars=llm_result.prompt_chars,
                output_chars=llm_result.output_chars,
                scope_override=scope_to_save,
                ticket_override=ticket_to_save,
                no_scope_override=no_scope_to_save,
            )

        # Step 8: Get message file path
        message_file = get_message_file(repo_root)

        # Step 9: If --edit flag, open editor
        if edit:
            _open_editor(message_file)
            # Re-read the file after editing
            message = message_file.read_text()
            # Update the message cache (but keep original metadata for diff comparison)
            update_message_cache(repo_root, message)
            typer.echo("Message updated from editor.", err=True)

        # Save rendering overrides to metadata if user provided any CLI flags
        # These persist with the cached message until regeneration or commit
        if scope or no_scope or ticket:
            update_metadata_overrides(
                repo_root=repo_root,
                scope_override=scope if scope and scope.lower() != "auto" else None,
                ticket_override=ticket,
                no_scope_override=no_scope,
            )

        # Step 9: Print the final message to stdout
        typer.echo("")
        typer.echo("=" * 60)
        typer.echo(message)
        typer.echo("=" * 60)
        typer.echo("")
        typer.echo("Run 'hunknote commit' to commit with this message.", err=True)

    except NoStagedChangesError:
        # Display a git-style message for no staged changes
        typer.echo("On branch " + _get_current_branch_safe(), err=True)
        typer.echo("", err=True)
        typer.echo("nothing to commit (no changes staged for commit)", err=True)
        typer.echo("", err=True)
        typer.echo("Stage your changes first with:", err=True)
        typer.echo("  git add <file>...", err=True)
        typer.echo("", err=True)
        typer.echo("Then run hunknote again.", err=True)
        raise typer.Exit(1)
    except MissingAPIKeyError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except GitError as e:
        typer.echo(f"Git error: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"LLM error: {e}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
