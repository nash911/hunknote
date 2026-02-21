"""CLI commands for style profile management."""

import typer

from hunknote import global_config
from hunknote.git_ctx import GitError, get_repo_root
from hunknote.styles import StyleProfile, PROFILE_DESCRIPTIONS
from hunknote.user_config import (
    get_repo_style_config,
    set_repo_style_profile,
)

# Subcommand group for style profile management
style_app = typer.Typer(
    name="style",
    help="Manage commit message style profiles",
    add_completion=False,
)


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

