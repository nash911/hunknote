"""CLI entry point for hunknote."""

import difflib
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

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
    save_cache,
    update_message_cache,
)
from hunknote.formatters import render_commit_message
from hunknote.git_ctx import (
    GitError,
    NoStagedChangesError,
    build_context_bundle,
    get_repo_root,
    get_staged_diff,
    get_status,
)
from hunknote.llm import LLMError, MissingAPIKeyError, generate_commit_json
from hunknote.user_config import (
    add_ignore_pattern,
    get_ignore_patterns,
    remove_ignore_pattern,
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


def _display_debug_info(
    repo_root: Path,
    metadata: CacheMetadata,
    current_message: str,
    cache_valid: bool,
) -> None:
    """Display debug information about the cache.

    Args:
        repo_root: The root directory of the git repository.
        metadata: The cache metadata.
        current_message: The current commit message (may be edited).
        cache_valid: Whether the cache is currently valid.
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
    typer.echo(f"Tokens: {metadata.input_tokens} input / {metadata.output_tokens} output")
    typer.echo()

    # Staged files
    typer.echo("Staged Files:")
    for f in metadata.staged_files:
        typer.echo(f"  - {f}")
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
    edit: bool = typer.Option(
        False,
        "--edit",
        "-e",
        help="Open the generated message file in an editor for manual edits",
    ),
    commit: bool = typer.Option(
        False,
        "--commit",
        "-c",
        help="Perform the commit using the generated message",
    ),
) -> None:
    """Generate an AI-powered git commit message from staged changes."""
    # If a subcommand is invoked, don't run the default behavior
    if ctx.invoked_subcommand is not None:
        return

    # Load global configuration
    from hunknote.config import load_config
    load_config()

    try:
        # Step 1: Get repo root
        repo_root = get_repo_root()

        # Step 2: Build context bundle
        typer.echo("Collecting git context...", err=True)
        context_bundle = build_context_bundle(max_chars=max_diff_chars)

        # Step 3: Compute context hash
        current_hash = compute_context_hash(context_bundle)

        # Step 4: Extract staged files and diff preview for metadata
        status_output = get_status()
        staged_files = extract_staged_files(status_output)
        staged_diff = get_staged_diff(max_chars=max_diff_chars)
        diff_preview = get_diff_preview(staged_diff, max_chars=500)

        # Step 5: Check cache validity (unless --regenerate)
        cache_valid = not regenerate and is_cache_valid(repo_root, current_hash)

        if cache_valid:
            # Use cached message
            typer.echo("Using cached commit message...", err=True)
            message = load_cached_message(repo_root)
            metadata = load_cache_metadata(repo_root)
        else:
            # Generate new message via LLM
            typer.echo("Generating commit message...", err=True)
            llm_result = generate_commit_json(context_bundle)


            # Render the commit message
            message = render_commit_message(llm_result.commit_json)

            # Save to cache
            save_cache(
                repo_root=repo_root,
                context_hash=current_hash,
                message=message,
                model=llm_result.model,
                input_tokens=llm_result.input_tokens,
                output_tokens=llm_result.output_tokens,
                staged_files=staged_files,
                diff_preview=diff_preview,
            )
            metadata = load_cache_metadata(repo_root)

        # Step 6: Handle --debug flag
        if debug:
            if metadata:
                _display_debug_info(repo_root, metadata, message, cache_valid)
            else:
                typer.echo("No cache metadata found.", err=True)
            raise typer.Exit(0)

        # Step 7: Get message file path
        message_file = get_message_file(repo_root)

        # Step 8: If --edit flag, open editor
        if edit:
            _open_editor(message_file)
            # Re-read the file after editing
            message = message_file.read_text()
            # Update the message cache (but keep original metadata for diff comparison)
            update_message_cache(repo_root, message)
            typer.echo("Message updated from editor.", err=True)

        # Step 9: Print the final message to stdout
        typer.echo("")
        typer.echo("=" * 60)
        typer.echo(message)
        typer.echo("=" * 60)

        # Step 10: If --commit flag, perform the commit
        if commit:
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
                # Invalidate cache after successful commit
                invalidate_cache(repo_root)
            else:
                typer.echo("Commit failed!", err=True)
                typer.echo(result.stderr, err=True)
                raise typer.Exit(1)

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
