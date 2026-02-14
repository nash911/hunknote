"""CLI entry point for hunknote."""

import difflib
import os
import shutil
import subprocess
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
    get_branch,
)
from hunknote.llm import LLMError, MissingAPIKeyError, generate_commit_json
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
    ExtendedCommitJSON,
    PROFILE_DESCRIPTIONS,
    load_style_config_from_dict,
    render_commit_message_styled,
    extract_ticket_from_branch,
    infer_commit_type,
)
from hunknote.scope import (
    ScopeStrategy,
    ScopeConfig,
    ScopeResult,
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
        help="Profile name to show (default, conventional, ticket, kernel)"
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
        typer.echo("Valid profiles: default, conventional, ticket, kernel")
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
    if style_profile == StyleProfile.CONVENTIONAL:
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
        help="Profile name (default, conventional, ticket, kernel)"
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
        typer.echo("Valid profiles: default, conventional, ticket, kernel")
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
    style: Optional[str] = typer.Option(
        None,
        "--style",
        help="Override commit style profile (default, conventional, ticket, kernel)",
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
            typer.echo("Valid styles: default, conventional, ticket, kernel")
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

    try:
        # Step 1: Get repo root
        repo_root = get_repo_root()

        # Step 2: Build context bundle
        typer.echo("Collecting git context...", err=True)
        context_bundle = build_context_bundle(max_chars=max_diff_chars)

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

        # Step 5: Determine effective scope (CLI override > inference > none)
        effective_scope = None
        scope_result = None

        if no_scope:
            # User explicitly disabled scope
            effective_scope = None
        elif scope and scope.lower() != "auto":
            # User provided explicit scope
            effective_scope = scope
        elif scope_config.enabled and not no_scope:
            # Infer scope from staged files
            scope_result = infer_scope(staged_files, scope_config)
            if scope_result.scope:
                effective_scope = scope_result.scope
                if debug:
                    typer.echo(f"Inferred scope: {scope_result.scope} ({scope_result.reason})", err=True)

        # Step 6: Compute context hash (include style and scope for cache invalidation)
        hash_input = f"{context_bundle}|style={effective_profile.value}|scope={effective_scope}|ticket={ticket}"
        current_hash = compute_context_hash(hash_input)

        # Step 7: Check cache validity (unless --regenerate)
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

            # Convert to ExtendedCommitJSON for styled rendering
            extended_data = ExtendedCommitJSON(
                title=llm_result.commit_json.title,
                body_bullets=llm_result.commit_json.body_bullets,
                # LLM may provide extended fields in the future
                type=getattr(llm_result.commit_json, 'type', None),
                scope=effective_scope or getattr(llm_result.commit_json, 'scope', None),
                subject=getattr(llm_result.commit_json, 'subject', None),
                ticket=ticket,
            )

            # Try to extract ticket from branch if not provided and using ticket style
            if not ticket and effective_profile == StyleProfile.TICKET:
                try:
                    branch = get_branch()
                    extracted_ticket = extract_ticket_from_branch(branch, style_config.ticket_key_regex)
                    if extracted_ticket:
                        extended_data.ticket = extracted_ticket
                except Exception:
                    pass

            # Infer commit type if using conventional style and not provided
            if effective_profile == StyleProfile.CONVENTIONAL and not extended_data.type:
                inferred_type = infer_commit_type(staged_files)
                if inferred_type:
                    extended_data.type = inferred_type

            # Render the commit message with style
            message = render_commit_message_styled(
                data=extended_data,
                config=style_config,
                override_style=override_style,
                override_scope=effective_scope,
                override_ticket=ticket,
                no_scope=no_scope,
            )

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

        # Step 8: Handle --debug flag
        if debug:
            if metadata:
                _display_debug_info(repo_root, metadata, message, cache_valid)
                # Show scope inference info
                if scope_result:
                    typer.echo(f"\n[SCOPE INFERENCE]", err=True)
                    typer.echo(f"  Strategy: {scope_result.strategy_used.value if scope_result.strategy_used else 'N/A'}", err=True)
                    typer.echo(f"  Inferred: {scope_result.scope or 'None'}", err=True)
                    typer.echo(f"  Confidence: {scope_result.confidence:.0%}", err=True)
                    typer.echo(f"  Reason: {scope_result.reason}", err=True)
            else:
                typer.echo("No cache metadata found.", err=True)
            raise typer.Exit(0)

        # Step 9: Get message file path
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
