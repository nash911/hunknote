"""Main CLI command for generating commit messages."""

from pathlib import Path
from typing import Optional

import typer

from hunknote.cache import (
    compute_context_hash,
    extract_staged_files,
    get_diff_preview,
    get_message_file,
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
from hunknote.styles import (
    StyleProfile,
    render_commit_message_styled,
    extract_ticket_from_branch,
    infer_commit_type,
)
from hunknote.scope import ScopeStrategy, infer_scope
from hunknote.cli.utils import (
    get_current_branch_safe,
    open_editor,
    process_intent_options,
    compute_intent_fingerprint,
    inject_intent_into_context,
    display_debug_info,
    get_effective_style_config,
    get_effective_scope_config,
)


def main_command(
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
    intent_content = process_intent_options(intent, intent_file)

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
                scope_config = get_effective_scope_config()
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

                display_debug_info(repo_root, metadata, message, True, intent_content)
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
            context_bundle = inject_intent_into_context(context_bundle, intent_content)

        # Step 3: Get configurations
        style_config = get_effective_style_config()
        scope_config = get_effective_scope_config()
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
        intent_fingerprint = compute_intent_fingerprint(intent_content)

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
                            except (GitError, ValueError, AttributeError):
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
                except (GitError, ValueError, AttributeError):
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
            open_editor(message_file)
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
        typer.echo("On branch " + get_current_branch_safe(), err=True)
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

